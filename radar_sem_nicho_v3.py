#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Radar YouTube v3 SEM FILTRO DE TEMA: primeiro upload publico conhecido recente.

Usa APENAS a YouTube Data API v3 e a biblioteca padrao do Python (3.10+).
Descoberta amostral, sem vidIQ. Canais mistos nao sao descartados: analisa
videos >3min independentemente das visualizacoes em possiveis Shorts <=3min.

Exemplo Windows PowerShell:
  # Coloque sua API Key (so a chave, em uma linha) no arquivo youtube_api_key.txt
  # situado na mesma pasta deste script. Nao precisa configurar PowerShell.
  python radar_sem_nicho_v3.py

Como alternativa, a variavel de ambiente YOUTUBE_API_KEY ainda funciona.
O arquivo txt local tem prioridade quando contem uma chave configurada.
NUNCA publique o arquivo de chave no GitHub.

Por padrao a janela sao os ultimos 21 dias corridos (inclusive), em UTC.
SEM palavras-chave, categorias ou topicos na descoberta (search.list sem q).
AVISOS: a API publica nao informa diretamente se um video e Short, nem a
localizacao dos espectadores, nem historico retroativo de inscritos ou RPM.
O campo regionCode prioriza videos disponiveis na regiao; nao localiza audiencia.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
import re
import statistics
import sys
import time
from urllib import error, parse, request

BASE = "https://www.googleapis.com/youtube/v3/"
# Mercados: pais declarado do canal; pais de quem assiste nao e publico.
COUNTRIES = {
    "US": "Estados Unidos", "CA": "Canada", "GB": "Reino Unido",
    "AU": "Australia", "DE": "Alemanha", "NO": "Noruega",
    "CH": "Suica", "DK": "Dinamarca", "NL": "Paises Baixos",
}
# Descoberta inteiramente sem tema: particionar intervalo e buscar videos de
# duracao media ou longa, com ordenacao por DATA e por VIEWS. Nenhum parametro
# q, videoCategoryId, topicId ou palavras-chave e usado em buscas.
# Com defaults: 5 paises x 4 janelas x 2 duracoes x 2 ordenacoes = 80 buscas.
DEFAULT_SHARDS = 4
DURATIONS = ("medium", "long")
ORDERS = ("viewCount", "date")

# Separacao confiavel por duracao: um Short tem no maximo 180 segundos.
# Ate 180s pode ser Short OU video horizontal tradicional: portanto 'INDEFINIDO'.
SHORT_POSSIBLE_MAX_S = 180
MIDROLL_MIN_S = 480
VIDEO_COLUMNS = [
    "coleta_utc", "pais_busca", "pais_declarado", "confianca_pais", "canal", "channel_id",
    "video_id", "link_video", "titulo", "publicado_utc", "duracao_seg", "faixa_duracao", "categoria_youtube_id", "categoria_youtube_nome",
    "possivel_short", "formato_confirmado_manual", "livestream", "views", "likes", "comentarios", "views_por_dia",
]
CHANNEL_COLUMNS = [
    "coleta_utc", "pais_busca", "codigo_pais", "pais_declarado", "confianca_pais",
    "canal", "channel_id", "url", "criado_utc", "primeiro_publico_conhecido_utc",
    "verificacao_primeiro_video", "inscritos_atual", "views_canal_atual",
    "videos_canal_atual", "videos_na_janela", "videos_com_metricas",
    "videos_ate_3min_indefinidos", "videos_shorts_confirmados", "videos_long_ate3_confirmados", "videos_long_3a8", "videos_long_8a20",
    "videos_long_20mais", "videos_long_total", "videos_long_8mais", "lives",
    "pct_publicacoes_long", "pct_publicacoes_ate3", "views_ate3", "views_shorts_confirmados", "views_long_total",
    "views_long_8mais", "views_lives", "pct_views_long", "media_views_ate3",
    "mediana_views_ate3", "media_views_shorts_confirmados", "media_views_long", "mediana_views_long",
    "media_views_8mais", "mediana_views_8mais", "mediana_views_dia_long",
    "max_views_long", "pct_views_top1_long", "pct_views_top3_long",
    "likes_por_view_long", "score_longform", "categoria_oportunidade",
    "qualificado", "restricao_dados", "top_video_long", "top_video_long_url",
    "origem_descoberta", "consulta_regiao_nao_prova_audiencia", "categorias_longform_ids", "categoria_longform_predominante_id", "categoria_longform_predominante_nome", "videos_longform_sem_categoria", "media_views_por_dia_long", "nicho_nao_filtrado",
]
SNAPSHOT_COLUMNS = ["coleta_utc", "channel_id", "pais_busca", "canal", "inscritos",
                    "views_canal", "videos_canal", "videos_long_na_janela", "views_long_na_janela"]

# A credencial fica em arquivo LOCAL, ignorado pelo Git, sem alterar o Python.
# Resolvida relativamente ao script: funciona mesmo abrindo PowerShell em outro local.
API_KEY_FILENAME = "youtube_api_key.txt"
API_KEY_PLACEHOLDERS = {
    "COLE_SUA_CHAVE_AQUI", "COLE_SUA_API_KEY_AQUI", "SUA_CHAVE_AQUI",
    "COLE_SUA_API_KEY_DO_YOUTUBE_AQUI", "SUA_CHAVE",
}


def load_api_key() -> str:
    """Ler arquivo TXT local; se nao estiver preenchido, usar variavel de ambiente.

    Nunca imprime a chave. Evita depender do diretorio de trabalho (cwd).
    """
    path = Path(__file__).resolve().parent / API_KEY_FILENAME
    if path.is_file():
        try:
            raw = path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError) as exc:
            raise SystemExit(
                f"Nao consegui ler {API_KEY_FILENAME}: {exc.__class__.__name__}. "
                "Confira se o arquivo e um TXT UTF-8 valido."
            ) from None
        rows = [line.strip() for line in raw.splitlines()
                if line.strip() and not line.lstrip().startswith("#")]
        if len(rows) > 1:
            raise SystemExit(
                f"{API_KEY_FILENAME} deve conter apenas uma linha com a chave, "
                "sem texto adicional."
            )
        if rows:
            key = rows[0]
            if key.startswith("YOUTUBE_API_KEY="):
                key = key.partition("=")[2].strip()
            key = key.strip("\"'").strip()
            if key and key.upper() not in API_KEY_PLACEHOLDERS:
                if any(char.isspace() for char in key):
                    raise SystemExit(
                        f"A chave em {API_KEY_FILENAME} possui espacos ou quebras "
                        "de linha; cole somente a chave."
                    )
                return key

    env_key = os.getenv("YOUTUBE_API_KEY", "").strip()
    if env_key and env_key.upper() not in API_KEY_PLACEHOLDERS:
        return env_key
    raise SystemExit(
        "API Key nao encontrada. Abra youtube_api_key.txt na mesma pasta do "
        "radar_sem_nicho_v3.py, substitua COLE_SUA_CHAVE_AQUI pela chave da "
        "YouTube Data API v3 e salve o arquivo. Nao envie ou publique sua chave."
    )


def duration_seconds(value: str | None) -> int | None:
    match = re.fullmatch(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?", value or "")
    if not match:
        return None
    days, hours, minutes, secs = (int(x or 0) for x in match.groups())
    return days * 86400 + hours * 3600 + minutes * 60 + secs


def num(value, default=0) -> int:
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def pct(a: float, b: float) -> float:
    return round(100.0 * a / b, 2) if b else 0.0


def average(xs):
    return round(statistics.mean(xs), 2) if xs else ""


def median(xs):
    return round(statistics.median(xs), 2) if xs else ""


def read_csv(path: Path):
    if not path or not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8-sig") as fp:
        return list(csv.DictReader(fp))


def write_csv(path: Path, data: list[dict], fields: list[str]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as fp:
        writer = csv.DictWriter(fp, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(data)


def chunks(xs, size=50):
    for start in range(0, len(xs), size):
        yield xs[start:start + size]


def iso_date(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


class QuotaStop(RuntimeError):
    """Limite diario da API ou limite local de consultas."""


def search_quota_exhausted(message: str) -> bool:
    """Detecta inclusive HTTP 429 com reason=rateLimitExceeded e limite *per day*.

    O Google pode devolver reason=rateLimitExceeded para limites diarios granulares.
    Nao confundir isso com sobrecarga temporaria por segundo.
    """
    msg = str(message).lower()
    return (
        "dailylimitexceeded" in msg
        or "quotaexceeded" in msg
        or ("quota exceeded" in msg and "search queries per day" in msg)
    )


class YouTube:
    def __init__(self, api_key: str, max_search: int, max_other: int):
        self.key = api_key
        self.limit_search = max_search
        self.limit_other = max_other
        self.search_calls = 0
        self.other_calls = 0

    def get(self, endpoint: str, **kwargs):
        if endpoint == "search":
            if self.search_calls >= self.limit_search:
                raise QuotaStop("Limite local de chamadas search.list atingido")
            self.search_calls += 1
        else:
            if self.other_calls >= self.limit_other:
                raise QuotaStop("Limite local de outras chamadas de API atingido")
            self.other_calls += 1
        kwargs["key"] = self.key
        url = BASE + endpoint + "?" + parse.urlencode(kwargs)
        for retry in range(4):
            try:
                with request.urlopen(url, timeout=35) as rsp:
                    return json.load(rsp)
            except error.HTTPError as exc:
                body = exc.read().decode("utf-8", "replace")[:1500]
                # Nao fazer novas tentativas quando a cota DIARIA de search.list
                # acabou. Isso evita 75 erros repetidos e protege os CSVs validos.
                if endpoint == "search" and search_quota_exhausted(body):
                    raise QuotaStop(
                        "COTA_DIARIA_SEARCH_ESGOTADA: limite Search Queries per day "
                        "(HTTP " + str(exc.code) + "). Aguarde renovacao da cota."
                    ) from exc
                if exc.code in (429, 500, 502, 503) and retry < 3:
                    time.sleep(2 ** retry)
                    continue
                raise RuntimeError(f"API {endpoint}: HTTP {exc.code}: {body}") from exc
        raise RuntimeError("Nao foi possivel consultar a API")


def search_plan(codes: list[str], start: str, end_exclusive: str, shards: int):
    """Gera consultas geograficas/temporais sem qualquer filtro de tema."""
    if shards < 1:
        raise ValueError("shards deve ser positivo")
    begin, end = iso_date(start), iso_date(end_exclusive)
    total = (end - begin).total_seconds()
    if total <= 0:
        raise ValueError("janela invalida")
    # Round robin pais por pais + fatia temporal, beneficiando todos sob quota.
    for shard in range(shards):
        left = begin + timedelta(seconds=total * shard/shards)
        right = begin + timedelta(seconds=total * (shard+1)/shards)
        for code in codes:
            for duration in DURATIONS:
                for order in ORDERS:
                    yield {
                        "code": code, "start":left.isoformat(timespec="seconds").replace("+00:00","Z"),
                        "end":right.isoformat(timespec="seconds").replace("+00:00","Z"),
                        "duration":duration,"order":order,"shard":shard+1,
                    }


def discover(api: YouTube, codes: list[str], start: str, end_exclusive: str,
             max_per_country: int, seed_rows: list[dict], shards: int,
             pages_per_search: int = 1):
    """Pesquisa SEM termo, topico ou categoria; descobertas sao AMOSTRA."""
    found = defaultdict(lambda: defaultdict(set))
    audit = []
    for row in seed_rows:
        cid = row.get("id") or row.get("channel_id")
        code = row.get("codigo") or row.get("codigo_pais") or row.get("pais_busca")
        if code not in codes and code in COUNTRIES.values():
            code = next((k for k,v in COUNTRIES.items() if v==code), None)
        if code in codes and cid and re.fullmatch(r"UC[A-Za-z0-9_-]{22}", cid):
            found[code][cid].add("semente_historica_sem_filtro_atual")
    stop = False
    for plan in search_plan(codes, start, end_exclusive, shards):
        if api.search_calls >= api.limit_search or stop:
            break
        params={"part":"snippet","type":"video","videoDuration":plan["duration"],
                "order":plan["order"],"regionCode":plan["code"],"safeSearch":"none","maxResults":50,
                "publishedAfter":plan["start"],"publishedBefore":plan["end"]}
        token = None
        for page in range(pages_per_search):
            if api.search_calls >= api.limit_search:
                break
            try:
                rsp = api.get("search",**({**params,"pageToken":token} if token else params))
                items = rsp.get("items",[])
                for item in items:
                    cid=item.get("snippet",{}).get("channelId")
                    if cid:
                        found[plan["code"]][cid].add(f"amostra_{plan['shard']}_{plan['duration']}_{plan['order']}")
                audit.append({"pais_busca":plan["code"],"fatia":plan["shard"],
                              "inicio_utc":plan["start"],"fim_utc":plan["end"],
                              "ordenacao":plan["order"],"duracao_filtro":plan["duration"],
                              "pagina":page+1,"q_enviado":"NAO","categoria_filtrada":"NAO",
                              "videos_retornados":len(items),
                              "canais_unicos_acumulados":len(found[plan["code"]]),"erro":""})
                token = rsp.get("nextPageToken")
                if not token:
                    break
            except (QuotaStop, RuntimeError) as exc:
                audit.append({"pais_busca":plan["code"],"fatia":plan["shard"],
                              "inicio_utc":plan["start"],"fim_utc":plan["end"],
                              "ordenacao":plan["order"],"duracao_filtro":plan["duration"],
                              "pagina":page+1,"q_enviado":"NAO","categoria_filtrada":"NAO",
                              "videos_retornados":0,"canais_unicos_acumulados":len(found[plan["code"]]),"erro":str(exc)[:500]})
                if isinstance(exc, QuotaStop) or search_quota_exhausted(str(exc)):
                    stop = True
                break
    # Evita truncar antes da verificacao por data de primeiro upload; caso
    # exista limite, preserva canais recorrentes entre fatias/ordenacoes.
    if max_per_country:
        for code in codes:
            if len(found[code]) > max_per_country:
                ordered = sorted(found[code], key=lambda cid:(-len(found[code][cid]),cid))
                found[code] = defaultdict(set,{cid:found[code][cid] for cid in ordered[:max_per_country]})
    for code in codes:
        print(f"Descoberta SEM nicho {code}: {len(found[code])} canais candidatos")
    return found,audit


def assign_market(channel_id: str, channel: dict, found: dict, codes: list[str]):
    """Escolhe uma UNICA regiao de busca; sem confundi-la com a audiencia."""
    offered = [code for code in codes if channel_id in found[code]]
    if not offered:
        return None
    declared = channel.get("snippet",{}).get("country","")
    if declared in offered:
        return declared
    return sorted(offered,key=lambda c:(-len(found[c][channel_id]),codes.index(c)))[0]


def category_names(api: YouTube, codes: list[str]):
    """Rotulos somente APOS descoberta: nenhuma categoria limita pesquisa."""
    names={}
    try:
        rsp=api.get("videoCategories",part="snippet",regionCode="US")
        for x in rsp.get("items",[]):
            names[x.get("id","")]=x.get("snippet",{}).get("title","")
    except (RuntimeError,QuotaStop):
        pass
    return names


def get_channel_metadata(api: YouTube, ids):
    output = {}
    for batch in chunks(sorted(set(ids))):
        rsp = api.get("channels", part="snippet,statistics,contentDetails", id=",".join(batch))
        output.update({c["id"]:c for c in rsp.get("items", [])})
    return output


def scan_public_uploads(api: YouTube, channel: dict, start: str, end: str, max_pages: int):
    """Prova ausencia de videos publicos ANTERIORES apenas se todas as paginas forem vistas.

    Um video antigo observado ja e suficiente para descartar a elegibilidade.
    A lista de uploads do canal pode mudar: 'primeiro' e sempre conhecido hoje.
    """
    playlist = channel.get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads")
    if not playlist:
        return "SEM_PLAYLIST", "", []
    token = None
    seen_ids = set()
    included = []
    oldest = None
    for _ in range(max_pages):
        params = {"part":"contentDetails", "playlistId":playlist, "maxResults":50}
        if token:
            params["pageToken"] = token
        rsp = api.get("playlistItems", **params)
        for p in rsp.get("items", []):
            det = p.get("contentDetails", {})
            at, vid = det.get("videoPublishedAt"), det.get("videoId")
            if not vid or not at:
                continue
            oldest = min(at, oldest) if oldest else at
            if at < start:
                return "VIDEO_PUBLICO_ANTIGO", at, []
            if start <= at < end and vid not in seen_ids:
                seen_ids.add(vid)
                included.append(vid)
        token = rsp.get("nextPageToken")
        if not token:
            break
    else:
        if token:
            return "PAGINACAO_INCOMPLETA", oldest or "", []
    if not oldest:
        return "SEM_UPLOAD_PUBLICO", "", []
    if oldest >= end:
        return "PRIMEIRO_POSTERIOR_A_JANELA", oldest, []
    return "ELEGIVEL", oldest, included


def get_video_details(api: YouTube, video_ids: list[str]) -> list[dict]:
    video_data = []
    for ids in chunks(list(dict.fromkeys(video_ids))):
        rsp = api.get("videos", part="snippet,statistics,contentDetails,liveStreamingDetails",
                      id=",".join(ids))
        video_data.extend(rsp.get("items", []))
    return video_data


def classify_video(video: dict, channel: dict, market: str, checked_at: datetime, manual: dict | None = None, categories: dict | None = None):
    seconds = duration_seconds(video.get("contentDetails", {}).get("duration"))
    snippet = video.get("snippet", {})
    is_live = bool(video.get("liveStreamingDetails")) or snippet.get("liveBroadcastContent") in ("live", "upcoming")
    if is_live:
        band = "LIVE"
    elif seconds is None:
        band = "DURACAO_DESCONHECIDA"
    elif seconds <= SHORT_POSSIBLE_MAX_S:
        band = "ATE_3M_POSSIVEL_SHORT"
    elif seconds < MIDROLL_MIN_S:
        band = "LONG_3A8"
    elif seconds < 1200:
        band = "LONG_8A20"
    else:
        band = "LONG_20MAIS"
    manual = manual or {}
    confirm = manual.get(video["id"], "")
    if not is_live and seconds is not None and seconds <= SHORT_POSSIBLE_MAX_S:
        if confirm == "SHORT":
            band = "SHORT_CONFIRMADO"
        elif confirm == "LONG":
            band = "LONG_ATE3_VERIFICADO"
    if confirm == "LIVE":
        band = "LIVE"
        is_live = True
    views = num(video.get("statistics", {}).get("viewCount"), None)
    likes = num(video.get("statistics", {}).get("likeCount"), None)
    comments = num(video.get("statistics", {}).get("commentCount"), None)
    video_at = snippet.get("publishedAt", "")
    age_days = max((checked_at - iso_date(video_at)).total_seconds() / 86400.0, 1.0) if video_at else None
    cid = channel["id"]
    return {
        "coleta_utc":checked_at.isoformat(), "pais_busca":market,
        "pais_declarado":channel.get("snippet", {}).get("country") or "",
        "confianca_pais":"DECLARADO" if channel.get("snippet", {}).get("country") == market else "BUSCA_REGIONAL_NAO_VERIFICADO",
        "canal":channel.get("snippet", {}).get("title", ""), "channel_id":cid,
        "video_id":video["id"], "link_video":"https://www.youtube.com/watch?v=" + video["id"],
        "titulo":snippet.get("title", ""), "publicado_utc":video_at,
        "categoria_youtube_id":snippet.get("categoryId", ""),
        "categoria_youtube_nome":(categories or {}).get(snippet.get("categoryId", ""), ""),
        "duracao_seg":seconds if seconds is not None else "", "faixa_duracao":band,
        "possivel_short": "INDEFINIDO" if band == "ATE_3M_POSSIVEL_SHORT" else "SIM_CONFIRMADO" if band == "SHORT_CONFIRMADO" else "NAO" if band.startswith("LONG_") else "N/A",
        "formato_confirmado_manual": confirm,
        "livestream":int(is_live), "views":views if views is not None else "",
        "likes":likes if likes is not None else "", "comentarios":comments if comments is not None else "",
        "views_por_dia":round(views/age_days, 2) if views is not None and age_days is not None else "",
    }


def analyze(channel: dict, market: str, videorows: list[dict], first: str,
            status: str, checked_at: datetime, discovery_sources: set[str],
            min_long_count: int, min_long_views: int):
    meta = channel.get("snippet", {})
    stats = channel.get("statistics", {})
    bands = Counter(v["faixa_duracao"] for v in videorows)
    valid = [v for v in videorows if not v["livestream"] and v["faixa_duracao"] != "DURACAO_DESCONHECIDA"]
    possible = [v for v in valid if v["faixa_duracao"] == "ATE_3M_POSSIVEL_SHORT"]
    confirmed_short = [v for v in valid if v["faixa_duracao"] == "SHORT_CONFIRMADO"]
    short_and_possible = possible + confirmed_short
    long = [v for v in valid if v["faixa_duracao"].startswith("LONG_")]
    long_8 = [v for v in long if v["duracao_seg"] >= MIDROLL_MIN_S]
    def vs(xs):
        return [num(v["views"]) for v in xs if v["views"] != ""]
    pv, lv, v8 = vs(short_and_possible), vs(long), vs(long_8)
    views_possible, views_long, views_8 = sum(pv), sum(lv), sum(v8)
    views_known = views_possible + views_long
    allcount = len(valid)
    long_medians = median(lv)
    long_velocity = median([float(v["views_por_dia"]) for v in long if v["views_por_dia"] != ""])
    score = round(2.0*math.log10(1+(long_medians or 0)) +
        1.0*math.log10(1+views_long) +
        0.5*math.log10(1+(long_velocity or 0)) +
        0.2*min(len(long), 10) + 0.3*min(len(long_8), 5), 3) if long else 0
    category = "SEM_LONGFORM"
    if long:
        if len(long)>=2 and len(long_8)>=1 and views_long >= min_long_views:
            category = "PRIORITARIO_LONGFORM" if pct(views_long,views_known)>=50 else "MISTO_PROMISSOR"
        elif views_long >= min_long_views:
            category = "LONGFORM_EM_TESTE"
        else:
            category = "LONGFORM_COM_POUCAS_VIEWS"
    qualifies = status=="ELEGIVEL" and len(long)>=min_long_count and views_long >= min_long_views
    ranked = sorted(long, key=lambda v: num(v["views"]), reverse=True)
    category_counter=Counter(v.get("categoria_youtube_id","") for v in long if v.get("categoria_youtube_id"))
    dominant_category=category_counter.most_common(1)[0][0] if category_counter else ""
    cat_by_id={v.get("categoria_youtube_id",""):v.get("categoria_youtube_nome","") for v in long}

    top = ranked[0] if ranked else {}
    likes_long = [num(v["likes"]) for v in long if v["likes"] != "" and v["views"] != ""]
    views_with_likes = [num(v["views"]) for v in long if v["likes"] != "" and v["views"] != ""]
    return {
        "coleta_utc": checked_at.isoformat(), "pais_busca": COUNTRIES[market], "codigo_pais":market,
        "pais_declarado":meta.get("country", ""),
        "confianca_pais":"DECLARADO" if meta.get("country") == market else "BUSCA_REGIONAL_NAO_VERIFICADO",
        "canal":meta.get("title", ""), "channel_id":channel["id"],
        "url":"https://www.youtube.com/channel/" + channel["id"],
        "criado_utc":meta.get("publishedAt", ""),
        "primeiro_publico_conhecido_utc":first, "verificacao_primeiro_video":status,
        "inscritos_atual":"" if stats.get("hiddenSubscriberCount") else stats.get("subscriberCount", ""),
        "views_canal_atual":stats.get("viewCount", ""), "videos_canal_atual":stats.get("videoCount", ""),
        "videos_na_janela":len(videorows), "videos_com_metricas":sum(v["views"] != "" for v in videorows),
        "videos_ate_3min_indefinidos":len(possible), "videos_shorts_confirmados":len(confirmed_short),
        "videos_long_ate3_confirmados":bands["LONG_ATE3_VERIFICADO"], "videos_long_3a8":bands["LONG_3A8"],
        "videos_long_8a20":bands["LONG_8A20"], "videos_long_20mais":bands["LONG_20MAIS"],
        "videos_long_total":len(long), "videos_long_8mais":len(long_8), "lives":bands["LIVE"],
        "pct_publicacoes_long":pct(len(long),allcount), "pct_publicacoes_ate3":pct(len(short_and_possible),allcount),
        "views_ate3":views_possible, "views_shorts_confirmados":sum(vs(confirmed_short)), "views_long_total":views_long, "views_long_8mais":views_8,
        "views_lives":sum(vs([v for v in videorows if v["faixa_duracao"] == "LIVE"])),
        "pct_views_long":pct(views_long, views_known),
        "media_views_ate3":average(pv), "mediana_views_ate3":median(pv),
        "media_views_shorts_confirmados":average(vs(confirmed_short)),
        "media_views_long":average(lv), "mediana_views_long":long_medians,
        "media_views_8mais":average(v8), "mediana_views_8mais":median(v8),
        "mediana_views_dia_long":long_velocity,
        "max_views_long":num(top.get("views", ""), 0),
        "pct_views_top1_long":pct(num(top.get("views", ""), 0),views_long),
        "pct_views_top3_long":pct(sum(num(v["views"]) for v in ranked[:3]),views_long),
        "likes_por_view_long":pct(sum(likes_long),sum(views_with_likes)) if views_with_likes else "",
        "score_longform":score, "categoria_oportunidade":category,
        "qualificado":"SIM" if qualifies else "NAO",
        "restricao_dados":"VERIFICAR_SHORTS_MANUAL" if possible else "SEM_CURTOS_INDEFINIDOS",
        "top_video_long":top.get("titulo", ""), "top_video_long_url":top.get("link_video", ""),
        "origem_descoberta":" | ".join(sorted(discovery_sources))[:300],
        "consulta_regiao_nao_prova_audiencia":"SIM",
        "categorias_longform_ids":" | ".join(f"{k}:{v}" for k,v in category_counter.most_common()),
        "categoria_longform_predominante_id":dominant_category,
        "categoria_longform_predominante_nome":cat_by_id.get(dominant_category,""),
        "videos_longform_sem_categoria":sum(not v.get("categoria_youtube_id") for v in long),
        "media_views_por_dia_long":average([float(v["views_por_dia"]) for v in long if v["views_por_dia"]!=""]),
        "nicho_nao_filtrado":"SIM",
    }


def derive_growth(snapshots: list[dict]):
    by_id = defaultdict(list)
    for snap in snapshots:
        by_id[snap["channel_id"]].append(snap)
    rows=[]
    for cid, series in by_id.items():
        series.sort(key=lambda s:s["coleta_utc"])
        if len(series)<2:
            continue
        first,last=series[0],series[-1]
        try:
            days=(iso_date(last["coleta_utc"])-iso_date(first["coleta_utc"])).total_seconds()/86400
        except Exception:
            continue
        rows.append({"channel_id":cid,"pais_busca":last["pais_busca"],"canal":last["canal"],
                     "primeira_coleta":first["coleta_utc"],"ultima_coleta":last["coleta_utc"],
                     "dias_monitorados":round(days,2),
                     "delta_inscritos":num(last["inscritos"],None)-num(first["inscritos"],None)
                     if str(last["inscritos"]).strip() and str(first["inscritos"]).strip() else "",
                     "delta_views_canal":num(last["views_canal"],None)-num(first["views_canal"],None)
                     if str(last["views_canal"]).strip() and str(first["views_canal"]).strip() else "",
                     "nota":"crescimento monitorado; NAO reconstruido retroativamente"})
    return rows


def parse_args(argv=None):
    p=argparse.ArgumentParser(description="Radar v3 sem temas: descoberta por data, regiao e formato")
    p.add_argument("--countries",default="US,CA,GB,AU,DE",help="Codigos separados por virgulas")
    p.add_argument("--target",type=int,default=50,help="Canais de long-form por pais (default 50)")
    p.add_argument("--days",type=int,default=21,help="Dias corridos inclusivos no radar")
    p.add_argument("--start",default=None,help="Data inicial UTC YYYY-MM-DD (opcional)")
    p.add_argument("--end",default=None,help="Data final UTC YYYY-MM-DD inclusiva (opcional)")
    p.add_argument("--seed-csv",default=None,help="CSV historico de candidatos; inclui canais ja encontrados")
    p.add_argument("--manual-csv",default=None,help="CSV opcional com video_id,tipo_confirmado (SHORT|LONG|LIVE)")
    p.add_argument("--output-dir",default="resultado_radar_sem_nicho_v3")
    p.add_argument("--shards",type=int,default=DEFAULT_SHARDS,help="Fatias temporais por pais (default 4)")
    p.add_argument("--pages-per-search",type=int,default=1,help="Paginacao por combinacao (default 1)")
    p.add_argument("--history-source",default=None,help="CSV de snapshots v2 a importar no historico v3")
    p.add_argument("--plan-only",action="store_true",help="Mostra a grade de buscas SEM tema, sem usar chave nem quota")
    p.add_argument("--max-search-requests",type=int,default=80)
    p.add_argument("--max-other-requests",type=int,default=6000)
    p.add_argument("--candidate-limit-per-country",type=int,default=800)
    p.add_argument("--max-upload-pages",type=int,default=30)
    p.add_argument("--min-long-uploads",type=int,default=1,
                   help="Canais com >= este numero de videos >3min (default 1)")
    p.add_argument("--min-long-views",type=int,default=1000,
                   help="Views acumuladas em long-forms da janela (default 1000)")
    return p.parse_args(argv)


def main(argv=None, api=None):
    args=parse_args(argv)
    if args.target<=0 or args.days<=0 or args.max_upload_pages<=0 or args.shards<=0 or args.pages_per_search<=0:
        raise SystemExit("target, days, max-upload-pages, shards e pages-per-search devem ser positivos")
    codes=list(dict.fromkeys(c.strip().upper() for c in args.countries.split(",") if c.strip()))
    if not codes or any(code not in COUNTRIES for code in codes):
        raise SystemExit("Pais desconhecido. Disponiveis: " + ", ".join(COUNTRIES))
    now=datetime.now(timezone.utc)
    end_date=datetime.strptime(args.end,"%Y-%m-%d").date() if args.end else now.date()
    start_date=datetime.strptime(args.start,"%Y-%m-%d").date() if args.start else end_date-timedelta(days=args.days-1)
    if start_date>end_date:
        raise SystemExit("--start deve ser menor ou igual a --end")
    start=f"{start_date.isoformat()}T00:00:00Z"
    end=f"{(end_date+timedelta(days=1)).isoformat()}T00:00:00Z"
    if args.plan_only:
        plan=list(search_plan(codes,start,end,args.shards))
        print(f"RADAR V3 - SEM TEMAS: {len(plan)} combinacoes possiveis; limite local {args.max_search_requests} chamadas search.list")
        for country in codes:
            scoped=[p for p in plan if p["code"]==country]
            print(f"  {country}: {len(scoped)} consultas - {args.shards} intervalos, duracoes medium/long, ordenacoes date/viewCount")
        print("Cada consulta EXCLUI: q, topicId, videoCategoryId. Nenhuma chamada a API realizada.")
        return None
    client = api if api is not None else YouTube(
        load_api_key(), args.max_search_requests, args.max_other_requests
    )
    if not getattr(client, "key", None):
        raise SystemExit("A API Key nao foi carregada corretamente.")
    out=Path(args.output_dir);out.mkdir(parents=True,exist_ok=True)
    seed=read_csv(Path(args.seed_csv)) if args.seed_csv else []
    manual_rows=read_csv(out/"revisao_short_manual.csv")
    if args.manual_csv:
        manual_rows += read_csv(Path(args.manual_csv))
    manual={row.get("video_id", ""): row.get("tipo_confirmado", "").strip().upper()
            for row in manual_rows if row.get("tipo_confirmado", "").strip().upper() in ("SHORT", "LONG", "LIVE")}
    hist_path=out/"historico_snapshots.csv"
    old_history=read_csv(hist_path)
    if args.history_source:
        old_history += read_csv(Path(args.history_source))
    old_history=list({(r.get("channel_id"),r.get("coleta_utc")):r for r in old_history if r.get("channel_id") and r.get("coleta_utc")}.values())
    watch_ids={r.get("channel_id") for r in old_history if r.get("channel_id")}
    found, searches=discover(client,codes,start,end,args.candidate_limit_per_country,seed,
                             args.shards,args.pages_per_search)
    quota_errors=[r for r in searches if search_quota_exhausted(r.get("erro", ""))
                  or "COTA_DIARIA_SEARCH_ESGOTADA" in r.get("erro", "")]
    if quota_errors:
        # Nunca sobrescrever os relatórios existentes com dados parciais.
        audit_fields=["pais_busca","fatia","inicio_utc","fim_utc","ordenacao","duracao_filtro",
                      "pagina","q_enviado","categoria_filtrada","videos_retornados",
                      "canais_unicos_acumulados","erro"]
        write_csv(out/"auditoria_busca_parcial_quota.csv",searches,audit_fields)
        (out/"status_coleta.json").write_text(json.dumps({
            "status":"INTERROMPIDA_QUOTA",
            "motivo":"Limite diario Search Queries per day atingido",
            "consultas_tentadas":len(searches),
            "consultas_bem_sucedidas":sum(not r.get("erro") for r in searches),
            "dados_anteriores_preservados":True,
            "aviso":"Execute novamente apos a renovacao da cota diaria",
        },ensure_ascii=False,indent=2),encoding="utf-8")
        raise SystemExit(
            "Cota diaria search.list esgotada. Interrompido imediatamente; "
            "rankings existentes PRESERVADOS. Veja status_coleta.json e "
            "auditoria_busca_parcial_quota.csv. Execute apos a renovacao da cota."
        )
    write_csv(out/"auditoria_busca.csv",searches,
              ["pais_busca","fatia","inicio_utc","fim_utc","ordenacao","duracao_filtro",
               "pagina","q_enviado","categoria_filtrada","videos_retornados",
               "canais_unicos_acumulados","erro"])
    ids={cid for code in codes for cid in found[code]} | watch_ids
    metadata=get_channel_metadata(client,ids)
    categories=category_names(client,codes)
    evals=[]; video_rows=[]; log=[]
    chosen={cid:assign_market(cid,channel,found,codes)
            for cid,channel in metadata.items() if any(cid in found[c] for c in codes)}
    stop=False
    for code in codes:
        relevant=[cid for cid,c in chosen.items() if c==code]
        print(f"Validando candidatos SEM nicho {COUNTRIES[code]}: {len(relevant)}")
        for cid in relevant:
            if stop:
                break
            channel=metadata[cid]
            declared=channel.get("snippet",{}).get("country","")
            source=set().union(*(found[c].get(cid,set()) for c in codes))
            try:
                status,first,uploads=scan_public_uploads(client,channel,start,end,args.max_upload_pages)
                if status=="ELEGIVEL":
                    videos=get_video_details(client,uploads)
                    newrows=[classify_video(v,channel,code,now,manual,categories) for v in videos]
                    video_rows.extend(newrows)
                    result=analyze(channel,code,newrows,first,status,now,source,
                                   args.min_long_uploads,args.min_long_views)
                    evals.append(result)
                log.append({"pais_busca":code,"channel_id":cid,
                            "canal":channel["snippet"].get("title",""),
                            "pais_declarado":declared,
                            "pais_diferente_do_busca":"SIM" if declared and declared!=code else "NAO",
                            "estado":status,"nota":first})
            except QuotaStop as exc:
                print("Limite local da API: "+str(exc),file=sys.stderr)
                stop=True
                break
            except RuntimeError as exc:
                log.append({"pais_busca":code,"channel_id":cid,
                            "canal":channel["snippet"].get("title",""),
                            "pais_declarado":declared,
                            "pais_diferente_do_busca":"SIM" if declared and declared!=code else "NAO",
                            "estado":"ERRO_API","nota":str(exc)[:300]})
                if "quotaExceeded" in str(exc) or "dailyLimitExceeded" in str(exc):
                    stop=True
                    break
    write_csv(out/"canais_elegiveis_analisados.csv",evals,CHANNEL_COLUMNS)
    write_csv(out/"videos_detalhados.csv",video_rows,VIDEO_COLUMNS)
    uncertain=[{"video_id":r["video_id"],"tipo_confirmado":manual.get(r["video_id"], ""),
                "canal":r["canal"],"duracao_seg":r["duracao_seg"],
                "views":r["views"],"url":r["link_video"],
                "instrucao":"Preencha SHORT ou LONG apos conferir o video no YouTube"}
               for r in video_rows if r["duracao_seg"] != "" and int(r["duracao_seg"]) <= 180]
    write_csv(out/"revisao_short_manual.csv",uncertain,
              ["video_id","tipo_confirmado","canal","duracao_seg","views","url","instrucao"])
    write_csv(out/"auditoria_candidatos.csv",log,["pais_busca","channel_id","canal","pais_declarado","pais_diferente_do_busca","estado","nota"])
    selected=[]; summary=[]
    for code in codes:
        group=[row for row in evals if row["codigo_pais"]==code and row["qualificado"]=="SIM"]
        group.sort(key=lambda row:(row["score_longform"],row["mediana_views_long"],row["views_long_total"]),reverse=True)
        # Ordenacao por desempenho, nao por pais declarado. O pais do canal e apenas metadado.
        for rank,row in enumerate(group[:args.target],1):
            selected.append({"ranking":rank,"posicoes_alvo":args.target,**row})
        summary.append({"pais":COUNTRIES[code],"codigo":code,
                        "candidatos_descobertos":len(found[code]),
                        "canais_elegiveis_verificados":sum(r["codigo_pais"]==code for r in evals),
                        "qualificados_longform":len(group),"posicoes_preenchidas":min(args.target,len(group)),
                        "posicoes_pendentes":max(0,args.target-len(group)),
                        "views_long_somadas_amostra":sum(num(r["views_long_total"]) for r in group),
                        "nota":"Rankeamento apenas dentro da amostra; nao e ranking mundial"})
    write_csv(out/"top50_longform_por_pais.csv",selected,["ranking","posicoes_alvo"]+CHANNEL_COLUMNS)
    write_csv(out/"resumo_paises.csv",summary,["pais","codigo","candidatos_descobertos",
                    "canais_elegiveis_verificados","qualificados_longform","posicoes_preenchidas",
                    "posicoes_pendentes","views_long_somadas_amostra","nota"])
    # Nenhum tema foi filtrado. A frequencia das categorias emerge APOS medir os videos longos.
    topic_rows=[]
    cat_counts=defaultdict(lambda:[0,0,set()])
    for v in video_rows:
        if v["faixa_duracao"].startswith("LONG_"):
            key=(v["pais_busca"],v.get("categoria_youtube_id", ""),v.get("categoria_youtube_nome", ""))
            cat_counts[key][0]+=1
            cat_counts[key][1]+=num(v["views"])
            cat_counts[key][2].add(v["channel_id"])
    for (code,cid,name),(total,views,chans) in sorted(cat_counts.items(),key=lambda x:(x[0][0],-x[1][1])):
        topic_rows.append({"codigo_pais":code,"pais_busca":COUNTRIES[code],
            "categoria_youtube_id":cid,"categoria_youtube_nome":name,
            "videos_long":total,"canais_distintos":len(chans),"views_long_somadas":views,
            "nota":"CATEGORIA DESCRITIVA POS-COLETA; NAO E FILTRO DE DESCOBERTA"})
    write_csv(out/"categorias_emergentes.csv",topic_rows,["codigo_pais","pais_busca",
        "categoria_youtube_id","categoria_youtube_nome","videos_long","canais_distintos",
        "views_long_somadas","nota"])
    # Indices complementares: top por mediana, views acumuladas e velocidade (por pais)
    secondary=[]
    for code in codes:
        group=[r for r in evals if r["codigo_pais"]==code and r["qualificado"]=="SIM"]
        for rank_name,col in (("views_long_total","views_long_total"),
                              ("mediana_views_long","mediana_views_long"),
                              ("mediana_views_dia_long","mediana_views_dia_long")):
            sorted_rows=sorted(group,key=lambda r:float(r[col] or 0),reverse=True)
            for rank,r in enumerate(sorted_rows[:args.target],1):
                secondary.append({"codigo_pais":code,"criterio":rank_name,"ranking":rank,
                                  "canal":r["canal"],"channel_id":r["channel_id"],"url":r["url"],
                                  "valor_metrica":r[col],"views_long_total":r["views_long_total"],
                                  "mediana_views_long":r["mediana_views_long"],
                                  "pct_views_top1_long":r["pct_views_top1_long"],
                                  "pais_declarado":r["pais_declarado"]})
    write_csv(out/"rankings_independentes.csv",secondary,["codigo_pais","criterio","ranking",
              "canal","channel_id","url","valor_metrica","views_long_total",
              "mediana_views_long","pct_views_top1_long","pais_declarado"])

    history_path=out/"historico_snapshots.csv"
    history=old_history
    # Importa o primeiro snapshot anterior, se ele existir no arquivo de entrada.
    known={(h.get("channel_id"),h.get("coleta_utc")) for h in history}
    for old in seed:
        stamp,cid=old.get("coleta_utc", ""),old.get("id", "")
        if not cid or not stamp or (cid,stamp) in known:
            continue
        if old.get("estado_primeiro_video") != "elegivel_primeiro_publico":
            continue
        history.append({"coleta_utc":stamp,"channel_id":cid,
                        "pais_busca":old.get("codigo",""),"canal":old.get("canal",""),
                        "inscritos":old.get("inscritos_atual",""),
                        "views_canal":old.get("views_canal_acumuladas",""),
                        "videos_canal":old.get("videos_publicos",""),
                        "videos_long_na_janela":"", "views_long_na_janela":""})
        known.add((cid,stamp))
    seen={(row["channel_id"],row["coleta_utc"][:10]) for row in history}
    # Canais no historico continuam monitorados quando deixam a janela movel.
    latest_by_id={row["channel_id"]:row for row in evals}
    tracked_ids=watch_ids | set(latest_by_id) | {s["channel_id"] for s in history}
    for cid in tracked_ids:
        item=metadata.get(cid)
        if not item:
            continue
        row=latest_by_id.get(cid, {})
        st=item.get("statistics", {})
        record={"coleta_utc":now.isoformat(), "channel_id":cid,
                "pais_busca":row.get("codigo_pais",item.get("snippet",{}).get("country","")),
                "canal":item.get("snippet",{}).get("title", ""),
                "inscritos":"" if st.get("hiddenSubscriberCount") else st.get("subscriberCount", ""),
                "views_canal":st.get("viewCount", ""), "videos_canal":st.get("videoCount", ""),
                "videos_long_na_janela":row.get("videos_long_total", ""),
                "views_long_na_janela":row.get("views_long_total", "")}
        key=(cid,record["coleta_utc"][:10])
        if key in seen:
            continue
        history.append(record)
        seen.add(key)
    write_csv(history_path,history,SNAPSHOT_COLUMNS)
    growth=derive_growth(history)
    write_csv(out/"crescimento_monitorado.csv",growth,["channel_id","pais_busca","canal",
                    "primeira_coleta","ultima_coleta","dias_monitorados","delta_inscritos",
                    "delta_views_canal","nota"])
    with (out/"metodologia.json").open("w",encoding="utf-8") as f:
        json.dump({"janela_inicio_utc":start,"janela_fim_exclusivo_utc":end,"paises":codes,
            "versao":"3.0 SEM TEMA","descoberta":"search.list SEM q, videoCategoryId ou topicId; amostragem temporal regional",
            "janelas_temporais":args.shards,"paginas_por_consulta":args.pages_per_search,
            "alvo_por_pais":args.target,"min_long_uploads":args.min_long_uploads,
            "min_long_views":args.min_long_views,"pesquisa_parcial_quota":bool(quota_errors),"chamadas_search":client.search_calls,
            "chamadas_outras":client.other_calls,
            "limitacoes":["Busca nao exaustiva; indice de busca parcial e regional", "Nenhum nicho ou categoria restringe descoberta",
             "Categorias sao associadas somente apos coleta", "Pais declarado nao identifica espectadores",
             "<=3min nao confirma Short; use revisao_short_manual.csv e --manual-csv",
             "Views de videos atuais nao sao crescimento retroativo", "Snapshot nao recupera historico passado",
             "Primeiro upload significa primeiro video publico atualmente disponivel",
             "Video de 4 a 20 minutos ou >20 minutos na descoberta; videos 3-4min apenas por sementes/recuperacao",
             "Para qualificar por mercado high RPM precisa de audiencia real (nao publica)"]},f,ensure_ascii=False,indent=2)
    print("\nRESULTADO: " + str(out.resolve()))
    for row in summary:
        print(f"  {row['codigo']}: {row['posicoes_preenchidas']}/{args.target} canais qualificados; "
              f"{row['posicoes_pendentes']} pendentes")
    (out/"status_coleta.json").write_text(json.dumps({
        "status":"COMPLETA",
        "chamadas_search":client.search_calls,
        "chamadas_outras":client.other_calls,
        "consultas_bem_sucedidas":sum(not r.get("erro") for r in searches),
        "avisos":"Amostra nao exaustiva; sem restricoes de tema",
    },ensure_ascii=False,indent=2),encoding="utf-8")
    print(f"Search: {client.search_calls} chamadas | outras: {client.other_calls} chamadas")
    return out


if __name__ == "__main__":
    main()
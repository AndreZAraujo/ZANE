#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Radar YouTube Long-form v2: canais cujo primeiro upload PUBLICO CONHECIDO e recente.

Usa APENAS a YouTube Data API v3 e a biblioteca padrao do Python (3.10+).
Descoberta amostral, sem vidIQ. Canais mistos nao sao descartados: analisa
videos >3min independentemente das visualizacoes em possiveis Shorts <=3min.

Exemplo Windows PowerShell:
  $env:YOUTUBE_API_KEY = 'SUA_CHAVE'
  python radar_longform_v2.py --start 2026-10-27 --end 2026-11-17 \
      --seed-csv resultado_youtube_sem_vidiq/todos_candidatos.csv

Por padrao a janela sao os ultimos 21 dias corridos (inclusive), em UTC.
AVISOS: a API publica nao informa diretamente se um video e Short, nem a
localizacao dos espectadores, nem historico retroativo de inscritos ou RPM.
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
# Cobertura propositalmente variada; perguntas de negocio, educacao, tecnologia,
# historia, ciencia e assuntos culturais. Edite este dicionario para experimentar.
TERMS_EN = [
    "business documentary", "economic history", "forgotten companies",
    "technology explained", "science documentary", "history documentary",
    "real estate explained", "money explained",
]
TERMS_DE = [
    "Wirtschaft Dokumentation", "Geschichte Dokumentation", "Firmen Geschichte",
    "Technik erklärt", "Wissenschaft Doku", "Finanzen erklärt",
    "Immobilien Deutschland", "vergessene Unternehmen",
]
# Separacao confiavel por duracao: um Short tem no maximo 180 segundos.
# Ate 180s pode ser Short OU video horizontal tradicional: portanto 'INDEFINIDO'.
SHORT_POSSIBLE_MAX_S = 180
MIDROLL_MIN_S = 480
VIDEO_COLUMNS = [
    "coleta_utc", "pais_busca", "pais_declarado", "confianca_pais", "canal", "channel_id",
    "video_id", "link_video", "titulo", "publicado_utc", "duracao_seg", "faixa_duracao",
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
    "origem_descoberta", "consulta_regiao_nao_prova_audiencia",
]
SNAPSHOT_COLUMNS = ["coleta_utc", "channel_id", "pais_busca", "canal", "inscritos",
                    "views_canal", "videos_canal", "videos_long_na_janela", "views_long_na_janela"]


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
    pass


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
                body = exc.read().decode("utf-8", "replace")[:500]
                if exc.code in (429, 500, 502, 503) and retry < 3:
                    time.sleep(2 ** retry)
                    continue
                raise RuntimeError(f"API {endpoint}: HTTP {exc.code}: {body}") from exc
        raise RuntimeError("Nao foi possivel consultar a API")


def discover(api: YouTube, codes: list[str], start: str, end_exclusive: str,
             max_per_country: int, seed_rows: list[dict], terms_per_country: int,
             custom_terms: dict | None = None):
    found = defaultdict(lambda: defaultdict(set))
    discovery_report = []
    custom_terms = custom_terms or {}
    for row in seed_rows:
        code = row.get("codigo") or row.get("codigo_pais") or row.get("pais_busca")
        cid = row.get("id") or row.get("channel_id")
        if code in codes and cid and re.fullmatch(r"UC[A-Za-z0-9_-]{22}", cid):
            found[code][cid].add("csv_anterior")
    # Distribuir consultas equitativamente entre os paises. Assim, ao atingir
    # o limite diario, nenhum pais perde todas as consultas.
    terms = {c:list(custom_terms.get(c) or (TERMS_DE if c == "DE" else TERMS_EN))
             for c in codes}
    quota_failure = False
    for index in range(terms_per_country):
        for code in codes:
            if index >= len(terms[code]):
                continue
            term = terms[code][index]
            for duration in ("medium", "long"):
                if api.search_calls >= api.limit_search:
                    break
                try:
                    rsp = api.get(
                        "search", part="snippet", type="video", q=term,
                        videoDuration=duration,
                        order="date" if index % 2 == 0 else "viewCount",
                        regionCode=code, maxResults=50,
                        publishedAfter=start, publishedBefore=end_exclusive)
                    items = rsp.get("items", [])
                    for item in items:
                        cid = item.get("snippet", {}).get("channelId")
                        if cid:
                            found[code][cid].add(f"{term} [{duration}]")
                    discovery_report.append({"pais_busca":code,"termo":term,
                        "duracao_filtro":duration,"videos_retornados":len(items),
                        "canais_unicos_acumulados":len(found[code]),"erro":""})
                except RuntimeError as exc:
                    discovery_report.append({"pais_busca":code,"termo":term,
                        "duracao_filtro":duration,"videos_retornados":0,
                        "canais_unicos_acumulados":len(found[code]),"erro":str(exc)})
                    if "quotaExceeded" in str(exc) or "dailyLimitExceeded" in str(exc):
                        quota_failure = True
                        break
            if quota_failure:
                break
        if quota_failure or api.search_calls >= api.limit_search:
            break
    if max_per_country:
        for code in codes:
            if len(found[code]) > max_per_country:
                ordered = sorted(found[code], key=lambda x:(-len(found[code][x]),x))
                found[code] = defaultdict(set,{cid:found[code][cid] for cid in ordered[:max_per_country]})
    for code in codes:
        print(f"Busca {code}: {len(found[code])} canais candidatos unicos")
    return found, discovery_report


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


def classify_video(video: dict, channel: dict, market: str, checked_at: datetime, manual: dict | None = None):
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
        "confianca_pais":"DECLARADO" if channel.get("snippet", {}).get("country") == market else "BUSCA_REGIONAL",
        "canal":channel.get("snippet", {}).get("title", ""), "channel_id":cid,
        "video_id":video["id"], "link_video":"https://www.youtube.com/watch?v=" + video["id"],
        "titulo":snippet.get("title", ""), "publicado_utc":video_at,
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
    p=argparse.ArgumentParser(description="Radar de canais YouTube com foco em videos longos")
    p.add_argument("--countries",default="US,CA,GB,AU,DE",help="Codigos separados por virgulas")
    p.add_argument("--target",type=int,default=50,help="Canais de long-form por pais (default 50)")
    p.add_argument("--days",type=int,default=21,help="Dias corridos inclusivos no radar")
    p.add_argument("--start",default=None,help="Data inicial UTC YYYY-MM-DD (opcional)")
    p.add_argument("--end",default=None,help="Data final UTC YYYY-MM-DD inclusiva (opcional)")
    p.add_argument("--seed-csv",default=None,help="CSV historico de candidatos; inclui canais ja encontrados")
    p.add_argument("--manual-csv",default=None,help="CSV opcional com video_id,tipo_confirmado (SHORT|LONG|LIVE)")
    p.add_argument("--output-dir",default="resultado_longform_v2")
    p.add_argument("--terms-per-country",type=int,default=8)
    p.add_argument("--queries-file",default=None,help="JSON opcional com lista de termos por pais")
    p.add_argument("--max-search-requests",type=int,default=80)
    p.add_argument("--max-other-requests",type=int,default=6000)
    p.add_argument("--candidate-limit-per-country",type=int,default=600)
    p.add_argument("--max-upload-pages",type=int,default=30)
    p.add_argument("--min-long-uploads",type=int,default=1,
                   help="Canais com >= este numero de videos >3min (default 1)")
    p.add_argument("--min-long-views",type=int,default=1000,
                   help="Views acumuladas em long-forms da janela (default 1000)")
    return p.parse_args(argv)


def main(argv=None, api=None):
    args=parse_args(argv)
    if args.target<=0 or args.days<=0 or args.max_upload_pages<=0 or args.terms_per_country<=0:
        raise SystemExit("target, days, max-upload-pages, terms-per-country devem ser positivos")
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
    client=api or YouTube(os.getenv("YOUTUBE_API_KEY", ""), args.max_search_requests, args.max_other_requests)
    if not getattr(client, "key", None):
        raise SystemExit("Configure YOUTUBE_API_KEY no ambiente; nunca publique a chave")
    out=Path(args.output_dir);out.mkdir(parents=True,exist_ok=True)
    seed=read_csv(Path(args.seed_csv)) if args.seed_csv else []
    manual_rows=read_csv(Path(args.manual_csv)) if args.manual_csv else []
    manual={row.get("video_id", ""): row.get("tipo_confirmado", "").strip().upper()
            for row in manual_rows if row.get("tipo_confirmado", "").strip().upper() in ("SHORT", "LONG", "LIVE")}
    hist_path=out/"historico_snapshots.csv"
    old_history=read_csv(hist_path)
    watch_ids={r.get("channel_id") for r in old_history if r.get("channel_id")}
    custom_terms={}
    if args.queries_file:
        with open(args.queries_file,encoding="utf-8") as f:
            custom_terms=json.load(f)
    found, searches=discover(client,codes,start,end,args.candidate_limit_per_country,seed,
                             args.terms_per_country,custom_terms)
    write_csv(out/"auditoria_busca.csv",searches,
              ["pais_busca","termo","duracao_filtro","videos_retornados","canais_unicos_acumulados","erro"])
    # Buscar metadados uma unica vez por ID; canal pode ser visto em varias regioes.
    ids={cid for code in codes for cid in found[code]} | watch_ids
    metadata=get_channel_metadata(client,ids)
    evals=[]; video_rows=[]; log=[]
    done=set()
    for code in codes:
        print(f"Validando candidatos em {COUNTRIES[code]}: {len(found[code])}")
        for cid,terms in found[code].items():
            if cid in done:  # Pais declarado tem prioridade no bloco correspondente
                continue
            channel=metadata.get(cid)
            if not channel:
                log.append({"pais_busca":code,"channel_id":cid,"canal":"",
                            "estado":"SEM_METADADOS","nota":"Canal indisponivel"})
                continue
            declared=channel.get("snippet",{}).get("country","")
            if declared and declared!=code:
                log.append({"pais_busca":code,"channel_id":cid,"canal":channel["snippet"].get("title",""),
                            "estado":"PAIS_DECLARADO_DIFERENTE","nota":declared})
                continue
            # Sem pais declarado: permite participar como candidato de busca regional,
            # sem fingir que a residencia ou audiencia do canal foi verificada.
            try:
                status,first,uploads=scan_public_uploads(client,channel,start,end,args.max_upload_pages)
                if status == "ELEGIVEL":
                    videos=get_video_details(client,uploads)
                    newrows=[classify_video(v,channel,code,now,manual) for v in videos]
                    video_rows.extend(newrows)
                    result=analyze(channel,code,newrows,first,status,now,terms,
                                   args.min_long_uploads,args.min_long_views)
                    evals.append(result)
                    done.add(cid)
                log.append({"pais_busca":code,"channel_id":cid,
                            "canal":channel["snippet"].get("title",""),
                            "estado":status,"nota":first})
            except QuotaStop as exc:
                print("Limite local da API: "+str(exc),file=sys.stderr)
                break
            except RuntimeError as exc:
                log.append({"pais_busca":code,"channel_id":cid,
                            "canal":channel["snippet"].get("title",""),
                            "estado":"ERRO_API","nota":str(exc)[:300]})
                if "quotaExceeded" in str(exc) or "dailyLimitExceeded" in str(exc):
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
    write_csv(out/"auditoria_candidatos.csv",log,["pais_busca","channel_id","canal","estado","nota"])
    selected=[]; summary=[]
    for code in codes:
        group=[row for row in evals if row["codigo_pais"]==code and row["qualificado"]=="SIM"]
        group.sort(key=lambda row:(row["score_longform"],row["mediana_views_long"],row["views_long_total"]),reverse=True)
        # Transparencia: pais declarado verificado primeiro; sem pais declarado fica visivel.
        group.sort(key=lambda row:row["confianca_pais"] != "DECLARADO")
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
            "alvo_por_pais":args.target,"min_long_uploads":args.min_long_uploads,
            "min_long_views":args.min_long_views,"chamadas_search":client.search_calls,
            "chamadas_outras":client.other_calls,
            "limitacoes":["Busca nao exaustiva", "País declarado nao identifica espectadores",
             "<=3min nao confirma Short; use revisao_short_manual.csv e --manual-csv",
             "Views de videos atuais nao sao crescimento retroativo", "Snapshot nao recupera historico passado",
             "Primeiro upload significa primeiro video publico atualmente disponivel"]},f,ensure_ascii=False,indent=2)
    print("\nRESULTADO: " + str(out.resolve()))
    for row in summary:
        print(f"  {row['codigo']}: {row['posicoes_preenchidas']}/{args.target} canais qualificados; "
              f"{row['posicoes_pendentes']} pendentes")
    print(f"Search: {client.search_calls} chamadas | outras: {client.other_calls} chamadas")
    return out


if __name__ == "__main__":
    main()
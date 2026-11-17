#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pesquisa canais iniciados por sua PRIMEIRA PUBLICACAO PUBLICA, sem vidIQ.

Uso:
  export YOUTUBE_API_KEY='SUA_CHAVE'   # Windows PowerShell: $env:YOUTUBE_API_KEY='...'
  python coletor_youtube_primeira_publicacao.py

Requer somente Python 3.10+ e biblioteca padrao. Consulta a API oficial YouTube
Data v3; descoberta amostral (nao exaustiva), respeitando quota do projeto.
"""

import csv
import json
import os
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

API = "https://www.googleapis.com/youtube/v3"
KEY = os.getenv("YOUTUBE_API_KEY")
WINDOW_START = "2026-10-27T00:00:00Z"
WINDOW_END_EXCLUSIVE = "2026-11-18T00:00:00Z"
OUT = Path("resultado_youtube_sem_vidiq")
COUNTRIES = {
    "US": ("Estados Unidos", ["business documentaries", "forgotten brands", "money explained"]),
    "AU": ("Austrália", ["australian business", "history documentary", "money explained"]),
    "NO": ("Noruega", ["norsk historie", "økonomi", "documentary"]),
    "CH": ("Suíça", ["Schweiz Wirtschaft", "Swiss business", "histoire suisse"]),
    "CA": ("Canadá", ["canadian history", "business documentary", "finance explained"]),
    "GB": ("Reino Unido", ["british brands", "UK business documentary", "money explained"]),
    "DK": ("Dinamarca", ["dansk historie", "økonomi Danmark", "business documentary"]),
    "DE": ("Alemanha", ["deutsche Geschichte", "Wirtschaft Doku", "Finanzen erklärt"]),
    "NL": ("Países Baixos", ["Nederland geschiedenis", "economie Nederland", "business documentary"]),
}


def request(endpoint, **params):
    params["key"] = KEY
    url = API + "/" + endpoint + "?" + urllib.parse.urlencode(params)
    for attempt in range(4):
        try:
            with urllib.request.urlopen(url, timeout=30) as handle:
                return json.load(handle)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")[:700]
            if exc.code in (429, 500, 503) and attempt < 3:
                time.sleep(2 ** attempt)
                continue
            raise RuntimeError(f"API {endpoint}: HTTP {exc.code}: {body}") from exc
    raise RuntimeError("Erro temporario de rede")


def batches(xs, n=50):
    for i in range(0, len(xs), n):
        yield xs[i:i + n]


def video_ids_from_search(code, searches):
    results = set()
    for keyword in searches:
        resp = request("search", part="snippet", type="video", q=keyword,
                       order="viewCount", regionCode=code, maxResults=50,
                       publishedAfter=WINDOW_START,
                       publishedBefore=WINDOW_END_EXCLUSIVE)
        for item in resp.get("items", []):
            cid = item.get("snippet", {}).get("channelId")
            if cid:
                results.add(cid)
    return results


def channels_detail(ids):
    found = {}
    for chunk in batches(sorted(ids)):
        resp = request("channels", part="snippet,statistics,contentDetails",
                       id=",".join(chunk), maxResults=50)
        for item in resp.get("items", []):
            found[item["id"]] = item
    return found


def public_uploads(channel):
    playlist = channel.get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads")
    if not playlist:
        return None, "playlist_nao_disponivel", []
    rows, token = [], None
    while True:
        params = {"part": "contentDetails,snippet", "playlistId": playlist, "maxResults": 50}
        if token:
            params["pageToken"] = token
        resp = request("playlistItems", **params)
        items = resp.get("items", [])
        for it in items:
            detail = it.get("contentDetails", {})
            published = detail.get("videoPublishedAt") or it.get("snippet", {}).get("publishedAt")
            video_id = detail.get("videoId")
            if published and video_id:
                rows.append((published, video_id))
        token = resp.get("nextPageToken")
        if not token:
            break
        # A lista de uploads do YouTube normalmente e da mais recente para a mais antiga.
        # Quando achamos um video anterior ao periodo, nenhum upload ainda mais antigo
        # vai tornar a conta elegivel.
        if rows and min(x[0] for x in rows) < WINDOW_START:
            return min(x[0] for x in rows), "anterior_ao_periodo", []
    if not rows:
        return None, "sem_upload_publico", []
    first = min(x[0] for x in rows)
    status = "elegivel_primeiro_publico" if WINDOW_START <= first < WINDOW_END_EXCLUSIVE else "fora_da_janela"
    return first, status, [video_id for _, video_id in rows if WINDOW_START <= _ < WINDOW_END_EXCLUSIVE]


def views_for_videos(ids):
    total = 0
    long_count = shorts_or_short_count = 0
    for chunk in batches(list(dict.fromkeys(ids))):
        resp = request("videos", part="statistics,contentDetails,snippet", id=",".join(chunk))
        for item in resp.get("items", []):
            total += int(item.get("statistics", {}).get("viewCount", 0))
            duration = item.get("contentDetails", {}).get("duration", "")
            # Rotulo simplificado; Shorts depende de formato e classificacao do YouTube.
            if "H" in duration or "M" in duration:
                long_count += 1
            else:
                shorts_or_short_count += 1
    return total, long_count, shorts_or_short_count


def save_csv(path, rows, keys):
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main():
    if not KEY:
        raise SystemExit("Configure YOUTUBE_API_KEY no seu ambiente; nao grave a chave no arquivo.")
    OUT.mkdir(exist_ok=True)
    candidates = []
    all_channels = {}
    for code, (label, searches) in COUNTRIES.items():
        print(f"Buscando canais: {label}")
        ids = video_ids_from_search(code, searches)
        details = channels_detail(ids)
        for cid, item in details.items():
            # regionCode controla a busca, nao a residencia do criador.
            declared_country = item.get("snippet", {}).get("country")
            if declared_country != code:
                continue
            all_channels[cid] = (code, label, item)
    print(f"{len(all_channels)} canais com pais declarado compativel. Verificando primeiro upload publico...")
    checked_at = datetime.now(timezone.utc).isoformat()
    for j, (cid, (code, label, item)) in enumerate(all_channels.items(), 1):
        first, status, ids = public_uploads(item)
        stats = item.get("statistics", {})
        entry = {
            "pais": label,
            "codigo": code,
            "canal": item.get("snippet", {}).get("title", ""),
            "id": cid,
            "link": "https://www.youtube.com/channel/" + cid,
            "criacao_conta": item.get("snippet", {}).get("publishedAt", ""),
            "primeiro_video_publico_conhecido": first or "",
            "estado_primeiro_video": status,
            "inscritos_atual": int(stats.get("subscriberCount", 0)),
            "views_canal_acumuladas": int(stats.get("viewCount", 0)),
            "videos_publicos": int(stats.get("videoCount", 0)),
            "views_videos_publicados_janela": 0,
            "amostragem": "Buscas tematicas; nao e cobertura exaustiva",
            "coleta_utc": checked_at,
        }
        if status == "elegivel_primeiro_publico":
            views, _, _ = views_for_videos(ids)
            entry["views_videos_publicados_janela"] = views
        candidates.append(entry)
        if j % 50 == 0:
            print(f"  {j}/{len(all_channels)} verificados")

    cols = ["pais", "codigo", "canal", "id", "link", "criacao_conta",
            "primeiro_video_publico_conhecido", "estado_primeiro_video", "inscritos_atual",
            "views_canal_acumuladas", "videos_publicos", "views_videos_publicados_janela",
            "amostragem", "coleta_utc"]
    save_csv(OUT / "todos_candidatos.csv", candidates, cols)
    valid = [r for r in candidates if r["estado_primeiro_video"] == "elegivel_primeiro_publico"]
    rank_rows = []
    for code, (label, _) in COUNTRIES.items():
        group = [r for r in valid if r["codigo"] == code]
        for metric, order_key in [
            ("INSCRITOS_ATUAIS_PROXY", "inscritos_atual"),
            ("VIEWS_VIDEOS_NA_JANELA", "views_videos_publicados_janela")]:
            ordered = sorted(group, key=lambda r: r[order_key], reverse=True)
            for rank, row in enumerate(ordered[:10], 1):
                rank_rows.append({"pais":label, "ranking":metric, "posicao":rank, **row})
    save_csv(OUT / "rankings_9_paises.csv", rank_rows, ["pais", "ranking", "posicao"]+cols[1:])
    print(f"Canais elegiveis na AMOSTRA: {len(valid)}. Arquivos CSV em {OUT.resolve()}")
    print("ATENCAO: inscritos atuais nao significam inscritos GANHOS na janela.")
    print("Para crescimento real, salve e compare snapshots em dias subsequentes.")


if __name__ == "__main__":
    main()

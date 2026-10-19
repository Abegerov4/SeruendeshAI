"""HTTP helpers for the data pipeline: honest User-Agent, retries with backoff, disk cache."""
from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any

import requests

from ayat_backend.app.paths import RAW_DIR

log = logging.getLogger("pipeline")

USER_AGENT = "SeruendeshAI/0.1 (hackathon walking assistant for Astana; https://github.com/Abegerov4/SeruendeshAI)"
OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]
ASTANA_AREA_ID = 3603087155  # OSM relation 3087155 (Astana, admin_level=4) + 3_600_000_000
ASTANA_RELATION = 3087155
ASTANA_BBOX = (50.857, 71.217, 51.352, 71.786)  # S, W, N, E (from the admin boundary)

session = requests.Session()
session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "ru,en;q=0.8"})


def cache_path(kind: str, key: str, ext: str = "json") -> Path:
    h = hashlib.sha1(key.encode()).hexdigest()[:16]
    p = RAW_DIR / kind / f"{h}.{ext}"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def get_json(url: str, *, params: dict | None = None, kind: str = "http", max_age_h: float | None = None,
             retries: int = 4, timeout: int = 60, delay: float = 0.0) -> Any:
    """GET with a disk cache under data/raw/<kind>/ and exponential backoff on 429/5xx."""
    key = url + "?" + json.dumps(params or {}, sort_keys=True)
    p = cache_path(kind, key)
    if p.exists() and (max_age_h is None or (time.time() - p.stat().st_mtime) < max_age_h * 3600):
        return json.loads(p.read_text())
    last: Exception | None = None
    for attempt in range(retries):
        if delay:
            time.sleep(delay)
        try:
            r = session.get(url, params=params, timeout=timeout)
            if r.status_code in (429, 500, 502, 503, 504):
                wait = float(r.headers.get("Retry-After", 0) or 0) or 2 ** (attempt + 1)
                log.warning("%s -> %s, retry in %.0fs", url, r.status_code, wait)
                time.sleep(min(wait, 90))
                continue
            r.raise_for_status()
            data = r.json()
            p.write_text(json.dumps(data, ensure_ascii=False))
            return data
        except (requests.RequestException, ValueError) as e:  # ValueError: bad JSON
            last = e
            time.sleep(2 ** (attempt + 1))
    raise RuntimeError(f"GET failed after {retries} attempts: {url}: {last}")


def overpass(query: str, *, kind: str = "overpass", max_age_h: float | None = 24, timeout: int = 330,
             cycles: int = 2) -> dict:
    """Run an Overpass QL query, trying mirrors in order; cached on disk."""
    p = cache_path(kind, query)
    if p.exists() and (max_age_h is None or (time.time() - p.stat().st_mtime) < max_age_h * 3600):
        return json.loads(p.read_text())
    errors = []
    for attempt in range(cycles):
        for url in OVERPASS_ENDPOINTS:
            try:
                log.info("overpass %s (attempt %d)", url, attempt + 1)
                r = session.post(url, data={"data": query}, timeout=timeout)
                if r.status_code != 200:
                    errors.append(f"{url}: HTTP {r.status_code}")
                    continue
                data = r.json()
                if data.get("remark") and not data.get("elements"):
                    errors.append(f"{url}: {data['remark'][:120]}")
                    continue
                p.write_text(json.dumps(data, ensure_ascii=False))
                return data
            except (requests.RequestException, ValueError) as e:
                errors.append(f"{url}: {type(e).__name__}")
        if attempt + 1 < cycles:
            time.sleep(20)
    raise RuntimeError("All Overpass endpoints failed: " + "; ".join(errors))


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n")


def read_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]

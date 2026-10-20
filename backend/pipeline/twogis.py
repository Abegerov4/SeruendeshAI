"""The team's 2GIS snapshot as a layer over our places (`python -m pipeline.twogis [path | git:<ref>:<path>]`).

Aslan's export (branch data/astana-2gis-*) holds what the public 2GIS site shows for ~7.9k places in Astana:
opening hours, rating and review count, phones, Wi-Fi, average check and photo links. Each record is matched to
one of our places (≤150 m and the same name, ignoring words like «кофейня»), and the facts become a layer the API
applies at load: hours with their 2GIS page as the source (researched official hours still win), the rating, a
photo when we have none (shown from the 2GIS CDN, credited «2ГИС»), a phone, a website and Wi-Fi.
Output: data/processed/twogis_layer.json {poi_id: {...}}.
"""
from __future__ import annotations

import gzip
import json
import logging
import math
import re
import subprocess
import sys

from rapidfuzz import fuzz

from app.hours import _parse
from app.paths import PROCESSED_DIR
from app.textnorm import fold

log = logging.getLogger("pipeline.twogis")
OUT_FILE = PROCESSED_DIR / "twogis_layer.json"
DEFAULT_SOURCE = "git:origin/data/astana-2gis-2026-10-20:places.json.gz"
DAYS = [("Mon", "Mo"), ("Tue", "Tu"), ("Wed", "We"), ("Thu", "Th"), ("Fri", "Fr"), ("Sat", "Sa"), ("Sun", "Su")]
# words that say what a place is, not which one: «Кофейня «София»» and «София, кофейня» are the same place
GENERIC = re.compile(r"\b(кофейня|кофехана|кафе|cafe|coffee|ресторан|мейрамхана|restaurant|бар|bar|паб|pub|пиццерия|"
                     r"столовая|асхана|кондитерская|пекарня|бургерная|суши|шашлычная|чайхана|караоке|кинотеатр|"
                     r"музей|галерея|парк|сквер|тц|трц|торговый центр|магазин|салон|клуб|club|центр)\b")


def load(source: str) -> list[dict]:
    if source.startswith("git:"):
        raw = subprocess.run(["git", "show", source[4:]], capture_output=True, check=True).stdout
    else:
        raw = open(source, "rb").read()
    return json.loads(gzip.decompress(raw))["records"]


def key(name: str) -> str:
    base = fold(name.split(",")[0])  # «TeaDrunk club, чайный клуб» -> «teadrunk club»
    return " ".join(GENERIC.sub(" ", re.sub(r"[«»\"'()]", " ", base)).split())


def hours(oh: dict | None) -> str | None:
    """2GIS {"Mon": {"working_hours": [{"from", "to"}]}} -> «Mo-Fr 09:00-18:00; Sa-Su 10:00-16:00» (days missing = closed)."""
    if not oh:
        return None
    per_day = []
    for long, short in DAYS:
        spans = [(w.get("from"), w.get("to")) for w in (oh.get(long) or {}).get("working_hours") or [] if w.get("from") and w.get("to")]
        if any(f == "00:00" and t in ("24:00", "00:00") for f, t in spans):
            spans = [("00:00", "24:00")]
        per_day.append((short, ",".join(f"{f}-{'24:00' if t == '00:00' else t}" for f, t in spans) or "off"))
    if all(v == "00:00-24:00" for _, v in per_day):
        return "24/7"
    groups: list[list] = []
    for short, v in per_day:
        if groups and groups[-1][2] == v:
            groups[-1][1] = short
        else:
            groups.append([short, short, v])
    text = "; ".join(f"{a}{'-' + b if b != a else ''} {v}" for a, b, v in groups if v != "off")
    return text if text and _parse(text) is not None else None


def photo(rec: dict) -> dict | None:
    for cand in rec.get("photo_candidates") or []:
        url = cand.get("url") or ""
        if url.startswith("https://") and ".photo.2gis.com/" in url:
            return {"url": url, "source": "2gis", "author": "2ГИС", "license": "2gis.kz", "page": rec.get("source_url")}
    return None


def match(pois: list[dict], recs: list[dict]) -> dict[str, dict]:
    """poi_id -> the 2GIS record of the same place (nearest among same-name candidates within 150 m)."""
    cell = lambda lat, lon: (round(lat * 200), round(lon * 125))  # ~550 × 550 m cells
    grid: dict[tuple, list] = {}
    for r in recs:
        if r.get("lat") is not None and r.get("lon") is not None and r.get("name"):
            grid.setdefault(cell(r["lat"], r["lon"]), []).append(r)
    out, taken = {}, set()
    for p in pois:
        if p.get("name_auto"):
            continue
        names = {key(n) for n in (p["name"], *(p.get("names") or {}).values()) if n}
        names.discard("")
        if not names:
            continue
        cy, cx = cell(p["lat"], p["lon"])
        best = None
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                for r in grid.get((cy + dy, cx + dx), []):
                    d = 6371000 * math.hypot(math.radians(r["lat"] - p["lat"]), math.radians(r["lon"] - p["lon"]) * math.cos(math.radians(p["lat"])))
                    if d > 150 or r["object_id"] in taken:
                        continue
                    k = key(r["name"])
                    score = max((fuzz.token_set_ratio(k, n) for n in names), default=0) if k else 0
                    if score >= 88 and (best is None or (score, -d) > (best[0], -best[1])):
                        best = (score, d, r)
        if best:
            out[p["id"]] = best[2]
            taken.add(best[2]["object_id"])
    return out


def layer(rec: dict) -> dict:
    out: dict = {"twogis_id": rec["object_id"], "url": rec.get("source_url"), "captured": (rec.get("source_captured_at") or "")[:10]}
    if h := hours(rec.get("opening_hours")):
        out["opening_hours"] = h
    rating = rec.get("rating_2gis") or rec.get("organization_rating_2gis")
    count = rec.get("rating_count_2gis") or rec.get("organization_rating_count_2gis")
    if isinstance(rating, (int, float)) and 1 <= rating <= 5:
        out["rating"] = round(float(rating), 1)
        if isinstance(count, int) and count > 0:
            out["rating_count"] = count
    if ph := photo(rec):
        out["photo"] = ph
    if rec.get("phones"):
        out["phone"] = rec["phones"][0]
    if rec.get("websites"):
        out["website"] = rec["websites"][0]
    if rec.get("free_wifi") is True:
        out["wifi"] = True
    if rec.get("average_check_text"):
        out["average_check"] = str(rec["average_check_text"])[:80]
    # facts the 2GIS card states (true only: «unknown» is not «no»)
    feats = {k: True for k, src in (("outdoor_seating", "terrace"), ("kids_area", "kids_area"), ("ramp", "ramp"),
                                    ("laptop_friendly", "laptop_allowed"), ("live_music", "live_music"), ("halal", "halal"))
             if rec.get(src) is True}
    if feats:
        out["features"] = feats
    if rec.get("cuisine_names"):
        out["cuisine"] = [str(c)[:40] for c in rec["cuisine_names"][:4]]
    return out


def main(source: str = DEFAULT_SOURCE) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    pois = [json.loads(line) for line in (PROCESSED_DIR / "pois.jsonl").open(encoding="utf-8") if line.strip()]
    recs = load(source)
    pairs = match(pois, recs)
    data = {pid: layer(r) for pid, r in pairs.items()}
    OUT_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=1))
    n = lambda k: sum(1 for v in data.values() if k in v)
    log.info("2GIS: %d records, %d of our places matched — hours %d, rating %d, photo %d, phone %d",
             len(recs), len(data), n("opening_hours"), n("rating"), n("photo"), n("phone"))


if __name__ == "__main__":
    main(*sys.argv[1:2])

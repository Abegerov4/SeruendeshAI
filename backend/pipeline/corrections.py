"""Reviewed corrections over the built catalogue (`python -m pipeline.corrections [2gis source]`).

Overture tags concert halls, palaces, music schools and even a museum as «music_venue», which the build mapped to
karaoke (fixed in pipeline.overture for the next build); betting shops sit in OSM as sports bars. This step
decides each case from the team's 2GIS export (the nearest record within 200 m with a similar name: its rubrics
say what the place is), else from the name, and writes data/processed/place_corrections.json
{poi_id: {"category": new, "reason": ...} | {"exclude": reason} | {"names": {...}, "reason": ...}}.
The API applies the file at load (app.store.apply_corrections); deleting it switches the corrections off.
"""
from __future__ import annotations

import json
import logging
import math
import re
import sys

from rapidfuzz import fuzz

from app.paths import POIS_FILE, PROCESSED_DIR
from app.textnorm import fold
from pipeline.twogis import DEFAULT_SOURCE, key, load

log = logging.getLogger("pipeline.corrections")
OUT_FILE = PROCESSED_DIR / "place_corrections.json"

KARAOKE = re.compile(r"караоке|karaok|\bktv\b|voice|голос", re.I)
MUSEUM = re.compile(r"музе|museum|мұражай|m[uý]ze", re.I)
SCHOOL = re.compile(r"школ|school|академ|academy|училищ|колледж|college|мектеп", re.I)
HALL = re.compile(r"зал\b|hall|сарай|palace|дворец|центр|center|centre|орталы|space|пространств|конгресс|congress|"
                  r"мероприят|event|медиа|media", re.I)
BAR = re.compile(r"\bбар\b|\bbar\b|\bpub\b|паб|lounge|лаунж", re.I)
RESTAURANT = re.compile(r"ресторан|restaurant|мейрамхана", re.I)
CAFE = re.compile(r"\bкафе\b|\bcafe\b", re.I)
BETTING = re.compile(r"\bБК\b|букмекер|betting|fonbet|фонбет|olimpbet|олимпбет|parimatch|париматч|1xbet|melbet|"
                     r"мелбет|tennisi|тенниси|casino|казино", re.I)
BETTING_SITE = re.compile(r"fairplay\.kz|fonbet|olimpbet|parimatch|1xbet|melbet|tennisi\.kz", re.I)  # a sports bar of a bookmaker
# 2GIS rubric -> our category, for places whose map category is in doubt
RUBRICS = [("Караоке", "karaoke"), ("Музеи", "museum"), ("Театры", "theatre"), ("Филармония", "theatre"),
           ("Концертные залы", "event_venue"), ("Аренда концертных площадок", "event_venue"),
           ("Конференц-залы", "event_venue"), ("Банкетные залы", "event_venue"), ("Ночные клубы", "nightclub"),
           ("Бары", "bar"), ("Рестораны", "restaurant"), ("Кафе", "cafe"), ("Кофейни", "cafe")]
# the same venue twice (an Overture copy under a transliterated name), and a borrowed Russian name
MANUAL = {
    "ov:f666893a-8296-4e": {"exclude": "duplicate of osm:n4894937300 (National Museum, transliterated Overture name)"},
    "ov:d8618d37-bebb-42": {"exclude": "duplicate of osm:n4894937300 (National Museum as «Historical Museum Astana», 194 m)"},
    "ov:dd3617a1-a856-43": {"exclude": "duplicate of osm:n4894937300 (National Museum under a Turkish name, 221 m)"},
    "ov:c5360c10-78b2-42": {"exclude": "duplicate of osm:n2474931663 (Arman cinema, Asia Park, same website, 60 m)"},
    # reviewed 2026-10-20: Overture copies of unique venues, two of them placed far from the real building
    "ov:af3d5a41-b852-49": {"exclude": "duplicate of osm:w240860325 (Hazrat Sultan Mosque, 150 m)"},
    "ov:e9514b43-d87e-49": {"exclude": "Hazrat Sultan Mosque placed 3.9 km from the real one (osm:w240860325)"},
    "ov:b1bbd733-b986-4e": {"exclude": "Astana Opera placed 1.2 km from the real building (osm:w917478479)"},
    "ov:7972273c-f99e-4c": {"exclude": "duplicate of osm:w240391776 (State Military History Museum, 221 m)"},
    "osm:w1239171353": {"exclude": "duplicate of osm:w240391776 (the same museum's building, 67 m; Wikidata and official hours stay)"},
    "ov:4526660e-f803-42": {"exclude": "duplicate of osm:n4902165007 (Cathedral of Our Lady of Perpetual Help)"},
    "ov:e91139d7-7cf8-40": {"exclude": "duplicate of osm:n4902165007 (Cathedral of Our Lady of Perpetual Help)"},
    "ov:ca75200e-4588-49": {"exclude": "duplicate of osm:n2635598135 (ТД «Сункар», 48 m)"},
    "osm:w242016673": {"exclude": "duplicate of osm:w256948787 (Central Market)"},
    "osm:w498977612": {"exclude": "duplicate of osm:w256948787 (Central Market)"},
    "ov:d67b3cc9-86a3-48": {"exclude": "duplicate of osm:w256948787 (Central Market)"},
    "osm:n5586173121": {"names": {"ru": "Kinopark 8 IMAX Сарыарка"},
                        "reason": "name:ru was the mall's name «Сарыарка»; the cinema is inside it"},
}


def _near(p: dict, records: list[dict]) -> dict | None:
    best, score = None, 0.0
    for r in records:
        d = math.hypot((r["lat"] - p["lat"]) * 111000, (r["lon"] - p["lon"]) * 69700)
        if d > 200:
            continue
        # pipeline.twogis.key: «Extaz, караоке-бар» -> «extaz» (the part before the comma, without generic words)
        s = max(fuzz.ratio(key(n), key(r["name"])) for n in [p["name"], *(p.get("names") or {}).values()] if n)
        if s >= 80 and s > score:
            best, score = r, s
    return best


def decide(p: dict, gis: dict | None) -> dict | None:
    name = " ".join([p["name"], *(p.get("names") or {}).values()])
    if BETTING.search(p["name"]) or (BETTING_SITE.search(p.get("website") or "") and p["category"] in ("bar", "nightclub")):
        return {"exclude": "betting shop / casino: not a place the assistant recommends"}
    if p["category"] != "karaoke" or KARAOKE.search(name):
        return None
    rubrics = (gis or {}).get("category_names") or []
    for rubric, cat in RUBRICS:
        if any(rubric.lower() in r.lower() for r in rubrics):
            return None if cat == "karaoke" else {"category": cat, "reason": f"2GIS rubric «{rubric}» ({gis['name']})"}
    if MUSEUM.search(name):
        return {"category": "museum", "reason": "museum by name (Overture music_venue)"}
    if SCHOOL.search(name):
        return {"exclude": "music school: not a place to visit (Overture music_venue)"}
    if HALL.search(name):
        return {"category": "event_venue", "reason": "concert hall / palace / event space by name (Overture music_venue)"}
    if RESTAURANT.search(name):
        return {"category": "restaurant", "reason": "restaurant by name (Overture music_venue)"}
    if CAFE.search(name):
        return {"category": "cafe", "reason": "café by name (Overture music_venue)"}
    if BAR.search(name):
        return {"category": "bar", "reason": "bar by name (Overture music_venue)"}
    return None  # no evidence either way: a live-music venue stays with the night places


def main(source: str = DEFAULT_SOURCE) -> dict:
    records = [r for r in load(source) if r.get("lat") and r.get("lon") and r.get("name")]
    pois = [json.loads(line) for line in POIS_FILE.open(encoding="utf-8") if line.strip()]
    out = dict(MANUAL)
    for p in pois:
        if p["id"] in out:
            continue
        doubtful = p["category"] == "karaoke" or BETTING.search(p["name"]) or BETTING_SITE.search(p.get("website") or "")
        if doubtful and (fix := decide(p, _near(p, records) if p["category"] == "karaoke" else None)):
            out[p["id"]] = {**fix, "name": p["name"], "was": p["category"]}
    OUT_FILE.write_text(json.dumps(out, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
    kinds = {k: sum(1 for v in out.values() if k in v) for k in ("category", "exclude", "names")}
    log.info("corrections: %d (%s) -> %s", len(out), kinds, OUT_FILE)
    return out


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s", datefmt="%H:%M:%S")
    main(*sys.argv[1:2])

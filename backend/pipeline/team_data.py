"""Layer from the team's big-data collection (branch `big-data`, Aslan, 2026-10-18).

That collection keeps 14k named Astana places with per-record provenance. Most of its leisure subset
duplicates our OSM + Overture records, so we take only what we lack:

* curated directory records (CityPass, mall maps) - checked opening hours and city experiences
  (excursions, river boats) that are not in OSM;
* origin anchors for the gazetteer - hotels, universities, hospitals, ministries, stations - so that
  "я в отеле Hilton" resolves to a point. Anchors are never recommended.

`extract` turns the branch export into the small committed file data/sources/team_bigdata.json;
`build` reads only that file.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from app.paths import DATA_DIR
from app.textnorm import fold

log = logging.getLogger("pipeline.team_data")

TEAM_FILE = DATA_DIR / "sources" / "team_bigdata.json"
PROVENANCE = {"branch": "big-data", "commit": "7a8d116", "author": "Aslan", "collected_at": "2026-10-18",
              "repo": "https://github.com/Abegerov4/SeruendeshAI/tree/big-data/data"}

DIRECTORY_SOURCES = {"citypass", "khanshatyr", "mega_silkway"}
DIRECTORY_CATEGORY = {"museum": "museum", "monument": "monument", "cafe": "cafe", "restaurant": "restaurant"}
# CityPass "attractions" are mostly experiences; map by name
EXPERIENCE = [(r"экскурси|автобус", "landmark"), (r"теплоход|водные прогулки", "active"), (r"колесо обозрения", "theme_park"),
              (r"океанариум", "zoo_aquarium"), (r"джунгли", "kids_indoor")]

OSM_ANCHOR = [("tourism", {"hotel", "hostel", "guest_house", "apartment"}, "hotel"),
              ("amenity", {"university", "college"}, "university"),
              ("amenity", {"hospital", "clinic"}, "hospital"),
              ("office", {"government"}, "government"),
              ("railway", {"station", "halt"}, "station")]
OV_ANCHOR = {"hotel": "hotel", "college_university": "university", "hospital": "hospital",
             "government_office": "government", "train_station": "station"}


def _anchor_kind(r: dict) -> str | None:
    t = r.get("raw_tags") or {}
    for key, values, kind in OSM_ANCHOR:
        if t.get(key) in values:
            return kind
    tax = r.get("raw_taxonomy") or {}
    return OV_ANCHOR.get(tax.get("basic_category") or "")


def extract(export_dir: str) -> dict:
    """Read <export_dir>/processed/pois.json from the big-data branch and write the compact layer."""
    rows = json.loads((Path(export_dir) / "processed" / "pois.json").read_text())
    rows = rows if isinstance(rows, list) else rows["pois"]
    directory, anchors = [], []
    for r in rows:
        srcs = [s["source"] for s in r["source_records"]]
        if srcs[0] in DIRECTORY_SOURCES:
            directory.append({
                "id": r["id"], "source": srcs[0], "name": r["name"], "name_en": r.get("name_en"),
                "lat": r["lat"], "lon": r["lon"], "category": r["category"], "address": r.get("address"),
                "opening_hours": r.get("opening_hours"), "schedule": (r.get("raw_tags") or {}).get("schedule_period"),
                "source_url": r["source_url"], "license": r["source_records"][0].get("license")})
        elif r["category"] == "other" and (kind := _anchor_kind(r)) and len(r["name"]) >= 4:
            anchors.append({"name": r["name"], "name_en": r.get("name_en"), "name_kk": r.get("name_kk"),
                            "lat": round(r["lat"], 6), "lon": round(r["lon"], 6), "kind": kind,
                            "source": srcs[0], "source_url": r["source_url"]})
    out = {"provenance": PROVENANCE, "directory": directory, "anchors": anchors}
    TEAM_FILE.parent.mkdir(parents=True, exist_ok=True)
    TEAM_FILE.write_text(json.dumps(out, ensure_ascii=False, indent=0))
    log.info("team layer: %d directory records, %d anchors", len(directory), len(anchors))
    return {"directory": len(directory), "anchors": len(anchors)}


def load() -> dict:
    return json.loads(TEAM_FILE.read_text()) if TEAM_FILE.exists() else {"directory": [], "anchors": []}


def _category(d: dict) -> str | None:
    if d["category"] == "attraction":
        n = fold(d["name"])
        return next((cat for pat, cat in EXPERIENCE if re.search(pat, n)), None)
    return DIRECTORY_CATEGORY.get(d["category"])


# reviewed source errors: the Nur Alem sphere (renamed Alem.AI) is geocoded to the Ailand mall 6 km away
COORD_FIX = {"citypass:81": (51.089314, 71.415901)}


def merge_directory(pois: list[dict], directory: list[dict]) -> list[dict]:
    """Attach directory hours/links to our records; add experiences we do not have."""
    from pipeline.build import FOOD_NIGHT, Grid
    from app.textnorm import contains_name, same_name

    grid = Grid([p for p in pois if not p["name_auto"]])
    added, enriched = [], 0
    for d in directory:
        cat = _category(d)
        if d["id"] in COORD_FIX:
            d = {**d, "lat": COORD_FIX[d["id"]][0], "lon": COORD_FIX[d["id"]][1]}
        brand = re.search(r"«([^»]+)»", d["name"])
        if brand and not any(fold(brand[1]) in fold(p["name"]) for _, p in grid.near(d["lat"], d["lon"], 400)) \
                and any(fold(brand[1]) == fold(p["name"]) for p in pois):
            log.info("team directory: skip %s - %s exists elsewhere, coordinates disagree", d["id"], brand[1])
            continue
        best = None
        for dist, p in grid.near(d["lat"], d["lon"], 300):
            if (p["category"] in FOOD_NIGHT) != (cat in FOOD_NIGHT):
                continue
            names = {p["name"], *p["names"].values()}
            if any(same_name(x, n) or contains_name(x, n) for x in filter(None, (d["name"], d["name_en"])) for n in names) \
                    or dist <= 40 and p["category"] == cat and d["category"] != "attraction":  # same museum, Kazakh name
                if best is None or dist < best[0]:
                    best = (dist, p)
        if best:
            p = best[1]
            if d["opening_hours"] and not p.get("opening_hours"):
                p["opening_hours"] = d["opening_hours"]
                p["hours_source"] = d["source"]
            p.setdefault("links", []).append({"source": d["source"], "url": d["source_url"]})
            if d["source"] not in p["sources"]:
                p["sources"].append(d["source"])
            enriched += 1
            continue
        if not cat or d["source"] != "citypass":
            continue
        added.append({
            "id": f"cp:{d['id'].split(':', 1)[1]}", "name": d["name"], "name_auto": False,
            "names": {"en": d["name_en"]} if d["name_en"] else {}, "category": cat,
            "lat": round(d["lat"], 6), "lon": round(d["lon"], 6), "address": d["address"],
            "opening_hours": d["opening_hours"], "hours_source": d["source"] if d["opening_hours"] else None,
            "check_date": None, "features": {}, "cuisine": None, "brand": None, "website": None, "phone": None,
            "instagram": None, "wikidata": None, "description": None, "description_source": None, "indoor": None,
            "heritage": False, "osm_tags_count": 0, "sources": [d["source"]], "source_url": d["source_url"]})
        grid.add(added[-1])
    log.info("team directory: enriched %d, added %d experiences", enriched, len(added))
    return pois + added


_GENERIC_WORDS = re.compile(r"\b(hotel|hostel|отель|гостиница|қонақүй|хостел|astana|астана|nur sultan|нур султан|"
                            r"by marriott|suites|resort|&|and|the)\b")
_LAT2CYR = [("sch", "щ"), ("sh", "ш"), ("ch", "ч"), ("zh", "ж"), ("kh", "х"), ("ts", "ц"), ("ya", "я"), ("yu", "ю"),
            ("tz", "ц"), ("x", "кс"), ("w", "в"), ("h", "х"), ("c", "к"), ("q", "к"), ("y", "и"), ("j", "дж")]
_LAT1 = dict(zip("abdefgiklmnoprstuvz", "абдефгиклмнопрстувз"))


def to_cyrillic(s: str) -> str:
    """Rough Latin -> Cyrillic spelling ("Hilton" -> "хилтон") for names users type in Russian."""
    s = s.lower()
    for a, b in _LAT2CYR:
        s = s.replace(a, b)
    return "".join(_LAT1.get(c, c) for c in s)


def anchor_keys(names: list[str]) -> list[str]:
    keys = set()
    for n in filter(None, names):
        f = fold(n)
        keys.add(f)
        core = re.sub(r"[\s,.\-]+", " ", _GENERIC_WORDS.sub(" ", f)).strip()
        if len(core) >= 5:
            keys.add(core)
            if re.fullmatch(r"[a-z0-9 ]+", core):
                keys.add(to_cyrillic(core))
    return sorted(k for k in keys if len(k) >= 5)


def gazetteer_anchors(anchors: list[dict]) -> list[dict]:
    return [{"name": a["name"], "lat": a["lat"], "lon": a["lon"], "kind": a["kind"], "source": a["source"],
             "keys": anchor_keys([a["name"], a.get("name_en"), a.get("name_kk")])} for a in anchors]

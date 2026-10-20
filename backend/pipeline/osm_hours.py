"""Opening hours from today's OpenStreetMap for places that have none (open data, ODbL).

One Overpass query returns every object in Astana with `opening_hours`. A place without hours gets them when
- it is that OSM object (same id), or
- it came from another source (Overture, Wikidata) and exactly one OSM object with the same name (or one name
  inside the other) is within MATCH_M.
Existing hours are never overwritten. The value keeps its source (OpenStreetMap), the object's URL and the
mapper's `check_date` when there is one, so the API shows it at the confidence it deserves.

    uv run --project backend python -m pipeline.osm_hours
"""
from __future__ import annotations

import json
import logging
import math

from app.paths import POIS_FILE
from app.textnorm import fold
from pipeline.common import overpass

log = logging.getLogger("pipeline.osm_hours")
MATCH_M = 80
QUERY = """[out:json][timeout:240];
area["name:en"="Astana"]["boundary"="administrative"]->.a;
nwr(area.a)["opening_hours"]["name"];
out center tags;"""


def _m(lat1, lon1, lat2, lon2) -> float:
    k = math.cos(math.radians(lat1))
    return math.hypot((lat2 - lat1) * 111_320, (lon2 - lon1) * 111_320 * k)


def _same(a: str, b: str) -> bool:
    """«Coffee Boom» = «coffee boom»; «Starbucks Mega» ~ «Starbucks» (one name inside the other, 4+ letters)."""
    if not a or not b:
        return False
    return a == b or (min(len(a), len(b)) >= 4 and (a in b or b in a))


def run() -> dict:
    data = overpass(QUERY, kind="osm_hours", max_age_h=24)
    osm = {}
    for e in data.get("elements", []):
        t = e.get("tags", {})
        lat, lon = (e["lat"], e["lon"]) if "lat" in e else (e.get("center", {}).get("lat"), e.get("center", {}).get("lon"))
        if lat is None:
            continue
        osm[f"osm:{e['type'][0]}{e['id']}"] = {"hours": t["opening_hours"].strip(), "name": fold(t.get("name")),
                                               "lat": lat, "lon": lon, "check": t.get("check_date:opening_hours") or t.get("check_date"),
                                               "url": f"https://www.openstreetmap.org/{e['type']}/{e['id']}"}
    lines = POIS_FILE.read_text().splitlines()
    pois = [json.loads(line) for line in lines]
    by_id = by_name = 0
    for p in pois:
        if p.get("opening_hours"):
            continue
        hit = osm.get(p["id"])
        if hit:
            by_id += 1
        else:
            name = fold(p.get("name"))
            near = [o for o in osm.values() if _same(name, o["name"]) and _m(p["lat"], p["lon"], o["lat"], o["lon"]) <= MATCH_M] if name else []
            if len(near) != 1:  # none, or two branches of a chain nearby: we cannot tell which one
                continue
            hit = near[0]
            by_name += 1
        p.update(opening_hours=hit["hours"], hours_source="OpenStreetMap", hours_source_url=hit["url"])
        if hit["check"]:
            p["check_date"] = hit["check"][:10]
        p["sources"] = sorted(set(p.get("sources") or []) | {"osm"})
    POIS_FILE.write_text("".join(json.dumps(p, ensure_ascii=False, separators=(",", ":")) + "\n" for p in pois))
    total = sum(bool(p.get("opening_hours")) for p in pois)
    out = {"osm_objects_with_hours": len(osm), "added_by_id": by_id, "added_by_name": by_name, "places_with_hours": total,
           "places": len(pois)}
    log.info("%s", out)
    return out


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s", datefmt="%H:%M:%S")
    print(run())

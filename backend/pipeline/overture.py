"""Overture Maps Places: fills OSM gaps (mostly food & nightlife) and adds contacts.

Quality filters from the coverage study: confidence >= 0.6, drop "stacked" points
(>= 3 places on one 5-decimal coordinate = geocoded to a centroid), drop historic_site
(mostly misclassified residential complexes). OSM stays the master record.
"""
from __future__ import annotations

import json
import logging

from rapidfuzz import fuzz

from app.paths import BOUNDARY_FILE, RAW_DIR
from app.textnorm import match_key

log = logging.getLogger("pipeline.overture")

RELEASE = "2026-09-23.1"
OV_FILE = RAW_DIR / "overture_astana.json"

# Overture basic_category -> our category
OV_MAP = {
    "restaurant": "restaurant", "cafe": "cafe", "coffee_shop": "cafe", "tea_room": "cafe", "bakery": "sweets",
    "dessert_shop": "sweets", "ice_cream_shop": "sweets", "fast_food_restaurant": "fast_food", "bar": "bar",
    "pub": "bar", "wine_bar": "bar", "cocktail_bar": "bar", "lounge": "hookah", "hookah_bar": "hookah",
    "night_club": "nightclub", "nightclub": "nightclub", "karaoke": "karaoke", "music_venue": "karaoke",
    "shopping_mall": "mall", "shopping_center": "mall", "park": "park", "playground": "playground",
    "museum": "museum", "art_museum": "museum", "history_museum": "museum", "art_gallery": "gallery",
    "movie_theater": "cinema", "cinema": "cinema", "theatre": "theatre", "theater": "theatre",
    "performing_arts_venue": "theatre", "library": "library", "bowling_alley": "active", "escape_room": "active",
    "escape_game": "active", "ice_skating_rink": "active", "trampoline_park": "kids_indoor",
    "amusement_park": "theme_park", "water_park": "water_park", "aquarium": "zoo_aquarium", "zoo": "zoo_aquarium",
    "indoor_playcenter": "kids_indoor", "kids_recreation_and_party": "kids_indoor", "spa": "spa",
    "bathhouse": "spa", "sauna": "spa", "coworking_space": "coworking", "bookstore": "souvenir",
    "souvenir_shop": "souvenir", "gift_shop": "souvenir", "landmark_and_historical_building": "landmark",
    "monument": "monument", "sculpture_statue": "artwork", "mosque": "worship", "church_cathedral": "worship",
    "religious_organization": None, "food_court": "fast_food", "beer_bar": "bar", "sports_bar": "bar",
    "bistro": "cafe", "burger_restaurant": "fast_food", "pizza_restaurant": "restaurant",
    "sushi_restaurant": "restaurant", "steakhouse": "restaurant", "gaming_venue": "active",
    "arcade": "kids_indoor", "climbing_gym": "active", "laser_tag": "active", "go_kart_track": "active",
    # names observed in the 2026-09 release for Astana
    "casual_eatery": "cafe", "theatre_venue": "theatre", "dance_club": "nightclub", "public_plaza": "garden",
    "cultural_center": "arts_centre", "muslim_place_of_worship": "worship", "christian_place_of_worship": "worship",
    "brewery": "bar", "non_alcoholic_beverage_venue": "cafe", "books_music_and_video_store": "souvenir",
}


def extract() -> list[dict]:
    import duckdb
    from shapely.geometry import Point, shape
    from shapely.prepared import prep

    if OV_FILE.exists():
        return json.loads(OV_FILE.read_text())
    con = duckdb.connect()
    con.sql("SET memory_limit='1GB'; SET threads=4; INSTALL httpfs; LOAD httpfs; SET s3_region='us-west-2';")
    rows = con.sql(f"""
      SELECT id, names.primary AS name, confidence, basic_category,
             websites[1] AS website, phones[1] AS phone, addresses[1].freeform AS address,
             (bbox.ymin + bbox.ymax) / 2 AS lat, (bbox.xmin + bbox.xmax) / 2 AS lon
      FROM read_parquet('s3://overturemaps-us-west-2/release/{RELEASE}/theme=places/type=place/*.parquet',
                        hive_partitioning=1)
      WHERE bbox.xmin BETWEEN 71.2179 AND 71.7852 AND bbox.ymin BETWEEN 50.8576 AND 51.3512
    """).fetchall()
    cols = ["id", "name", "confidence", "basic_category", "website", "phone", "address", "lat", "lon"]
    poly = prep(shape(json.loads(BOUNDARY_FILE.read_text())["geometry"]))
    out = [dict(zip(cols, r)) for r in rows if poly.contains(Point(r[8], r[7]))]
    OV_FILE.parent.mkdir(parents=True, exist_ok=True)
    OV_FILE.write_text(json.dumps(out, ensure_ascii=False))
    log.info("overture places in Astana: %d", len(out))
    return out


def merge_overture(pois: list[dict], places: list[dict]) -> list[dict]:
    from collections import Counter

    from pipeline.build import Grid

    stack = Counter((round(p["lat"], 5), round(p["lon"], 5)) for p in places)
    grid = Grid([p for p in pois if not p["name_auto"]])
    added, enriched, skipped = [], 0, Counter()
    for o in places:
        cat = OV_MAP.get(o.get("basic_category") or "")
        if not cat or not o.get("name"):
            skipped["category"] += 1
            continue
        if (o.get("confidence") or 0) < 0.6:
            skipped["confidence"] += 1
            continue
        if stack[(round(o["lat"], 5), round(o["lon"], 5))] >= 3:
            skipped["stacked"] += 1
            continue
        k = match_key(o["name"])
        best = None
        for d, p in grid.near(o["lat"], o["lon"], 150):
            sc = max(fuzz.token_set_ratio(k, match_key(n)) for n in {p["name"], *p["names"].values()})
            if sc >= 85 and (best is None or d < best[0]):
                best = (d, p)
        if best:
            p = best[1]
            p["website"] = p.get("website") or o.get("website")
            p["phone"] = p.get("phone") or o.get("phone")
            p["address"] = p.get("address") or o.get("address")
            if "overture" not in p["sources"]:
                p["sources"].append("overture")
            enriched += 1
            continue
        added.append({
            "id": f"ov:{o['id'][:16]}", "name": o["name"].strip(), "name_auto": False, "names": {}, "category": cat,
            "lat": round(o["lat"], 6), "lon": round(o["lon"], 6), "address": o.get("address"), "opening_hours": None,
            "check_date": None, "features": {}, "cuisine": None, "brand": None, "website": o.get("website"),
            "phone": o.get("phone"), "instagram": None, "wikidata": None, "description": None,
            "description_source": None, "indoor": None, "heritage": False, "osm_tags_count": 0,
            "sources": ["overture"], "overture_confidence": round(o["confidence"], 2),
            "source_url": None,
        })
        grid.add(added[-1])
    log.info("overture: enriched %d OSM POIs, added %d, skipped %s", enriched, len(added), dict(skipped))
    return pois + added


def category_stats() -> list[tuple[str, int]]:
    from collections import Counter
    return Counter(p.get("basic_category") for p in extract()).most_common(120)

"""OpenStreetMap collection via Overpass (filtered by the Astana admin boundary, not a bbox)."""
from __future__ import annotations

import json
import logging

from ayat_backend.app.paths import BOUNDARY_FILE, RAW_DIR
from ayat_backend.pipeline.common import ASTANA_AREA_ID, ASTANA_RELATION, get_json, overpass

log = logging.getLogger("pipeline.osm")

POI_QUERY = f"""[out:json][timeout:300];
area(id:{ASTANA_AREA_ID})->.a;
(
  nwr(area.a)["amenity"~"^(cafe|restaurant|bar|pub|biergarten|fast_food|food_court|ice_cream|theatre|cinema|arts_centre|library|nightclub|community_centre|planetarium|marketplace|place_of_worship|coworking_space|internet_cafe|events_venue|exhibition_centre|concert_hall|music_venue|karaoke_box|hookah_lounge|public_bath)$"];
  nwr(area.a)["tourism"~"^(museum|attraction|viewpoint|gallery|artwork|zoo|aquarium|theme_park)$"];
  nwr(area.a)["leisure"~"^(park|playground|garden|water_park|amusement_arcade|sports_centre|ice_rink|bowling_alley|escape_game|trampoline_park|swimming_pool|miniature_golf|sauna|indoor_play|dance)$"];
  nwr(area.a)["historic"]["name"];
  nwr(area.a)["man_made"~"^(tower|obelisk|observatory)$"]["name"];
  nwr(area.a)["shop"~"^(mall|department_store|books|gift|souvenir|art|bakery|confectionery|chocolate|coffee|tea)$"];
  nwr(area.a)["office"="coworking"];
  nwr(area.a)["attraction"]["name"];
  nwr(area.a)["building"~"^(mosque|cathedral|church|synagogue|temple|museum|theatre)$"]["name"];
);
out center tags;"""

# named streets / residential complexes / neighbourhoods / stations: used to label unnamed
# playgrounds and as a gazetteer for "I'm near ..." queries
CONTEXT_QUERY = f"""[out:json][timeout:300];
area(id:{ASTANA_AREA_ID})->.a;
(
  way(area.a)["highway"~"^(primary|secondary|tertiary|residential|pedestrian|living_street|unclassified)$"]["name"];
  nwr(area.a)["landuse"="residential"]["name"];
  nwr(area.a)["place"~"^(neighbourhood|quarter|suburb|square)$"]["name"];
  nwr(area.a)["railway"="station"]["name"];
  nwr(area.a)["aeroway"~"^(aerodrome|terminal)$"]["name"];
  nwr(area.a)["building"~"^(university|government|stadium)$"]["name"];
  nwr(area.a)["leisure"="stadium"]["name"];
  nwr(area.a)["tourism"="hotel"]["name"];
);
out center tags;"""

# small extra gazetteer layer: stations, airport, stadiums, universities, government, boulevards
GAZ_QUERY = f"""[out:json][timeout:120];
area(id:{ASTANA_AREA_ID})->.a;
(
  nwr(area.a)["railway"="station"]["name"];
  nwr(area.a)["aeroway"~"^(aerodrome|terminal)$"]["name"];
  nwr(area.a)["leisure"="stadium"]["name"];
  nwr(area.a)["building"~"^(stadium|university|government)$"]["name"];
  nwr(area.a)["amenity"="university"]["name"];
  nwr(area.a)["office"="government"]["name"~"Ақорда|Акорда|Akorda"];
  way(area.a)["highway"="pedestrian"]["name"];
);
out center tags;"""


def fetch_gazetteer_extra() -> list[dict]:
    try:
        return overpass(GAZ_QUERY, kind="osm_gaz", timeout=60, cycles=1).get("elements", [])
    except RuntimeError as e:
        log.warning("gazetteer extra layer unavailable: %s", str(e)[:200])
        return []


RIVER_QUERY = f"""[out:json][timeout:180];
area(id:{ASTANA_AREA_ID})->.a;
way(area.a)["waterway"="river"]["name"~"Есіл|Есиль|Ишим|Yesil|Ishim",i];
out geom;"""


def fetch_pois() -> dict:
    data = overpass(POI_QUERY, kind="osm_pois")
    log.info("OSM POI elements: %d", len(data.get("elements", [])))
    return data


def fetch_context() -> dict:
    data = overpass(CONTEXT_QUERY, kind="osm_context")
    log.info("OSM context elements: %d", len(data.get("elements", [])))
    return data


def fetch_river() -> list[list[list[float]]]:
    """Yesil (Ishim) river centre-lines as [[lat, lon], ...] polylines (for the routing fallback)."""
    try:
        data = overpass(RIVER_QUERY, kind="osm_river", timeout=90, cycles=1)
    except RuntimeError as e:  # optional layer: the walk graph already knows the bridges
        log.warning("river layer unavailable: %s", str(e)[:200])
        return []
    lines =[[[round(p["lat"], 6), round(p["lon"], 6)] for p in w["geometry"]]
             for w in data.get("elements", []) if w.get("geometry")]
    log.info("river polylines: %d (%d points)", len(lines), sum(map(len, lines)))
    return lines


def fetch_boundary() -> dict:
    """Astana admin boundary polygon (GeoJSON) from Nominatim; one request, cached."""
    data = get_json("https://nominatim.openstreetmap.org/lookup",
                    params={"osm_ids": f"R{ASTANA_RELATION}", "polygon_geojson": 1, "format": "json"},
                    kind="nominatim", max_age_h=24 * 30, delay=1.0)
    geom = data[0]["geojson"]
    BOUNDARY_FILE.parent.mkdir(parents=True, exist_ok=True)
    BOUNDARY_FILE.write_text(json.dumps({"type": "Feature", "properties": {"name": "Astana", "source": "OSM R3087155"},
                                         "geometry": geom}))
    (RAW_DIR / "boundary_ok").touch()
    return geom


def element_latlon(e: dict) -> tuple[float, float] | None:
    if "lat" in e:
        return e["lat"], e["lon"]
    c = e.get("center")
    return (c["lat"], c["lon"]) if c else None


def element_url(e: dict) -> str:
    return f"https://www.openstreetmap.org/{e['type']}/{e['id']}"

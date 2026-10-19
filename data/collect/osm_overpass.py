"""Collect uncapped named Astana POIs and its real OSM administrative boundary.

Run ``python -m data.collect.osm_overpass``. Raw responses are reused unless
``--refresh`` is given. A failed refresh preserves a previous valid response.
Only public Overpass endpoints are used, sequentially with finite backoff.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

# Listed public instances: https://wiki.openstreetmap.org/wiki/Overpass_API
OVERPASS_ENDPOINTS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
)
DEFAULT_BBOX = (50.9, 71.0, 51.4, 71.9)  # south, west, north, east; includes airport
REGIONAL_EXTRACT_URL = "https://download.geofabrik.de/asia/kazakhstan-latest.osm.pbf"
BOUNDARY_QUERY = '''[out:json][timeout:120];
relation["boundary"="administrative"]["wikidata"="Q1520"];
out tags geom;'''
POI_KEYS = (
    "amenity", "tourism", "leisure", "historic", "shop", "sport", "club",
    "natural", "aeroway", "railway", "public_transport", "office", "craft",
    "healthcare", "landuse",
)
LANDMARK_TYPES = {"tower", "water_tower", "lighthouse", "observatory", "windmill", "obelisk"}
LIFECYCLE = ("abandoned", "disused", "demolished", "razed", "removed", "destroyed", "proposed", "construction")


def _text(value):
    return value.strip() if isinstance(value, str) and value.strip() else None


def _validate_bbox(bbox):
    if len(bbox) != 4 or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in bbox):
        raise ValueError("bbox must contain four finite numbers: south, west, north, east")
    south, west, north, east = bbox
    if not (-90 <= south < north <= 90 and -180 <= west < east <= 180):
        raise ValueError("bbox must have valid coordinates and south<north, west<east")
    return tuple(bbox)


def poi_query(bbox):
    """All named nodes, ways and relations with place/venue/landmark tags, no limit."""
    coordinates = ",".join(str(v) for v in _validate_bbox(bbox))
    keys = "|".join(POI_KEYS)
    landmarks = "|".join(sorted(LANDMARK_TYPES))
    return f'''[out:json][timeout:120][maxsize:268435456];
(
  nwr[~"^name(:.*)?$"~"."][~"^({keys})$"~"."]({coordinates});
  nwr[~"^name(:.*)?$"~"."]["man_made"~"^({landmarks})$"]({coordinates});
);
out center tags;'''


def _category(tags):
    amenity = tags.get("amenity")
    if amenity in {"cafe", "restaurant", "bar", "cinema", "theatre", "library"}:
        return amenity
    if amenity in {"pub", "biergarten"}:
        return "bar"
    if amenity in {"fast_food", "food_court"}:
        return "restaurant"
    if amenity == "nightclub" or tags.get("club") == "music":
        return "nightlife"
    if amenity in {"coworking_space", "coworking"} or tags.get("office") == "coworking":
        return "coworking"
    tourism = tags.get("tourism")
    if tourism in {"museum", "gallery", "viewpoint"}:
        return tourism
    if tags.get("historic") in {"monument", "memorial", "obelisk"}:
        return "monument"
    leisure = tags.get("leisure")
    if leisure == "playground":
        return "playground"
    if leisure in {"park", "garden", "nature_reserve"} or tags.get("landuse") == "recreation_ground":
        return "park"
    if leisure in {"sports_centre", "sports_hall", "stadium", "pitch", "fitness_centre", "swimming_pool", "ice_rink", "golf_course", "track", "water_park"} or tags.get("sport"):
        return "sport"
    if tags.get("shop") in {"mall", "department_store"}:
        return "mall"
    if tourism in {"attraction", "artwork", "zoo", "theme_park", "aquarium"} or amenity == "arts_centre":
        return "attraction"
    return "other"


def _closed(tags):
    if any(str(tags.get(key, "")).lower() in {"yes", "true", "1"} for key in LIFECYCLE):
        return True
    if any(key.startswith(tuple(f"{prefix}:" for prefix in LIFECYCLE)) for key in tags):
        # A disused side feature (e.g. disused:railway at an active cafe) is not
        # sufficient by itself. A lifecycle POI tag with no active counterpart is.
        active = any(tags.get(key) not in {None, "no", "disused", "abandoned", "construction", "proposed"} for key in POI_KEYS)
        if not active:
            return True
        if any(tags.get(f"{prefix}:{key}") == tags.get(key) and tags.get(key)
               for prefix in LIFECYCLE for key in POI_KEYS):
            return True
    if any(tags.get(key) in {"disused", "abandoned", "demolished", "construction", "proposed", "vacant", "closed"} for key in POI_KEYS):
        return True
    return str(tags.get("opening_hours", "")).strip().lower() in {"closed", "off", "permanently closed"} or str(tags.get("closed", "")).lower() in {"yes", "true", "permanent"}


def parse_elements(payload):
    """Return candidates and rejection counts without inventing unavailable facts."""
    pois = {}
    rejected = Counter()
    for element in payload.get("elements", []):
        tags = element.get("tags") or {}
        if _closed(tags):
            rejected["closed_or_inactive"] += 1
            continue
        name = next((_text(tags.get(key)) for key in ("name", "name:kk", "name:ru", "name:en", "int_name", "official_name") if _text(tags.get(key))), None)
        if not name:
            rejected["unnamed"] += 1
            continue
        if not any(tags.get(key) and tags[key] != "no" for key in POI_KEYS) and tags.get("man_made") not in LANDMARK_TYPES:
            rejected["not_poi"] += 1
            continue
        kind, osm_id = element.get("type"), element.get("id")
        location = element if kind == "node" else element.get("center", {})
        try:
            lat, lon = float(location["lat"]), float(location["lon"])
            if not (math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180):
                raise ValueError("invalid coordinates")
        except (KeyError, ValueError, TypeError):
            rejected["invalid_coordinates"] += 1
            continue
        if kind not in {"node", "way", "relation"} or not isinstance(osm_id, int):
            rejected["invalid_identity"] += 1
            continue
        description = next((_text(tags.get(key)) for key in ("description", "description:ru", "description:kk", "description:en") if _text(tags.get(key))), None)
        category = _category(tags)
        wheelchair = tags.get("wheelchair") if tags.get("wheelchair") in {"yes", "limited", "no"} else None
        kid_friendly = True if tags.get("leisure") == "playground" or tags.get("tourism") in {"zoo", "aquarium", "theme_park"} or tags.get("kids_area") == "yes" else None
        address = _text(tags.get("addr:full")) or ", ".join(filter(None, (_text(tags.get(key)) for key in ("addr:street", "addr:place", "addr:housenumber", "addr:unit")))) or None
        candidate_id = f"osm:{kind}/{osm_id}"
        candidate = {
            "id": candidate_id, "name": name, "name_en": _text(tags.get("name:en")),
            "name_kk": _text(tags.get("name:kk")), "lat": lat, "lon": lon,
            "category": category,
            "tags": sorted(f"{key}={value}" for key, value in tags.items() if key in set(POI_KEYS) | {"man_made", "cuisine", "religion", "denomination", "access", "fee"}),
            "raw_tags": tags, "description": description,
            "description_source": "osm" if description else None,
            "opening_hours": _text(tags.get("opening_hours")),
            "phone": _text(tags.get("phone")) or _text(tags.get("contact:phone")),
            "website": _text(tags.get("website")) or _text(tags.get("contact:website")),
            "address": address, "wheelchair": wheelchair, "kid_friendly": kid_friendly,
            "rating": None, "rating_count": None, "source": "osm",
            "source_url": f"https://www.openstreetmap.org/{kind}/{osm_id}",
            "source_license": "ODbL-1.0",
        }
        if candidate_id in pois:
            rejected["duplicate_osm_id"] += 1
        pois[candidate_id] = candidate
    return [pois[key] for key in sorted(pois)], dict(rejected)


def _join_rings(segments):
    remaining = [list(segment) for segment in segments if len(segment) >= 2]
    rings = []
    while remaining:
        ring = remaining.pop(0)
        while ring[0] != ring[-1]:
            for index, segment in enumerate(remaining):
                if ring[-1] == segment[0]:
                    ring.extend(segment[1:])
                elif ring[-1] == segment[-1]:
                    ring.extend(reversed(segment[:-1]))
                elif ring[0] == segment[-1]:
                    ring = segment[:-1] + ring
                elif ring[0] == segment[0]:
                    ring = list(reversed(segment[1:])) + ring
                else:
                    continue
                remaining.pop(index)
                break
            else:
                # Never fabricate the missing edge of an incomplete boundary.
                return None
        if len(ring) >= 4:
            rings.append(ring)
    return rings


def _inside(point, ring):
    x, y = point
    inside = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def boundary_geometry(payload):
    """Assemble complete relation way geometries, retaining islands and holes."""
    nodes = {element["id"]: element for element in payload.get("elements", []) if element.get("type") == "node"}
    ways = {element["id"]: element for element in payload.get("elements", []) if element.get("type") == "way"}
    relations = [element for element in payload.get("elements", [])
                 if element.get("type") == "relation" and element.get("tags", {}).get("wikidata") == "Q1520"
                 and element.get("tags", {}).get("boundary") == "administrative"]
    for relation in sorted(relations, key=lambda e: int(e.get("tags", {}).get("admin_level", 99))):
        segments = {"outer": [], "inner": []}
        incomplete = False
        for member in relation.get("members", []):
            role = member.get("role") or "outer"
            if member.get("type") == "way" and role in segments:
                geometry = member.get("geometry", [])
                if not geometry and member.get("ref") in ways:
                    way = ways[member["ref"]]
                    geometry = way.get("geometry") or [nodes.get(node, {}) for node in way.get("nodes", [])]
                if not geometry or any("lon" not in point or "lat" not in point for point in geometry):
                    incomplete = True
                    continue
                segments[role].append([[point["lon"], point["lat"]] for point in geometry])
        if incomplete:
            continue
        outers, inners = _join_rings(segments["outer"]), _join_rings(segments["inner"])
        if not outers or inners is None:
            continue
        polygons = [[ring] for ring in outers]
        for hole in inners:
            containing = [polygon for polygon in polygons if _inside(hole[0], polygon[0])]
            if not containing:
                break
            # Assign to the smallest containing exterior, important for islands.
            def area(polygon):
                ring = polygon[0]
                return abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(ring, ring[1:])))
            min(containing, key=area).append(hole)
        else:
            return {"type": "MultiPolygon", "coordinates": polygons}
    return None


def geometry_bbox(geometry):
    polygons = geometry["coordinates"] if geometry["type"] == "MultiPolygon" else [geometry["coordinates"]]
    points = [point for polygon in polygons for ring in polygon for point in ring]
    return (min(p[1] for p in points), min(p[0] for p in points), max(p[1] for p in points), max(p[0] for p in points))


def read_osm_file(path: Path, bbox: tuple | None = None) -> dict:
    """Read a complete local OSM/PBF extract when public Overpass is unavailable.

    Requires the optional ``osmium`` package. libosmium assembles genuine area
    geometries from referenced ways/nodes; no approximate city polygon is made.
    """
    import osmium

    factory = osmium.geom.GeoJSONFactory()
    boundary = None
    boundary_urls = []
    # Restrict relation assembly to Q1520 for this first pass. Location resolution
    # happens before filters, so untagged member nodes and ways stay available.
    processor = osmium.FileProcessor(str(path)).with_areas(
        osmium.filter.TagFilter(("wikidata", "Q1520"))
    ).with_filter(osmium.filter.TagFilter(("wikidata", "Q1520")))
    for obj in processor:
        if obj.is_area() and not obj.from_way() and obj.tags.get("boundary") == "administrative":
            boundary = json.loads(factory.create_multipolygon(obj))
            boundary_urls.append(f"https://www.openstreetmap.org/relation/{obj.orig_id()}")
    del processor
    used_bbox = _validate_bbox(bbox) if bbox is not None else geometry_bbox(boundary) if boundary else DEFAULT_BBOX
    south, west, north, east = used_bbox
    elements = []
    relations = []
    skipped_geometry = 0
    processor = osmium.FileProcessor(str(path)).with_areas(
        osmium.filter.KeyFilter(*POI_KEYS, "man_made")
    ).with_filter(osmium.filter.KeyFilter("name", "name:kk", "name:ru", "name:en", "int_name", "official_name"))
    for obj in processor:
        tags = dict(obj.tags)
        if not any(tags.get(key) for key in POI_KEYS) and tags.get("man_made") not in LANDMARK_TYPES:
            continue
        if obj.is_node():
            if not obj.location.valid():
                skipped_geometry += 1
                continue
            kind, osm_id, lat, lon = "node", obj.id, obj.lat, obj.lon
        elif obj.is_way():
            points = [(node.lat, node.lon) for node in obj.nodes if node.location.valid()]
            if len(points) != len(obj.nodes) or not points:
                skipped_geometry += 1
                continue
            kind, osm_id = "way", obj.id
            lat = (min(p[0] for p in points) + max(p[0] for p in points)) / 2
            lon = (min(p[1] for p in points) + max(p[1] for p in points)) / 2
        elif obj.is_area() and not obj.from_way():
            try:
                geometry = json.loads(factory.create_multipolygon(obj))
                s, w, n, e = geometry_bbox(geometry)
            except (RuntimeError, ValueError):
                skipped_geometry += 1
                continue
            kind, osm_id, lat, lon = "relation", obj.orig_id(), (s + n) / 2, (w + e) / 2
        elif obj.is_relation() and tags.get("type") not in {"multipolygon", "boundary"}:
            node_points = []
            for member in obj.members:
                if member.type == "n":
                    try:
                        location = processor.node_location_storage.get(member.ref)
                        node_points.append((location.lat, location.lon))
                    except KeyError:
                        pass
            relations.append({"id": obj.id, "tags": tags, "nodes": node_points,
                              "ways": [m.ref for m in obj.members if m.type == "w"],
                              "nested_relations": any(m.type == "r" for m in obj.members)})
            continue
        else:
            continue
        if south <= lat <= north and west <= lon <= east:
            element = {"type": kind, "id": osm_id, "tags": tags}
            element.update({"lat": lat, "lon": lon} if kind == "node" else {"center": {"lat": lat, "lon": lon}})
            elements.append(element)
    del processor
    if relations:
        way_ids = {way for relation in relations for way in relation["ways"]}
        bounds = {}
        if way_ids:
            processor = osmium.FileProcessor(str(path)).with_locations().with_filter(
                osmium.filter.EntityFilter(osmium.osm.WAY)
            ).with_filter(osmium.filter.IdFilter(way_ids))
            for way in processor:
                points = [(node.lat, node.lon) for node in way.nodes if node.location.valid()]
                if points and len(points) == len(way.nodes):
                    bounds[way.id] = [(min(p[0] for p in points), min(p[1] for p in points)),
                                      (max(p[0] for p in points), max(p[1] for p in points))]
            del processor
        for relation in relations:
            points = relation["nodes"] + [point for way in relation["ways"] for point in bounds.get(way, [])]
            if not points or relation["nested_relations"] or any(way not in bounds for way in relation["ways"]):
                skipped_geometry += 1
                continue
            lat = (min(p[0] for p in points) + max(p[0] for p in points)) / 2
            lon = (min(p[1] for p in points) + max(p[1] for p in points)) / 2
            if south <= lat <= north and west <= lon <= east:
                elements.append({"type": "relation", "id": relation["id"], "tags": relation["tags"],
                                 "center": {"lat": lat, "lon": lon}})
    pois, rejected = parse_elements({"elements": elements})
    if skipped_geometry:
        rejected["incomplete_local_geometry_countrywide"] = skipped_geometry
    return {"pois": pois, "boundary": boundary, "bbox": list(used_bbox),
            "boundary_source_urls": sorted(set(boundary_urls)), "raw_count": len(elements), "rejected": rejected}


def _atomic_json(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def download_extract(raw_dir: Path, refresh: bool = False) -> Path:
    """Download the public Kazakhstan extract once, then reuse its verified cache.

    This optional fallback is selected explicitly with ``--download-pbf``;
    Overpass outages never silently trigger a large country download.
    """
    raw_dir = Path(raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    destination = raw_dir / "kazakhstan-latest.osm.pbf"
    metadata_path = raw_dir / "pbf_download.json"
    if destination.exists() and metadata_path.exists() and not refresh:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if destination.stat().st_size == metadata.get("bytes"):
            return destination
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    request = Request(REGIONAL_EXTRACT_URL, headers={"User-Agent": "AstanaWalkAI-data-collector/1.0"})
    checksum, size = hashlib.sha256(), 0
    with urlopen(request, timeout=60) as response, temporary.open("wb") as output:
        expected = response.headers.get("Content-Length")
        source_url = response.geturl()
        last_modified = response.headers.get("Last-Modified")
        while chunk := response.read(1024 * 1024):
            output.write(chunk)
            checksum.update(chunk)
            size += len(chunk)
    if expected is not None and size != int(expected):
        raise OSError(f"Incomplete regional extract: received {size} bytes, expected {expected}")
    if size == 0:
        raise OSError("Regional extract was empty")
    temporary.replace(destination)
    _atomic_json(metadata_path, {
        "source_url": source_url, "requested_url": REGIONAL_EXTRACT_URL,
        "retrieved_at": datetime.now(timezone.utc).isoformat(), "last_modified": last_modified,
        "bytes": size, "sha256": checksum.hexdigest(), "source_license": "ODbL-1.0",
    })
    return destination


def collect_file(path: Path, raw_dir: Path, bbox: tuple | None = None, refresh: bool = False) -> dict:
    """Export an uncapped local regional OSM extract using the collector contract."""
    started = time.monotonic()
    path, raw_dir = Path(path).resolve(), Path(raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    if bbox is not None:
        bbox = _validate_bbox(bbox)
    stat = path.stat()
    signature = {"path": str(path), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns,
                 "requested_bbox": list(bbox) if bbox is not None else None}
    metadata_path = raw_dir / "local_extract.json"
    if not refresh and metadata_path.exists() and (raw_dir / "candidates.json").exists() and (raw_dir / "report.json").exists():
        try:
            previous = json.loads(metadata_path.read_text(encoding="utf-8"))
            if previous == signature:
                pois = json.loads((raw_dir / "candidates.json").read_text(encoding="utf-8"))
                boundary = json.loads((raw_dir / "boundary.geojson").read_text(encoding="utf-8")) if (raw_dir / "boundary.geojson").exists() else None
                report = json.loads((raw_dir / "report.json").read_text(encoding="utf-8"))
                report["cached"] = {"pois": True, "boundary": boundary is not None}
                report["elapsed_seconds"] = round(time.monotonic() - started, 3)
                return {"pois": pois, "boundary": boundary, "report": report}
        except (OSError, ValueError, TypeError):
            pass
    try:
        result = read_osm_file(path, bbox)
    except (OSError, RuntimeError, ImportError, ValueError) as error:
        pois, boundary = [], None
        try:
            if (raw_dir / "candidates.json").exists():
                pois = json.loads((raw_dir / "candidates.json").read_text(encoding="utf-8"))
            if (raw_dir / "boundary.geojson").exists():
                boundary = json.loads((raw_dir / "boundary.geojson").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        report = {
            "source": "osm", "status": "partial" if pois else "unavailable", "count": len(pois),
            "collection_method": "regional_osm_extract", "extract_file": path.name,
            "source_urls": [REGIONAL_EXTRACT_URL], "source_license": "ODbL-1.0",
            "boundary_available": boundary is not None, "stale_cache": bool(pois),
            "cached": {"pois": bool(pois), "boundary": boundary is not None},
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "errors": [{"source": path.name, "error": f"{type(error).__name__}: {error}"}],
        }
        _atomic_json(raw_dir / "report.json", report)
        return {"pois": pois, "boundary": boundary, "report": report}
    pois, boundary = result["pois"], result["boundary"]
    download_metadata = raw_dir / "pbf_download.json"
    downloaded = json.loads(download_metadata.read_text(encoding="utf-8")) if download_metadata.exists() else {}
    report = {
        "source": "osm", "status": "ok" if boundary else "partial", "count": len(pois),
        "collection_method": "regional_osm_extract", "extract_file": path.name,
        "raw_count": result["raw_count"], "rejected": result["rejected"],
        "categories": dict(sorted(Counter(p["category"] for p in pois).items())),
        "bbox": result["bbox"], "bbox_order": "south,west,north,east",
        "boundary_available": boundary is not None, "boundary_wikidata": "Q1520",
        "boundary_source_urls": result["boundary_source_urls"],
        "source_urls": [downloaded.get("source_url", REGIONAL_EXTRACT_URL)],
        "source_license": "ODbL-1.0", "attribution": "© OpenStreetMap contributors",
        "license_url": "https://www.openstreetmap.org/copyright",
        "cached": {"pois": False, "boundary": False}, "stale_cache": False,
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "source_retrieved_at": downloaded.get("retrieved_at"),
        "elapsed_seconds": round(time.monotonic() - started, 3), "errors": [],
        "notes": ["Complete regional OSM extract used after public Overpass instances were unavailable.",
                  "Named nodes, ways and relations, uncapped, within the actual city boundary envelope.",
                  "Ways and relation coordinates use their geographic envelope center; normalization clips to the boundary.",
                  "No invented descriptions or ratings; earlier endpoint failures are retained in initial_unavailable_report.json."],
        "extract_metadata": downloaded,
    }
    _atomic_json(raw_dir / "candidates.json", pois)
    if boundary is not None:
        _atomic_json(raw_dir / "boundary.geojson", boundary)
    _atomic_json(metadata_path, signature)
    _atomic_json(raw_dir / "report.json", report)
    return {"pois": pois, "boundary": boundary, "report": report}


def _request_overpass(query, endpoint):
    request = Request(endpoint, data=urlencode({"data": query}).encode(), headers={
        "User-Agent": "AstanaWalkAI-data-collector/1.0 (uncapped named city POIs; local research)",
        "Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded",
    })
    with urlopen(request, timeout=150) as response:
        payload = json.load(response)
    if not isinstance(payload, dict) or not isinstance(payload.get("elements"), list):
        raise ValueError("Overpass returned an invalid payload")
    if payload.get("remark"):
        raise ValueError(f"Overpass returned incomplete results: {payload['remark']}")
    return payload


def _fetch_query(query, raw_dir, name, refresh, errors):
    digest = hashlib.sha256(query.encode()).hexdigest()[:16]
    path = raw_dir / f"{name}_{digest}.json"
    previous = None
    if path.exists():
        try:
            previous = json.loads(path.read_text(encoding="utf-8"))
            if previous.get("query") != query or not isinstance(previous.get("payload", {}).get("elements"), list):
                previous = None
        except (OSError, ValueError, TypeError):
            previous = None
    if previous and not refresh:
        return previous, True, False
    for index, endpoint in enumerate(OVERPASS_ENDPOINTS):
        if index:
            time.sleep(2 ** index)
        try:
            payload = _request_overpass(query, endpoint)
            result = {"query": query, "source_url": endpoint,
                      "retrieved_at": datetime.now(timezone.utc).isoformat(), "payload": payload}
            _atomic_json(path, result)
            return result, False, False
        except (OSError, ValueError, TimeoutError) as error:
            errors.append({"query": name, "source_url": endpoint, "error": f"{type(error).__name__}: {error}"})
            if isinstance(error, HTTPError) and error.code in {429, 406}:
                # Also wait after the final instance: a subsequent query must
                # not immediately bypass the service's throttling response.
                time.sleep(30)
    return previous, bool(previous), bool(previous)


def collect(raw_dir: Path, bbox: tuple | None = None, refresh: bool = False) -> dict:
    """Cache and return ``pois``, Astana ``boundary`` geometry and a source ``report``.

    ``raw_dir`` is the source-specific directory, normally ``data/raw/osm``.
    Candidates cover the boundary envelope. The normalization stage clips points
    to the administrative polygon, retaining full provenance of exclusions.
    """
    if bbox is not None:
        bbox = _validate_bbox(bbox)
    started = time.monotonic()
    raw_dir = Path(raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    local_metadata = raw_dir / "local_extract.json"
    if local_metadata.exists():
        try:
            local_path = Path(json.loads(local_metadata.read_text(encoding="utf-8"))["path"])
            if local_path.exists():
                return collect_file(local_path, raw_dir, bbox, refresh)
        except (KeyError, ValueError, TypeError):
            pass
    local_files = sorted(raw_dir.glob("*.osm.pbf"))
    if local_files:
        return collect_file(local_files[-1], raw_dir, bbox, refresh)
    errors = []
    boundary_response, boundary_cached, boundary_stale = _fetch_query(BOUNDARY_QUERY, raw_dir, "boundary_response", refresh, errors)
    boundary = boundary_geometry(boundary_response["payload"]) if boundary_response else None
    used_bbox = bbox or (geometry_bbox(boundary) if boundary else DEFAULT_BBOX)
    places_response, places_cached, places_stale = _fetch_query(poi_query(used_bbox), raw_dir, "pois_response", refresh, errors)
    pois, rejected = parse_elements(places_response["payload"]) if places_response else ([], {})
    source_urls = sorted({response["source_url"] for response in (boundary_response, places_response) if response})
    boundary_relations = [element for element in (boundary_response or {}).get("payload", {}).get("elements", []) if element.get("type") == "relation" and element.get("tags", {}).get("wikidata") == "Q1520"]
    report = {
        "source": "osm", "status": "unavailable" if not places_response else "partial" if errors or boundary is None else "ok",
        "count": len(pois), "raw_count": len((places_response or {}).get("payload", {}).get("elements", [])),
        "rejected": rejected, "categories": dict(sorted(Counter(p["category"] for p in pois).items())),
        "bbox": list(used_bbox), "bbox_order": "south,west,north,east",
        "boundary_available": boundary is not None,
        "boundary_source_urls": [f"https://www.openstreetmap.org/relation/{relation['id']}" for relation in boundary_relations],
        "boundary_wikidata": "Q1520", "source_urls": source_urls,
        "attempted_source_urls": list(OVERPASS_ENDPOINTS), "source_license": "ODbL-1.0",
        "attribution": "© OpenStreetMap contributors", "license_url": "https://www.openstreetmap.org/copyright",
        "cached": {"boundary": boundary_cached, "pois": places_cached}, "stale_cache": boundary_stale or places_stale,
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "source_retrieved_at": {key: response["retrieved_at"] for key, response in (("boundary", boundary_response), ("pois", places_response)) if response},
        "elapsed_seconds": round(time.monotonic() - started, 3), "errors": errors,
        "notes": ["Uncapped named OSM nodes, ways and relations in the boundary envelope; clip to boundary during normalization.",
                  "OSM has no ratings; ratings remain null. Missing descriptions and other facts remain null."]
    }
    if boundary is None:
        report["notes"].append("Astana administrative multipolygon unavailable; using explicit bbox or airport-inclusive fallback.")
    # Never replace a previous successful candidates export with source-outage data.
    if places_response:
        _atomic_json(raw_dir / "candidates.json", pois)
    if boundary is not None:
        _atomic_json(raw_dir / "boundary.geojson", boundary)
    _atomic_json(raw_dir / "report.json", report)
    return {"pois": pois, "boundary": boundary, "report": report}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw/osm"))
    parser.add_argument("--bbox", type=float, nargs=4, metavar=("SOUTH", "WEST", "NORTH", "EAST"))
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--pbf", type=Path, help="Use a complete local OSM/PBF regional extract instead of Overpass")
    parser.add_argument("--download-pbf", action="store_true", help="Download the public Kazakhstan extract, cache it and collect locally")
    args = parser.parse_args(argv)
    bbox = tuple(args.bbox) if args.bbox else None
    local_path = download_extract(args.raw_dir, args.refresh) if args.download_pbf else args.pbf
    result = collect_file(local_path, args.raw_dir, bbox, args.refresh) if local_path else collect(args.raw_dir, bbox, args.refresh)
    print(json.dumps(result["report"], ensure_ascii=False, indent=2))
    return 1 if result["report"]["status"] == "unavailable" else 0


if __name__ == "__main__":
    raise SystemExit(main())

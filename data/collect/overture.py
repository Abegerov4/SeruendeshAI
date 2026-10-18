"""Uncapped, bbox-filtered Overture Places collection for Astana.

Run with ``.venv/bin/python -m data.collect.overture``. Public bbox arguments
use (south, west, north, east); the Overture client uses (west, south, east,
north). The parent pipeline clips these candidates to the city polygon.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import html
import json
import math
from pathlib import Path
import re
import sys
import time
from urllib.parse import quote


DEFAULT_BBOX = (50.9, 71.0, 51.4, 71.9)
NORMALIZATION_VERSION = 3
STAC_URL = "https://stac.overturemaps.org/catalog.json"
LICENSE_URL = "https://docs.overturemaps.org/attribution/"
CLOSED_STATUSES = {"closed", "permanently_closed", "closed_permanently", "temporarily_closed"}

# Source-specific terms published in the official Places attribution section.
# The downloaded licensing document is cached alongside each release subset.
SOURCE_LICENSES = {
    "meta": "CDLA-Permissive-2.0",
    "microsoft": "CDLA-Permissive-2.0",
    "pinmeto": "CDLA-Permissive-2.0",
    "krick": "CDLA-Permissive-2.0",
    "renderseo": "CDLA-Permissive-2.0",
    "dac": "CDLA-Permissive-2.0",
    "brightquery": "CDLA-Permissive-2.0",
    "foursquare": "Apache-2.0",
    "alltheplaces": "CC0-1.0",
}

CATEGORY_ALIASES = {
    "cafe": {"cafe", "coffee_shop", "tea_room", "tea_house", "coffeehouse", "internet_cafe"},
    "restaurant": {"restaurant", "casual_eatery", "fast_food", "food_court", "diner", "pizzeria", "eatery"},
    "bar": {"bar", "pub", "cocktail_bar", "beer_bar", "wine_bar", "brewpub"},
    "nightlife": {"nightclub", "night_club", "dance_club", "nightlife", "dance_hall"},
    "museum": {"museum", "art_museum", "history_museum", "science_museum"},
    "gallery": {"gallery", "art_gallery"},
    "theatre": {"theatre", "theater", "performing_arts_theater", "performing_arts_theatre", "opera_house", "concert_hall"},
    "cinema": {"cinema", "movie_theater", "movie_theatre", "drive_in_movie_theater"},
    "park": {"park", "city_park", "urban_park", "national_park", "botanical_garden", "garden", "nature_reserve"},
    "viewpoint": {"viewpoint", "scenic_lookout", "observation_deck", "lookout"},
    "monument": {"monument", "memorial", "statue", "historic_monument"},
    "attraction": {"attraction", "tourist_attraction", "landmark", "historical_landmark", "historic_site", "zoo", "aquarium", "amusement_park", "theme_park", "ferris_wheel"},
    "playground": {"playground", "children_playground", "indoor_playground"},
    "mall": {"mall", "shopping_mall", "shopping_center", "shopping_centre"},
    "library": {"library", "public_library"},
    "coworking": {"coworking", "coworking_space", "co_working_space"},
    "sport": {"sport", "sports", "sports_center", "sports_centre", "sports_club", "fitness_center", "fitness_centre", "gym", "stadium", "swimming_pool", "ice_rink", "tennis_court", "soccer_field", "golf_course", "bowling_alley", "recreation_center"},
}
CATEGORY_LOOKUP = {alias: category for category, aliases in CATEGORY_ALIASES.items() for alias in aliases}


def _string(value):
    return value.strip() if isinstance(value, str) and value.strip() else None


def _taxonomy_tokens(row):
    tokens = []
    taxonomy = row.get("taxonomy") or {}
    legacy = row.get("categories") or {}
    for value in (taxonomy.get("primary"), row.get("basic_category"), legacy.get("primary")):
        if _string(value):
            tokens.append(value)
    for key in ("hierarchy", "alternate", "alternates"):
        for value in taxonomy.get(key) or []:
            if _string(value):
                tokens.append(value)
    for value in legacy.get("alternate") or []:
        if _string(value):
            tokens.append(value)
    return list(dict.fromkeys(tokens))


def _category(tokens):
    for token in tokens:
        if token in CATEGORY_LOOKUP:
            return CATEGORY_LOOKUP[token]
        if token.endswith("_restaurant"):
            return "restaurant"
    return "other"


def _source_license(sources, licenses):
    found = set()
    for source in sources:
        dataset = re.sub(r"[^a-z0-9]", "", str(source.get("dataset", "")).lower())
        # Current releases publish the exact SPDX licence on every source,
        # including Overture's separately licensed derived confidence value.
        license_name = _string(source.get("license")) or licenses.get(dataset)
        if not license_name:
            return None
        found.add(license_name)
    return " AND ".join(sorted(found)) or None


def normalize_place(row: dict, release: str, licenses: dict | None = None) -> dict | None:
    """Preserve source facts; exclude only closed, unnamed or invalid places."""
    names = row.get("names") or {}
    name = _string(names.get("primary"))
    identifier = _string(row.get("id"))
    if not name or not identifier or row.get("operating_status") in CLOSED_STATUSES:
        return None
    from shapely import from_wkb
    from shapely.errors import GEOSException
    from shapely.geometry import shape

    try:
        raw_geometry = row.get("geometry")
        geometry = shape(raw_geometry) if isinstance(raw_geometry, dict) else from_wkb(raw_geometry)
        if geometry is None or geometry.geom_type != "Point" or geometry.is_empty:
            return None
        lon, lat = geometry.x, geometry.y
        if not math.isfinite(lat) or not math.isfinite(lon) or not (-90 <= lat <= 90 and -180 <= lon <= 180):
            return None
    except (TypeError, ValueError, GEOSException):
        return None
    common = names.get("common") or {}
    if isinstance(common, list):
        common = dict(common)
    tokens = _taxonomy_tokens(row)
    category = _category(tokens)
    quality_flags = ["source_classification_unverified"]
    primary_taxonomy = ((row.get("taxonomy") or {}).get("primary")
                        or (row.get("categories") or {}).get("primary") or row.get("basic_category"))
    name_prefix = name.lstrip(" \"'«»“”„")
    explicit_housing = re.match(r"^(?:жк\b|жилой\s+комплекс\b|residential\s+complex\b)", name_prefix, re.IGNORECASE)
    explicit_parking = re.search(r"\b(?:парковочное\s+пространство|парковка|паркинг|parking|автотұрақ)\b", name, re.IGNORECASE)
    if (primary_taxonomy == "historic_site" and explicit_housing) or (category == "park" and explicit_parking):
        category = "other"
        quality_flags.append("upstream_category_conflict")
    sources = row.get("sources") or []
    addresses = row.get("addresses") or []
    address = _string(addresses[0].get("freeform")) if addresses else None
    description = _string(row.get("description"))
    raw_tags = {key: value for key, value in row.items() if key != "geometry"}
    collection_url = f"https://stac.overturemaps.org/{release}/places/place/collection.json"
    return {
        "id": f"overture:{identifier}",
        "name": name,
        "name_en": _string(common.get("en")),
        "name_kk": _string(common.get("kk")),
        "lat": lat,
        "lon": lon,
        "category": category,
        "quality_flags": quality_flags,
        "tags": tokens,
        "raw_tags": raw_tags,
        "raw_taxonomy": {key: row.get(key) for key in ("basic_category", "taxonomy", "categories")},
        "description": description,
        "description_source": None,
        "description_source_url": collection_url if description else None,
        "address": address,
        "opening_hours": _string(row.get("opening_hours")),
        "phone": next((phone for phone in row.get("phones") or [] if _string(phone)), None),
        "website": next((url for url in row.get("websites") or [] if isinstance(url, str) and url.startswith(("https://", "http://"))), None),
        "rating": None,
        "rating_count": None,
        "wheelchair": None,
        "kid_friendly": None,
        "source": "overture",
        "source_url": f"{collection_url}#gers_id={quote(identifier)}",
        "source_license": _source_license(sources, SOURCE_LICENSES if licenses is None else licenses),
        "sources": sources,
        "source_updated_at": next((_string(source.get("update_time")) for source in sources
                                   if source.get("property") == "" and _string(source.get("update_time"))), None),
        "release": release,
        "source_release": release,
        "source_license_url": LICENSE_URL,
        "updated_at": release[:10],
    }


def _json_write(path: Path, value):
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    temporary.replace(path)


def _download_subset(path: Path, bbox: tuple) -> dict:
    """Resolve live STAC then stream spatially filtered cloud GeoParquet."""
    import httpx
    import pyarrow.parquet as pq
    from overturemaps.core import record_batch_reader

    print("Overture: resolving latest official STAC release and licensing", file=sys.stderr, flush=True)
    transport = httpx.HTTPTransport(retries=2)
    path.parent.mkdir(parents=True, exist_ok=True)
    cache_paths = [path.parent / name for name in ("stac_catalog.json", "stac_collection.json", "licensing.html")]
    metadata_cache_used, metadata_errors = False, []
    try:
        with httpx.Client(transport=transport, timeout=60, follow_redirects=True,
                          headers={"User-Agent": "AstanaWalkAI-POICollector/1.0"}) as client:
            response = client.get(STAC_URL)
            response.raise_for_status()
            catalog = response.json()
            release = catalog["latest"]
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}\.\d+", release):
                raise ValueError(f"Unexpected Overture release identifier: {release!r}")
            collection_url = f"https://stac.overturemaps.org/{release}/places/place/collection.json"
            response = client.get(collection_url)
            response.raise_for_status()
            collection = response.json()
            license_url = next((link["href"] for link in collection.get("links", []) if link.get("rel") == "license"), LICENSE_URL)
            response = client.get(license_url)
            response.raise_for_status()
            licensing_html = response.text
    except httpx.HTTPError as error:
        # A short DNS outage must not discard a release resolved earlier today.
        # Preserve snapshot mtimes so repeated failures cannot renew old metadata.
        if not all(item.exists() and time.time() - item.stat().st_mtime < 86400 for item in cache_paths):
            raise
        catalog = json.loads(cache_paths[0].read_text())
        collection = json.loads(cache_paths[1].read_text())
        licensing_html = cache_paths[2].read_text()
        release = catalog["latest"]
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}\.\d+", release) or release not in collection.get("partition:glob", ""):
            raise ValueError("Cached STAC metadata does not identify one consistent release") from error
        collection_url = f"https://stac.overturemaps.org/{release}/places/place/collection.json"
        license_url = next((link["href"] for link in collection.get("links", []) if link.get("rel") == "license"), LICENSE_URL)
        metadata_cache_used = True
        metadata_errors.append(f"{type(error).__name__}: {error}")
        print(f"Overture: using recent verified {release} metadata after {type(error).__name__}", file=sys.stderr, flush=True)
    if not metadata_cache_used:
        _json_write(cache_paths[0], catalog)
        _json_write(cache_paths[1], collection)
        cache_paths[2].write_text(licensing_html, encoding="utf-8")
    # Confirm the published document still contains each source and licence
    # before using the documented mapping. Unknown new sources stay null.
    text = html.unescape(re.sub(r"<[^>]+>", " ", licensing_html))
    text = re.sub(r"\s+", " ", text)
    licenses = {}
    for dataset, license_name in SOURCE_LICENSES.items():
        label = {"CDLA-Permissive-2.0": "CDLA Permissive 2.0", "Apache-2.0": "Apache 2.0", "CC0-1.0": "CC0 1.0"}[license_name]
        match = re.search(r"Data from\s+" + dataset + r"\b(.*?)(?=Data from|Transportation|$)", text, re.IGNORECASE)
        if match and label in match.group(0):
            licenses[dataset] = license_name
    south, west, north, east = bbox
    print(f"Overture {release}: streaming bbox {bbox} (STAC + row-group filters; no record cap)", file=sys.stderr, flush=True)
    reader = record_batch_reader("place", bbox=(west, south, east, north), release=release,
                                 stac=True, connect_timeout=30, request_timeout=120)
    if reader is None:
        raise RuntimeError("Overture client did not return a spatial subset reader")
    total = 0
    with pq.ParquetWriter(path, reader.schema) as writer:
        for batch in reader:
            writer.write_batch(batch)
            total += batch.num_rows
            print(f"Overture downloaded {total:,} bbox rows", file=sys.stderr, flush=True)
    return {
        "release": release,
        "source_urls": [STAC_URL, collection_url, f"https://stac.overturemaps.org/{release}/collections.parquet", collection.get("partition:glob"), license_url],
        "release_license": collection.get("license"),
        "source_licenses": licenses,
        "downloaded_rows": total,
        "metadata_cache_used": metadata_cache_used,
        "metadata_snapshot_at": datetime.fromtimestamp(cache_paths[0].stat().st_mtime, timezone.utc).isoformat(),
        "metadata_errors": metadata_errors,
        "download_method": "overturemaps.record_batch_reader(stac=True, bbox=...)",
    }


def collect(raw_dir: Path, bbox: tuple | None = None, refresh: bool = False) -> dict:
    """Collect all named non-closed places, atomically caching data and report."""
    import pyarrow.parquet as pq

    bbox = tuple(DEFAULT_BBOX if bbox is None else bbox)
    if len(bbox) != 4 or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in bbox):
        raise ValueError("bbox must contain finite south, west, north, east coordinates")
    south, west, north, east = bbox
    if not (-90 <= south < north <= 90 and -180 <= west < east <= 180):
        raise ValueError("Invalid bbox: expected south < north and west < east within WGS84")
    folder = Path(raw_dir)
    # Accept the orchestrator's source-specific directory and a raw-data root.
    if folder.name != "overture":
        folder = folder / "overture"
    folder.mkdir(parents=True, exist_ok=True)
    candidates_path, report_path = folder / "candidates.json", folder / "report.json"
    previous = None
    if candidates_path.exists() and report_path.exists():
        previous = {"pois": json.loads(candidates_path.read_text()), "report": json.loads(report_path.read_text())}
        if not refresh and tuple(previous["report"].get("bbox", [])) == bbox and previous["report"].get("status") in {"ok", "stale_cache"} and previous["report"].get("normalization_version") == NORMALIZATION_VERSION:
            return previous
    temporary_subset = folder / "subset.download.parquet"
    try:
        reprocess_cache = (not refresh and previous is not None
                           and tuple(previous["report"].get("bbox", [])) == bbox
                           and (folder / "subset.parquet").exists())
        if reprocess_cache:
            metadata_keys = ("release", "source_urls", "release_license", "source_licenses", "downloaded_rows",
                             "metadata_cache_used", "metadata_snapshot_at", "metadata_errors", "download_method")
            metadata = {key: value for key, value in previous["report"].items() if key in metadata_keys}
            subset = folder / "subset.parquet"
        else:
            metadata = _download_subset(temporary_subset, bbox)
            subset = temporary_subset
        release = metadata["release"]
        source_collected_at = (previous["report"]["collected_at"] if reprocess_cache
                               else datetime.now(timezone.utc).isoformat())
        counts = Counter({"downloaded_rows": 0, "closed_excluded": 0, "unnamed_excluded": 0,
                          "invalid_excluded": 0, "outside_bbox_excluded": 0, "candidates": 0})
        pois = []
        source_counts, category_counts = Counter(), Counter()
        status_counts, license_counts = Counter(), Counter()
        for batch in pq.ParquetFile(subset).iter_batches():
            for row in batch.to_pylist():
                counts["downloaded_rows"] += 1
                status_counts[str(row.get("operating_status") or "unknown")] += 1
                if row.get("operating_status") in CLOSED_STATUSES:
                    counts["closed_excluded"] += 1
                    continue
                if not _string((row.get("names") or {}).get("primary")):
                    counts["unnamed_excluded"] += 1
                    continue
                poi = normalize_place(row, release, metadata.get("source_licenses"))
                if poi is None:
                    counts["invalid_excluded"] += 1
                    continue
                if not (south <= poi["lat"] <= north and west <= poi["lon"] <= east):
                    counts["outside_bbox_excluded"] += 1
                    continue
                poi["collected_at"] = source_collected_at
                poi["source_records"] = [{
                    "id": poi["id"], "source": "overture", "source_url": poi["source_url"],
                    "license": poi["source_license"], "release": release,
                    "collected_at": source_collected_at, "source_updated_at": poi["source_updated_at"],
                    "upstream_sources": poi["sources"], "raw_taxonomy": poi["raw_taxonomy"],
                }]
                pois.append(poi)
                category_counts[poi["category"]] += 1
                license_counts[poi["source_license"] or "unknown"] += 1
                for source in poi["sources"]:
                    source_counts[source.get("dataset") or "unknown"] += 1
        pois.sort(key=lambda poi: poi["id"])
        counts["candidates"] = len(pois)
        counts["original_descriptions"] = sum(bool(poi["description"]) for poi in pois)
        counts["upstream_category_conflicts"] = sum("upstream_category_conflict" in poi["quality_flags"] for poi in pois)
        normalized_at = datetime.now(timezone.utc).isoformat()
        report = {
            "status": "ok", "bbox": list(bbox), "bbox_order": "south,west,north,east",
            "collected_at": source_collected_at,
            "normalized_at": normalized_at, "normalization_version": NORMALIZATION_VERSION,
            "normalization_rebuilt_from_cache": bool(reprocess_cache),
            **metadata, "counts": dict(counts), "category_counts": dict(category_counts),
            "source_counts": dict(source_counts), "operating_status_counts": dict(status_counts),
            "license_counts": dict(license_counts), "errors": [],
            "record_cap": None, "city_boundary_clip": "performed by parent collection pipeline",
        }
        if not reprocess_cache:
            temporary_subset.replace(folder / "subset.parquet")
        _json_write(candidates_path, pois)
        _json_write(report_path, report)
        return {"pois": pois, "report": report}
    except Exception as error:
        temporary_subset.unlink(missing_ok=True)
        same_bbox = previous is not None and tuple(previous["report"].get("bbox", [])) == bbox
        report = dict(previous["report"]) if same_bbox else {"bbox": list(bbox), "counts": {"candidates": 0}, "source_urls": [STAC_URL], "release": None}
        report.update(status="stale_cache" if same_bbox else "failed", errors=[f"{type(error).__name__}: {error}"], attempted_at=datetime.now(timezone.utc).isoformat())
        _json_write(folder / "last_attempt.json", report)
        return {"pois": previous["pois"] if same_bbox else [], "report": report}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw/overture"))
    parser.add_argument("--bbox", type=float, nargs=4, metavar=("SOUTH", "WEST", "NORTH", "EAST"))
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()
    result = collect(args.raw_dir, args.bbox, args.refresh)
    print(json.dumps(result["report"], ensure_ascii=False, indent=2))
    return 0 if result["report"]["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())

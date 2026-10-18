"""Normalize source facts and conservatively merge physical POI duplicates."""
from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime
from math import asin, cos, floor, isfinite, radians, sin, sqrt
import json
import re
import unicodedata
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from data.collect.identity import addresses_compatible, same_name


CATEGORIES = {"cafe", "restaurant", "bar", "nightlife", "museum", "gallery", "theatre",
              "cinema", "park", "viewpoint", "monument", "attraction", "playground", "mall",
              "library", "coworking", "sport", "other"}
CATEGORY_RU = {"cafe": "Кафе", "restaurant": "Ресторан", "bar": "Бар", "nightlife": "Ночное заведение",
               "museum": "Музей", "gallery": "Галерея", "theatre": "Театр", "cinema": "Кинотеатр",
               "park": "Парк или сад", "viewpoint": "Смотровая площадка", "monument": "Памятник",
               "attraction": "Достопримечательность", "playground": "Детская площадка", "mall": "Торговый центр",
               "library": "Библиотека", "coworking": "Коворкинг", "sport": "Спортивный объект", "other": "Место"}
SOURCE_PRIORITY = {"osm": 100, "wikidata": 90, "wikipedia": 85, "marwin": 80, "dodo": 80,
                   "astana_library": 80, "mega": 80, "citypass": 75, "overture": 60, "geonames": 55}
FALLBACK_BBOX = (50.8, 71.0, 51.4, 71.9)  # south, west, north, east; full administrative extent
OPTIONAL_TEXT = ("name_en", "name_kk", "address", "opening_hours", "phone")
DESCRIPTION_SOURCES = {"osm", "wikipedia", "website", "llm_generated"}


def _text(value):
    if not isinstance(value, str):
        return None
    value = re.sub(r"\s+", " ", "".join(c for c in value if c.isprintable() or c.isspace())).strip()
    return value or None


def _url(value):
    value = _text(value)
    if not value or any(c.isspace() for c in value):
        return None
    try:
        parsed = urlsplit(value)
        return value if parsed.scheme.lower() in {"https", "http"} and parsed.hostname else None
    except ValueError:
        return None


def _name_key(value):
    return re.sub(r"[^\w]+", "", unicodedata.normalize("NFKC", value).casefold().replace("ё", "е"))


def _distance(a, b):
    p1, p2 = radians(a["lat"]), radians(b["lat"])
    term = sin((p2-p1)/2)**2 + cos(p1)*cos(p2)*sin(radians(b["lon"]-a["lon"])/2)**2
    return 12_742_017.6 * asin(sqrt(min(1.0, term)))


def _cell(poi):
    return floor(poi["lat"] / .001), floor(poi["lon"] / .0015)


def _geometry(boundary):
    if boundary and boundary.get("type") == "Feature":
        return boundary["geometry"]
    if boundary and boundary.get("type") == "FeatureCollection":
        return {"type": "GeometryCollection", "geometries": [f["geometry"] for f in boundary["features"]]}
    return boundary


def _prepare_boundary(boundary):
    if not boundary:
        return None
    from shapely.geometry import shape
    geometry = shape(_geometry(boundary))
    if geometry.is_empty or not geometry.is_valid:
        raise ValueError("Astana boundary must be a valid nonempty geometry")
    return geometry


def _closed(raw):
    if raw.get("operating_status") in {"permanently_closed", "closed", "closed_permanently"}:
        return True
    tags = raw.get("raw_tags") or {}
    return any(tags.get(k) in {"yes", "true", "1"} for k in ("disused", "abandoned", "demolished", "removed"))


def _record(raw):
    return {"id": raw["id"], "source": raw["source"], "source_url": raw.get("source_url"),
            "license": raw.get("source_license"), "source_updated_at": raw.get("source_updated_at"),
            "collected_at": raw.get("collected_at"),
            **({"release": raw["release"]} if raw.get("release") else {}),
            **{key: deepcopy(raw[key]) for key in ("coordinate_source_id", "coordinate_source_url", "coordinate_match_verified",
                                                  "coordinate_match_method", "coordinate_anchor_ids", "coordinate_match_anchor_ids", "quality_review_notes") if raw.get(key)}}


def _normalize_one(raw, collected_at):
    if not isinstance(raw, dict) or not _text(raw.get("id")) or not _text(raw.get("name")):
        return None, "missing_id_or_name"
    for field in ("lat", "lon"):
        value = raw.get(field)
        if isinstance(value, bool) or not isinstance(value, (float, int)) or not isfinite(value):
            return None, "invalid_coordinates"
    south, west, north, east = FALLBACK_BBOX
    if not (south <= raw["lat"] <= north and west <= raw["lon"] <= east):
        return None, "outside_collection_envelope"
    if _closed(raw):
        return None, "closed_or_disused"
    source = _text(raw.get("source")) or "unknown"
    poi = {"id": _text(raw["id"]), "name": _text(raw["name"]),
           "lat": float(raw["lat"]), "lon": float(raw["lon"]),
           "category": raw.get("category") if raw.get("category") in CATEGORIES else "other",
           "source": source, "source_url": _url(raw.get("source_url")), "updated_at": collected_at,
           "collected_at": collected_at, "source_updated_at": _text(raw.get("source_updated_at"))}
    for field in OPTIONAL_TEXT:
        poi[field] = _text(raw.get(field))
    poi["website"] = _url(raw.get("website"))
    poi["wheelchair"] = raw.get("wheelchair") if raw.get("wheelchair") in {"yes", "limited", "no"} else None
    poi["kid_friendly"] = raw.get("kid_friendly") if isinstance(raw.get("kid_friendly"), bool) else None
    if poi["category"] == "playground" and poi["kid_friendly"] is None:
        poi["kid_friendly"] = True
        poi["kid_friendly_basis"] = "category:playground"
    # Popularity, Wikimedia sitelinks and Overture confidence are not visitor ratings.
    rating = raw.get("rating")
    genuine_rating = raw.get("rating_source") and isinstance(rating, (int, float)) and not isinstance(rating, bool)
    poi["rating"] = float(rating) if genuine_rating and isfinite(rating) and 0 <= rating <= 5 else None
    count = raw.get("rating_count")
    poi["rating_count"] = count if poi["rating"] is not None and isinstance(count, int) and count >= 0 else None
    tags = raw.get("tags") or []
    if isinstance(tags, str):
        tags = [tags]
    poi["tags"] = sorted({_text(x) for x in tags if _text(x)})
    poi["raw_tags"] = deepcopy(raw.get("raw_tags") or {})
    poi["source_records"] = deepcopy(raw.get("source_records") or [_record({**raw, "source": source})])
    for key in ("wikidata_ids", "wikidata_descriptions", "description_attribution", "source_refs", "aliases", "raw_taxonomy",
                "wikipedia_attribution", "description_url", "description_license", "coordinate_source_id", "coordinate_source_url"):
        if raw.get(key):
            poi[key] = deepcopy(raw[key])
    for key in ("quality_review_notes", "skip_wikimedia_enrichment", "suppress_cuisine_text", "coordinate_match_verified", "coordinate_match_method", "coordinate_match_anchor_ids", "verified_identity_parent_id"):
        if raw.get(key):
            poi[key] = deepcopy(raw[key])
    if raw.get("quality_flags"):
        poi["quality_flags"] = list(raw["quality_flags"])
    aliases = list(poi.get("aliases", [])) if isinstance(poi.get("aliases", []), list) else []
    if source == "osm":
        for key in ("name:ru", "name:kk", "name:en", "int_name", "official_name", "alt_name", "short_name"):
            if isinstance(poi["raw_tags"].get(key), str):
                aliases.extend(value.strip() for value in poi["raw_tags"][key].split(";") if value.strip())
    if aliases:
        poi["aliases"] = sorted(set(aliases))
    description = _text(raw.get("description"))
    poi["description"] = description
    poi["description_source"] = raw.get("description_source") if description else None
    if description and poi["description_source"] not in DESCRIPTION_SOURCES:
        poi["description_source"] = "osm" if source == "osm" else "website"
    poi["description_kind"] = raw.get("description_kind", "source") if description else None
    if raw.get("description_source_detail"):
        poi["description_source_detail"] = raw["description_source_detail"]
    return poi, None


def _name_keys(poi):
    values = [poi.get(k) for k in ("name", "name_en", "name_kk")]
    aliases = poi.get("aliases", [])
    values += aliases if isinstance(aliases, list) else []
    return {_name_key(v) for v in values if isinstance(v, str) and v.strip()}


def _same_place(a, b):
    if a["id"] == b["id"]:
        return True
    if _distance(a, b) < 50:
        for reviewed, parent in ((a, b), (b, a)):
            parent_ids = {parent["id"], *(r["id"] for r in parent.get("source_records", []))}
            if reviewed.get("verified_identity_parent_id") in parent_ids:
                return True
    if _distance(a, b) < 1:
        for fact, parent in ((a, b), (b, a)):
            if fact.get("coordinate_match_verified") and fact.get("coordinate_match_method") in {"street_address", "mall_scope"}:
                parent_ids = {parent["id"], *(r["id"] for r in parent.get("source_records", []))}
                if fact.get("coordinate_source_id") in parent_ids:
                    return True
    if _distance(a, b) >= 50 or not same_name(a, b):
        return False
    left, right = a.get("raw_tags", {}), b.get("raw_tags", {})
    if left.get("level") and right.get("level") and left["level"] != right["level"]:
        return False
    if not addresses_compatible(a.get("address"), b.get("address")):
        return False
    culture = {"monument", "viewpoint", "attraction"}
    return a["category"] == b["category"] or "other" in {a["category"], b["category"]} or {a["category"], b["category"]} <= culture


def _merge(primary, secondary):
    if not primary.get("description") and secondary.get("description"):
        for key in ("description", "description_source", "description_kind", "description_attribution", "description_source_detail",
                    "description_url", "description_license", "wikipedia_attribution"):
            if key in secondary:
                primary[key] = deepcopy(secondary[key])
    for key in (*OPTIONAL_TEXT, "website", "wheelchair", "kid_friendly", "rating", "rating_count"):
        if primary.get(key) is None and secondary.get(key) is not None:
            primary[key] = secondary[key]
        elif primary.get(key) is not None and secondary.get(key) is not None and primary[key] != secondary[key]:
            if key in {"opening_hours", "wheelchair", "kid_friendly", "address"}:
                primary.setdefault("field_conflicts", []).append({"field": key, "value": secondary[key], "source_id": secondary["id"]})
    if primary["category"] == "other" and secondary["category"] != "other":
        primary["category"] = secondary["category"]
    primary["tags"] = sorted(set(primary["tags"]) | set(secondary["tags"]))
    for key, value in secondary.get("raw_tags", {}).items():
        primary["raw_tags"].setdefault(key, value)
    records = {r["id"]: r for r in primary["source_records"]}
    for record in secondary["source_records"]:
        records.setdefault(record["id"], record)
    primary["source_records"] = sorted(records.values(), key=lambda r: r["id"])
    for field in ("wikidata_ids", "aliases"):
        values = [*primary.get(field, []), *secondary.get(field, [])]
        if values:
            primary[field] = sorted(set(values))
    if secondary.get("wikidata_descriptions"):
        primary.setdefault("wikidata_descriptions", {}).update(secondary["wikidata_descriptions"])
    if secondary.get("source_refs"):
        refs = primary.setdefault("source_refs", [])
        for ref in secondary["source_refs"]:
            if ref not in refs:
                refs.append(deepcopy(ref))
    if secondary.get("quality_flags"):
        primary["quality_flags"] = sorted(set(primary.get("quality_flags", [])) | set(secondary["quality_flags"]))
    if secondary.get("quality_review_notes"):
        notes = primary.setdefault("quality_review_notes", [])
        for note in secondary["quality_review_notes"]:
            if note not in notes:
                notes.append(deepcopy(note))


def _describe(poi):
    if poi.get("description"):
        return
    # Reproducible, factual fallback. This is explicitly not a source-authored review or LLM output.
    text = f'{CATEGORY_RU[poi["category"]]} «{poi["name"]}» в Астане.'
    if poi.get("address"):
        text += f' Адрес из источника: {poi["address"]}.'
    raw = poi.get("raw_tags", {})
    attributes = []
    if raw.get("cuisine") and not poi.get("suppress_cuisine_text"):
        attributes.append("кухня: " + str(raw["cuisine"]).replace(";", ", "))
    if raw.get("sport"):
        attributes.append("вид спорта: " + str(raw["sport"]).replace(";", ", "))
    if raw.get("shop"):
        attributes.append("тип магазина: " + str(raw["shop"]))
    if poi["category"] == "other":
        for field in ("amenity", "public_transport", "office", "tourism", "healthcare", "natural", "man_made", "basic_category"):
            if isinstance(raw.get(field), str):
                attributes.append(field + ": " + raw[field])
    if attributes:
        text += " Сведения источника: " + "; ".join(attributes) + "."
    poi["description"] = text
    poi["description_source"] = "osm" if poi["source"] == "osm" else "website"
    poi["description_kind"] = "structured_template"
    poi["description_source_detail"] = "deterministic text from attributed structured fields; no LLM used"


def normalize_candidates(candidates: list[dict], boundary: dict | None = None,
                         collected_at: str | None = None) -> tuple[list[dict], dict]:
    """Return all valid city POIs and a quality report; never cap the record count."""
    collected_at = collected_at or datetime.now(ZoneInfo("Asia/Almaty")).date().isoformat()
    geometry = _prepare_boundary(boundary)
    rejected = Counter()
    normalized = []
    for candidate in candidates:
        poi, reason = _normalize_one(candidate, collected_at)
        if reason:
            rejected[reason] += 1
            continue
        if geometry is not None:
            from shapely.geometry import Point
            if not geometry.covers(Point(poi["lon"], poi["lat"])):
                rejected["outside_city_boundary"] += 1
                continue
        normalized.append(poi)
    normalized.sort(key=lambda p: (-SOURCE_PRIORITY.get(p["source"], 70),
                                  -sum(v is not None for v in p.values()),
                                  p["id"], json.dumps(p, ensure_ascii=False, sort_keys=True)))
    results, grid, identities = [], defaultdict(list), {}
    merged = 0
    for poi in normalized:
        match = identities.get(poi["id"])
        x, y = _cell(poi)
        if match is None:
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for idx in grid.get((x+dx, y+dy), []):
                        if _same_place(results[idx], poi):
                            match = idx
                            break
                    if match is not None:
                        break
                if match is not None:
                    break
        if match is None:
            identities[poi["id"]] = len(results)
            grid[(x, y)].append(len(results))
            results.append(poi)
        else:
            _merge(results[match], poi)
            identities[poi["id"]] = match
            merged += 1
    for poi in results:
        _describe(poi)
        poi["source_records"] = sorted(poi["source_records"], key=lambda r: r["id"])
        if poi.get("field_conflicts"):
            poi["field_conflicts"] = sorted(poi["field_conflicts"], key=lambda r: json.dumps(r, sort_keys=True))
    results.sort(key=lambda p: p["id"])
    report = {"input_count": len(candidates), "output_count": len(results), "merged_count": merged,
              "rejected_count": sum(rejected.values()), "rejections": dict(sorted(rejected.items())),
              "boundary_mode": "administrative_polygon" if geometry is not None else "broad_bbox_only",
              "categories": dict(sorted(Counter(p["category"] for p in results).items())),
              "primary_sources": dict(sorted(Counter(p["source"] for p in results).items())),
              "source_description_count": sum(p["description_kind"] == "source" for p in results),
              "template_description_count": sum(p["description_kind"] == "structured_template" for p in results),
              "unknown_opening_hours": sum(p["opening_hours"] is None for p in results),
              "collected_at": collected_at}
    return results, report

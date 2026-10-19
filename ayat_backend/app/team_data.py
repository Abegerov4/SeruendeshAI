"""Read the team's complete canonical snapshot without rewriting any data files.

The API receives only explicitly classified leisure destinations. Origin-only
records remain in the gazetteer; explicit lifecycle exclusions remain only in
the archive, with all source identifiers preserved. Embeddings for the older JSONL view
are deliberately incompatible with this derived view.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from copy import deepcopy
from pathlib import Path

from ayat_backend.app.categories import CATEGORIES
from ayat_backend.app.features import features_from_osm
from ayat_backend.app.textnorm import fold

_COARSE_CATEGORY = {"attraction": "landmark", "sport": "active", "nightlife": "nightclub"}
_NEGATIVE_FEATURES = {
    "outdoor_seating": "outdoor_seating", "kids_area": "kids_area", "changing_table": "changing_table",
    "takeaway": "takeaway", "air_conditioning": "air_conditioning", "toilets": "toilets", "indoor": "indoor",
}
_CONFLICT_FEATURES = {
    "internet_access": "wifi", "wheelchair": "wheelchair", "lit": "lit", "fee": "free",
    **_NEGATIVE_FEATURES, "diet:vegetarian": "vegetarian", "smoking": "no_smoking",
    "power_supply": "power_outlets", "socket": "power_outlets", "charging_station": "power_outlets",
    "opening_hours": "open_24_7", "location": "indoor",
}


from data.eligibility import (identifier_aliases as _identifier_aliases, source_ids as _source_ids,
                              review_matches, exclusion_reasons, safe_facts, evidence_for_hours)


def _names(row: dict) -> dict[str, str]:
    names = {}
    raw = row.get("raw_tags") or {}
    for lang in ("ru", "kk", "en"):
        value = row.get("name_" + lang) or raw.get("name:" + lang)
        if isinstance(value, str) and value.strip():
            names[lang] = value
    return names


def _features(row: dict, conflicts: set[str]) -> dict:
    raw = {k: v for k, v in (row.get("raw_tags") or {}).items() if isinstance(v, str)}
    features = features_from_osm(raw)
    # The upstream helper accepts internet_access=yes as Wi-Fi. The canonical
    # contract permits Wi-Fi only when attributed WLAN facts do not conflict.
    features.pop("wifi", None)
    access = {
        f["value"] for f in row.get("amenity_facts", [])
        if f.get("field") == "internet_access" and isinstance(f.get("value"), str)
        and f.get("source_id") and f.get("source_url")
    }
    if "wlan" in access and access <= {"wlan", "yes"}:
        features["wifi"] = True
    elif access == {"no"}:
        features["wifi"] = False
    for field, feature in _NEGATIVE_FEATURES.items():
        if raw.get(field) == "no":
            features[feature] = False
    if row.get("wheelchair") in ("yes", "limited", "no"):
        features["wheelchair"] = row["wheelchair"]
    for field in conflicts:
        if field in _CONFLICT_FEATURES:
            features.pop(_CONFLICT_FEATURES[field], None)
    if "conflicting_internet_access" in row.get("quality_flags", []):
        features.pop("wifi", None)
    return features


def _adapt(row: dict, category: str, source_ids: list[str], aliases: list[str], external_evidence=()) -> dict:
    conflicts = {f["field"] for f in row.get("field_conflicts", []) if f.get("field")}
    raw = row.get("raw_tags") or {}
    features = _features(row, conflicts)
    details = deepcopy(row.get("place_details") or {})
    feature_fields = {"wifi":"wifi","sockets":"power_outlets","quiet":"quiet","indoor":"indoor",
        "toilets":"toilets","changing_table":"changing_table","kids_area":"kids_area","lit":"lit",
        "terrace":"outdoor_seating","takeaway":"takeaway"}
    derived_conflicts = []
    retained = []
    for fact in details.get("facts",[]):
        key = feature_fields.get(fact["field"])
        disputed_features = {_CONFLICT_FEATURES.get(f) for f in conflicts}
        if "conflicting_internet_access" in row.get("quality_flags", []):
            disputed_features.add("wifi")
        if fact["field"] in conflicts or key and key in disputed_features:
            continue
        if key and key in features and features[key] != fact["value"]:
            features.pop(key,None)
            derived_conflicts.append({"field":fact["field"],"reason":"Supplemental and canonical source assertions disagree", "source_url":fact["source"]["url"]})
        else:
            if key:
                features[key] = fact["value"]
            retained.append(fact)
    if details:
        details["facts"] = retained
    sources = sorted({row.get("source") or "unknown", *(r.get("source") or "unknown"
                     for r in row.get("source_records", [])), *(r.get("source") or "unknown"
                     for r in row.get("source_refs", []))})
    opening_hours = None if "opening_hours" in conflicts else row.get("opening_hours")
    hours_meta = evidence_for_hours(row,external_evidence)
    accepted_hours = any(r.get("status") == "accepted" and r.get("field") == "opening_hours" for r in row.get("fact_reviews",[]))
    supplements = [f for f in retained if f["field"] == "opening_hours"]
    if supplements and not accepted_hours and "opening_hours" not in conflicts:
        fact = supplements[0]
        opening_hours = fact["value"]
        hours_meta.update(hours_source="reviewed branch source",hours_source_url=fact["source"]["url"],
            check_date=fact["source"]["checked_at"],hours_fact_status="attributed",hours_evidence=[fact])
    elif accepted_hours and supplements and any(f["value"] != opening_hours for f in supplements):
        details["withheld_facts"] = [f for f in supplements if f["value"] != opening_hours]
        details["facts"] = [f for f in retained if f["field"] != "opening_hours" or f["value"] == opening_hours]
    cuisine = raw.get("cuisine")
    if row.get("suppress_cuisine_text") or "cuisine" in conflicts or not isinstance(cuisine, str):
        cuisine = None
    wikidata = raw.get("wikidata")
    if not isinstance(wikidata, str) or not re.fullmatch(r"Q\d+", wikidata) \
            or "conflicting_wikimedia_link" in row.get("quality_flags", []):
        wikidata = None
    return {
        **safe_facts(row), **hours_meta, "canonical_category": row.get("canonical_category", row["category"]), "category": category,
        "canonical_opening_hours": row.get("canonical_opening_hours", row.get("opening_hours")), "opening_hours": opening_hours,
        "canonical_wheelchair": row.get("wheelchair"),
        "wheelchair": None if "wheelchair" in conflicts else row.get("wheelchair"),
        "name_auto": False, "names": _names(row), "aliases": row.get("aliases", []),
        "source_ids": source_ids, "id_aliases": aliases, "sources": sources, "features": features,
        "place_details":details,"field_conflicts":[*row.get("field_conflicts",[]),*derived_conflicts],
        "cuisine": cuisine, "brand": raw.get("brand") if isinstance(raw.get("brand"), str) else None,
        "instagram": raw.get("contact:instagram"), "wikidata": wikidata,
        "indoor": features.get("indoor"), "heritage": raw.get("heritage") == "yes", "popularity": 0.0,
    }


def load_team_snapshot(canonical_path: Path, *, quarantine_path: Path | None = None) -> tuple[list, list, dict]:
    """Return ``(recommendation_pois, gazetteer, manifest)`` from local JSON.

    ``quarantine_path=None`` applies no additional review list. Callers serving
    this repository's data should pass ``data/quarantine.json`` explicitly.
    The returned source IDs cover every canonical record, including exclusions.
    Colliding name/legacy-ID keys remain available for audit but are withheld
    from automatic gazetteer resolution and identifier alias lookup.
    """
    payload = Path(canonical_path).read_bytes()
    rows = json.loads(payload)
    if isinstance(rows, dict):
        rows = rows["pois"]
    if not isinstance(rows, list):
        raise ValueError("Canonical POI snapshot must contain a list of records")
    details_path = Path(canonical_path).parent / "place_details.json"
    if details_path.exists():
        from datetime import datetime
        from zoneinfo import ZoneInfo
        from data.place_details import load_place_details, apply_place_details
        details = load_place_details(details_path,canonical_sha256=hashlib.sha256(payload).hexdigest(),
                                    as_of=datetime.now(ZoneInfo("Asia/Almaty")).date())
        rows = apply_place_details(rows,details)
    from data.eligibility import apply_fact_reviews
    review_overlay = Path(canonical_path).parent / "fact_reviews.json"
    if review_overlay.exists():
        rows = apply_fact_reviews(rows, json.loads(review_overlay.read_bytes()),
                                  canonical_sha256=hashlib.sha256(payload).hexdigest())
    ids = [r["id"] for r in rows]
    if len(set(ids)) != len(ids):
        raise ValueError("Canonical POI identifiers must be unique")

    ids_by_row, aliases_by_row, names_by_row = {}, {}, {}
    identifier_owners, name_owners = defaultdict(set), defaultdict(set)
    for row in rows:
        canonical_id = row["id"]
        source_ids = _source_ids(row)
        aliases = set().union(*(_identifier_aliases(s) for s in source_ids))
        names = {fold(n) for n in [row["name"], *_names(row).values(), *row.get("aliases", [])]
                 if isinstance(n, str) and n.strip()}
        ids_by_row[canonical_id], aliases_by_row[canonical_id], names_by_row[canonical_id] = source_ids, aliases, names
        for alias in aliases:
            identifier_owners[alias].add(canonical_id)
        for name in names:
            name_owners[name].add(canonical_id)

    evidence_path = Path(canonical_path).parent / "field_evidence.json"
    external = json.loads(evidence_path.read_bytes()) if evidence_path.exists() else {}
    quarantine = json.loads(Path(quarantine_path).read_bytes()) if quarantine_path is not None else []
    quarantined, unmatched, ambiguous_quarantine = review_matches(rows, quarantine)

    pois, gazetteer, exclusions, archived_ids = [], [], [], []
    excluded_counts = Counter()
    for row in rows:
        canonical_id = row["id"]
        category = _COARSE_CATEGORY.get(row["category"], row["category"])
        reasons = exclusion_reasons(row, canonical_id in quarantined)
        if category not in CATEGORIES and "origin_only_category" not in reasons:
            reasons.append("origin_only_category")
        aliases = sorted(a for a in aliases_by_row[canonical_id] if len(identifier_owners[a]) == 1)
        adapted = _adapt(row, category, ids_by_row[canonical_id], aliases,
                         [e for ident in ids_by_row[canonical_id] for e in external.get(ident, [])])
        if reasons:
            exclusions.append({"id": canonical_id, "reasons": reasons,
                               **({"quarantine": quarantined[canonical_id]} if canonical_id in quarantined else {})})
            excluded_counts.update(reasons)
        else:
            pois.append(adapted)
        if "unresolved_geometry" in reasons or any(review.get("exclude_from_origins") is True for review in quarantined.get(canonical_id, [])):
            archived_ids.append(canonical_id)
            continue
        keys = {n for n in names_by_row[canonical_id] if len(name_owners[n]) == 1}
        keys.update(fold(a) for a in aliases)
        gazetteer.append({
            **adapted, "poi_id": canonical_id, "kind": "place" if reasons else "poi",
            "origin_only": bool(reasons), "keys": sorted(keys), "exclusion_reasons": reasons,
            "ambiguous_keys": sorted(n for n in names_by_row[canonical_id] if len(name_owners[n]) > 1),
        })

    source_ids = {s for source_ids in ids_by_row.values() for s in source_ids}
    preserved_ids = {s for g in gazetteer for s in g["source_ids"]} | {
        s for ident in archived_ids for s in ids_by_row[ident]}
    licenses = defaultdict(set)
    for row in rows:
        for source in row.get("source_records", []):
            if source.get("source"):
                licenses[source["source"]].add(source.get("license") or "not specified; attributed facts")
    sha256 = hashlib.sha256(payload).hexdigest()
    manifest = {
        "snapshot_kind": "canonical_team_data", "canonical_sha256": sha256, "canonical_count": len(rows),
        "adapted_count": len(pois), "poi_count": len(pois), "gazetteer_count": len(gazetteer),
        "origin_anchor_count": sum(g["origin_only"] for g in gazetteer), "preserved_canonical_ids_count": len(gazetteer)+len(archived_ids),
        "archived_canonical_ids": sorted(archived_ids), "archived_canonical_count": len(archived_ids),
        "raw_source_ids_count": len(source_ids), "preserved_source_ids_count": len(preserved_ids),
        "pois_sha": sha256, "built_at": max((r.get("collected_at") or "" for r in rows), default="") or None,
        "by_category": dict(Counter(p["category"] for p in pois)),
        "by_source": dict(Counter(s for p in pois for s in p["sources"])),
        "sources": {s: "; ".join(sorted(values)) for s, values in sorted(licenses.items())},
        "excluded_by_reason": dict(excluded_counts), "excluded_records": exclusions,
        "alias_collisions": {a: sorted(owners) for a, owners in sorted(name_owners.items()) if len(owners) > 1},
        "id_alias_collisions": {a: sorted(owners) for a, owners in sorted(identifier_owners.items()) if len(owners) > 1},
        "quarantine_unmatched_ids": sorted(unmatched), "quarantine_ambiguous_ids": ambiguous_quarantine,
        "dense_disabled": True,
        "dense_disabled_reason": "Canonical team-data view has no row-aligned embeddings; use BM25 until explicitly rebuilt.",
    }
    return pois, gazetteer, manifest

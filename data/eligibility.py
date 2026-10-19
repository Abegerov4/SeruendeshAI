"""Shared, non-destructive recommendation policy for canonical data consumers."""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
import json
import math
from pathlib import Path
import re

POLICY_VERSION = "canonical-eligibility-v1"


def identifier_aliases(identifier):
    aliases = {identifier}
    osm = re.fullmatch(r"osm:(node|way|relation)/(\d+)", identifier)
    old = re.fullmatch(r"osm:([nwr])(\d+)", identifier)
    if osm:
        aliases.add(f"osm:{osm[1][0]}{osm[2]}")
    elif old:
        aliases.add(f"osm:{ {'n': 'node', 'w': 'way', 'r': 'relation'}[old[1]]}/{old[2]}")
    elif identifier.startswith("overture:"):
        aliases.add("ov:" + identifier.removeprefix("overture:")[:16])
    elif identifier.startswith("citypass:"):
        aliases.add("cp:" + identifier.removeprefix("citypass:"))
    elif identifier.startswith("cp:"):
        aliases.add("citypass:" + identifier.removeprefix("cp:"))
    return aliases


def source_ids(row):
    return sorted({row["id"], *(r["id"] for r in row.get("source_records", []) if r.get("id"))})


def review_matches(rows, reviews):
    owners = defaultdict(set)
    for row in rows:
        for ident in source_ids(row):
            for alias in identifier_aliases(ident):
                owners[alias].add(row["id"])
    matches, unmatched, ambiguous = defaultdict(list), [], {}
    for review in reviews:
        ids = owners.get(review["id"], set())
        if not ids:
            unmatched.append(review["id"])
        if len(ids) > 1:
            ambiguous[review["id"]] = sorted(ids)
        # Ambiguous exclusions fail closed for *all* owners, never pick one.
        for ident in ids:
            matches[ident].append(review)
    return matches, sorted(unmatched), ambiguous


def exclusion_reasons(row, quarantined=False):
    reasons = []
    if any(f.get("field") in {"coordinates","lat","lon","geometry"} for f in row.get("field_conflicts", [])):
        reasons.append("unresolved_geometry")
    if row.get("category") == "other":
        reasons.append("origin_only_category")
    if quarantined:
        reasons.append("quarantine")
    flags = row.get("quality_flags", [])
    if "source_classification_unverified" in flags:
        if row.get("category") == "playground":
            reasons.append("unverified_playground")
        elif (row.get("category") in {"park", "garden"} and
              re.search(r"(?:казахстан|kazakhstan)\s*,\s*(?:казахстан|kazakhstan)$", row.get("name", ""), re.I)):
            reasons.append("suspicious_classification")
    return reasons


def load_reviews(path):
    return json.loads(Path(path).read_bytes()) if path and Path(path).exists() else []


def safe_facts(row):
    """Withhold disputed facts in the candidate view, retaining original evidence."""
    result = deepcopy(row)
    conflicts = {f["field"] for f in row.get("field_conflicts", []) if f.get("field")}
    if conflicts & {"coordinates","lat","lon","geometry"}:
        for axis in ("lat","lon"):
            result.setdefault("canonical_"+axis, row.get(axis))
            result[axis] = None
    for field in conflicts:
        if field in row:
            result["canonical_" + field] = deepcopy(row[field])
            result[field] = None
    result.setdefault("canonical_opening_hours", row.get("opening_hours"))
    result.setdefault("canonical_wheelchair", row.get("wheelchair"))
    result["classification_status"] = ("unverified" if "source_classification_unverified" in row.get("quality_flags", []) else "source_classified")
    result["eligibility_policy"] = POLICY_VERSION
    # Unlicensed narrative remains in the canonical source, never in public text.
    if row.get("description_kind") == "source" and row.get("description_license") in {None, "", "not_specified", "unknown"}:
        result["description"] = None
        result["description_publication_status"] = "held_pending_license_review"
    return result


def evidence_for_hours(row, external=()):
    evidence = [e for e in [*row.get("field_evidence", []), *external]
                if e.get("field") == "opening_hours" and e.get("value") == row.get("opening_hours")
                and e.get("source_id") and e.get("source_url")]
    evidence = sorted(evidence, key=lambda e: (e.get("review_status") != "accepted", e.get("source_id", ""), e.get("source_url", "")))
    if not row.get("opening_hours"):
        return {"hours_source": None, "hours_source_url": None, "check_date": None, "hours_evidence": []}
    selected = evidence[0] if evidence else {}
    return {"hours_source": selected.get("source"), "hours_source_id": selected.get("source_id"),
            "hours_source_url": selected.get("source_url"), "hours_acquired_at": selected.get("acquired_at") or selected.get("collected_at"),
            "hours_source_updated_at": selected.get("source_updated_at"),
            "check_date": selected.get("checked_at"), "hours_evidence": evidence,
            "hours_fact_status": "conflicting" if any(f.get("field") == "opening_hours" for f in row.get("field_conflicts", []))
                                 else "attributed_unchecked" if evidence and not selected.get("checked_at") else "attributed" if evidence else "unknown_provenance"}


def apply_fact_reviews(rows, payload, *, canonical_sha256):
    """Apply hash-bound, explicitly accepted source reviews to a derived view only.

    ``payload={schema_version:1, canonical_sha256:..., reviews:[...]}``.
    Source records/IDs remain unchanged; original fields and disputes are retained
    under ``canonical_*`` keys. Pending/rejected assertions never become facts.
    """
    from datetime import date
    from urllib.parse import urlsplit
    if payload.get("schema_version") != 1 or payload.get("canonical_sha256") != canonical_sha256:
        raise ValueError("Fact review snapshot hash/schema mismatch")
    result = deepcopy(rows)
    by_id = {r["id"]: r for r in result}
    top_fields = {"opening_hours", "wheelchair", "kid_friendly", "name_en", "name_kk", "category", "name", "aliases", "coordinates"}
    raw_fields = {"internet_access", "power_supply", "socket", "charging_station", "indoor", "entrance", "kids_area", "lit"}
    from data.collect.normalize import CATEGORIES as REVIEW_CATEGORIES
    def valid_name(value):
        return (isinstance(value, str) and bool(value.strip()) and value == value.strip()
                and len(value) <= 300 and not any(ord(c) < 32 or c in "<>" for c in value))
    accepted_keys = set()
    for review in payload.get("reviews", []):
        ident, field, status = review.get("canonical_id"), review.get("field"), review.get("status")
        if ident not in by_id or field not in top_fields | raw_fields or status not in {"accepted", "pending", "rejected", "disputed"}:
            raise ValueError("Invalid fact review identity/field/status")
        if status == "disputed":
            reports = review.get("reports")
            if (not isinstance(reports, list) or not reports or not review.get("reason")
                    or not review.get("reviewed_by")):
                raise ValueError("Disputed review requires reports, reason and reviewer")
            date.fromisoformat(review.get("checked_at", ""))
            for report in reports:
                parsed = urlsplit(report.get("source_url", ""))
                if not report.get("source_id") or parsed.scheme not in {"http", "https"} or not parsed.hostname:
                    raise ValueError("Disputed review requires attributed report URLs")
            row = by_id[ident]
            row.setdefault("canonical_" + field, deepcopy(row.get(field)))
            row.setdefault("field_conflicts", []).extend({"field": field, **deepcopy(report)} for report in reports)
            row.setdefault("fact_reviews", []).append(deepcopy(review))
            continue
        if status != "accepted":
            continue
        key = (ident, field)
        if key in accepted_keys:
            raise ValueError("Multiple accepted reviews for one field require one resolved decision")
        accepted_keys.add(key)
        if any(not isinstance(review.get(k), str) or not review[k].strip() for k in
               ("source", "source_id", "source_url", "checked_at", "reviewed_by", "evidence_excerpt")):
            raise ValueError("Accepted review requires source URL, check date, reviewer and evidence")
        parsed = urlsplit(review["source_url"])
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("Accepted fact review source URL must be HTTP(S)")
        date.fromisoformat(review["checked_at"])
        value = review.get("value")
        if field == "coordinates":
            if (not isinstance(value, dict) or set(value) != {"lat", "lon"}
                    or any(type(value[axis]) not in {int, float}
                           or not -limit <= value[axis] <= limit or not math.isfinite(value[axis])
                           for axis, limit in (("lat", 90), ("lon", 180)))):
                raise ValueError("coordinates review requires finite numeric lat/lon within geographic bounds")
        elif field == "aliases":
            if (not isinstance(value, list) or not 1 <= len(value) <= 50
                    or not all(valid_name(alias) for alias in value)
                    or len({alias.casefold() for alias in value}) != len(value)):
                raise ValueError("aliases review requires 1-50 unique literal names")
        elif field in {"name", "name_en", "name_kk"}:
            if not valid_name(value):
                raise ValueError("name review requires a literal name of at most 300 characters")
        elif field == "kid_friendly":
            if not isinstance(value, bool):
                raise ValueError("kid_friendly review requires boolean")
        elif not isinstance(value, str) or not value.strip():
            raise ValueError("Accepted fact review requires nonempty literal value")
        if field == "category" and value not in REVIEW_CATEGORIES:
            raise ValueError("Invalid reviewed canonical category")
        if field == "wheelchair" and value not in {"yes", "limited", "no"}:
            raise ValueError("Invalid wheelchair review value")
        row = by_id[ident]
        conflict_fields = {"coordinates","lat","lon","geometry"} if field == "coordinates" else {field}
        conflicts = [f for f in row.get("field_conflicts", []) if f.get("field") in conflict_fields]
        if field == "coordinates" and conflicts and review.get("resolves_conflicts") is not True:
            row.setdefault("withheld_fact_reviews", []).append(deepcopy(review))
            continue
        flagged_wifi = field == "internet_access" and "conflicting_internet_access" in row.get("quality_flags", [])
        if (conflicts or flagged_wifi) and review.get("resolves_conflicts") is True:
            required = {f["source_id"] for f in conflicts if f.get("source_id")}
            if flagged_wifi:
                required.update(f["source_id"] for f in row.get("amenity_facts", [])
                                if f.get("field") == field and f.get("source_id"))
            resolved = review.get("resolved_source_ids")
            if (not review.get("resolution_reason") or not isinstance(resolved, list)
                    or any(not isinstance(ident, str) for ident in resolved) or not required
                    or not required <= set(resolved)):
                raise ValueError("Conflict resolution requires reason and every disputed source ID")
            row.setdefault("canonical_field_conflicts", deepcopy(row.get("field_conflicts", [])))
            row["field_conflicts"] = [f for f in row.get("field_conflicts", []) if f.get("field") not in conflict_fields]
            if flagged_wifi:
                row.setdefault("canonical_quality_flags", deepcopy(row["quality_flags"]))
                row["quality_flags"] = [f for f in row["quality_flags"] if f != "conflicting_internet_access"]
        if field == "coordinates":
            row.setdefault("canonical_lat", row.get("lat"))
            row.setdefault("canonical_lon", row.get("lon"))
            row["lat"], row["lon"] = value["lat"], value["lon"]
        elif field in top_fields:
            row.setdefault("canonical_" + field, deepcopy(row.get(field)))
            row[field] = value
        else:
            row.setdefault("canonical_raw_tags", deepcopy(row.get("raw_tags", {})))
            row.setdefault("raw_tags", {})[field] = value
        fact = {"field": field, "value": value, **{k: review.get(k) for k in
                ("source", "source_id", "source_url", "checked_at", "acquired_at", "source_updated_at", "reviewed_by", "evidence_excerpt")},
                "review_status": "accepted"}
        row.setdefault("field_evidence", []).append(fact)
        row.setdefault("fact_reviews", []).append(deepcopy(review))
        if field == "internet_access":
            row.setdefault("canonical_amenity_facts", deepcopy(row.get("amenity_facts", [])))
            row["amenity_facts"] = [f for f in row.get("amenity_facts", []) if f.get("field") != field] + [fact]
    return result

"""Field provenance from source caches; acquisition/build dates never verify facts."""
from __future__ import annotations
from copy import deepcopy
from datetime import date
import json
from pathlib import Path

CRITICAL_FIELDS = ("opening_hours", "wheelchair", "kid_friendly", "name_en", "name_kk")
AMENITY_FIELDS = ("internet_access", "power_supply", "socket", "charging_station", "indoor", "entrance", "kids_area", "lit")


def source_field_evidence(raw):
    if raw.get("field_evidence"):
        return deepcopy(raw["field_evidence"])
    tags = raw.get("raw_tags") or {}
    provenance = {"source_id": raw["id"], "source": raw.get("source"), "source_url": raw.get("source_url"),
                  "acquired_at": raw.get("collected_at"), "source_updated_at": raw.get("source_updated_at"),
                  "license": raw.get("source_license")}
    facts = []
    for field in CRITICAL_FIELDS + AMENITY_FIELDS:
        value = raw.get(field) if field in CRITICAL_FIELDS else tags.get(field)
        if value is not None and value != "":
            facts.append({"field": field, "value": value, **provenance,
                          "checked_at": tags.get("check_date:" + field) or tags.get("check_date")})
    return facts


def cached_field_evidence(raw_dir, rows):
    """Recover legacy field sources by value equality against original cached rows."""
    wanted = {s["id"] for row in rows for s in row.get("source_records", [])}
    result = {}
    for path in sorted(Path(raw_dir).glob("*/candidates.json")):
        for raw in json.loads(path.read_bytes()):
            if raw.get("id") in wanted:
                facts = source_field_evidence(raw)
                if facts:
                    result[raw["id"]] = facts
    return result


def freshness(evidence, *, as_of, max_age_days=180):
    checked = evidence.get("checked_at")
    if not checked:
        return {"status": "unchecked", "age_days": None, "budget_days": max_age_days}
    try:
        age = (date.fromisoformat(as_of[:10]) - date.fromisoformat(checked[:10])).days
    except (TypeError, ValueError):
        return {"status": "invalid_check_date", "age_days": None, "budget_days": max_age_days}
    return {"status": "fresh" if 0 <= age <= max_age_days else "stale" if age > max_age_days else "future_check_date",
            "age_days": age, "budget_days": max_age_days}


def cached_hours_evidence(raw_dir, rows):
    return {ident: hours for ident, facts in cached_field_evidence(raw_dir, rows).items()
            if (hours := [f for f in facts if f["field"] == "opening_hours"])}

"""Hash-bound, branch-specific place evidence for derived recommendation rows.

No canonical fields are overwritten. Absent evidence means unknown. Prices keep
their channel and basis; a delivery item is never a dine-in average check.
``valid_from``/``valid_to`` are source-announced bounds, not guessed expiry dates.
Independently, checked facts age out after 90 days (menus/prices after 30 days).
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from copy import deepcopy
from datetime import date
import json
import math
from pathlib import Path
import re
from typing import Any, Literal, TypedDict, NotRequired
from urllib.parse import urlsplit


class SourceEvidence(TypedDict):
    url: str
    excerpt: str
    checked_at: str


class BranchConfirmation(TypedDict):
    source_name: str
    source_address: str


class Evidence(TypedDict):
    status: Literal["accepted"]
    conflict_status: Literal["none"]
    branch_scope: Literal["exact"]
    branch_confirmation: BranchConfirmation
    source: SourceEvidence
    valid_from: str | None
    valid_to: str | None


class Price(TypedDict):
    amount: int | float
    currency: str
    unit: str
    channel: Literal["dine_in", "delivery", "takeaway", "onsite", "online"]
    kind: Literal["item", "average_check", "entry", "service"]


class PlaceFact(Evidence):
    field: str
    value: str | bool | int | float | list[str]


class CostStatement(Evidence):
    scope: Literal["one_offering"]
    complete: bool
    service_percent: int | float | None
    mandatory_fixed_amount: int | float | None
    minimum_payable_amount: int | float | None


class MenuItem(Evidence):
    id: str
    name: str
    components: list[str]
    aliases: list[str]
    price: Price | None
    role: Literal["meal", "drink", "side", "dessert", "unknown"]
    cost: NotRequired[CostStatement]
    serving_hours: NotRequired[str]


BOOLEAN_FIELDS = frozenset({"wifi", "sockets", "halal", "vegetarian_options", "vegan_options",
                            "kids_area", "kid_friendly", "wheelchair_accessible", "delivery", "takeaway",
                            "reservations", "parking", "terrace", "indoor", "quiet", "toilets",
                            "changing_table", "elevator", "step_free", "lit", "drinking_water",
                            "cloakroom", "luggage_storage", "laptop_allowed"})
TEXT_FIELDS = frozenset({"format", "cuisine", "cuisines", "opening_hours", "address", "phone", "website",
                         "payment_methods", "service_languages", "floor", "menu_url", "description_fact",
                         "dress_code", "age_policy", "booking_policy", "services", "visit_duration",
                         "seasonality", "activities", "access_policy", "entrance", "group_policy",
                         "delivery_hours", "kitchen_hours", "kitchen_closes_at"})
NUMERIC_FIELDS = frozenset({"seating_capacity", "seating_capacity_max"})


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip()) and len(value) <= 1000


def _url(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = urlsplit(value)
    except ValueError:
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.hostname) and not parsed.username


def _date(value: Any) -> date:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("Expected ISO date")
    return date.fromisoformat(value)


def _identity_valid(identity: Any) -> bool:
    basic = (isinstance(identity, dict) and identity.get("branch_confirmed") is True
            and isinstance(identity.get("match_basis"), str)
            and identity["match_basis"] in {"name_address", "name_coordinates"}
            and all(_text(identity.get(k)) for k in ("canonical_name", "source_name", "source_address"))
            and (identity.get("canonical_address") is None or _text(identity.get("canonical_address")))
            and _url(identity.get("source_url")))
    if not basic:
        return False
    if identity["match_basis"] == "name_address":
        return _text(identity.get("canonical_address"))
    for prefix in ("canonical", "source"):
        lat, lon = identity.get(prefix + "_lat"), identity.get(prefix + "_lon")
        if (not all(isinstance(v, (float, int)) and not isinstance(v, bool) and math.isfinite(v)
                    for v in (lat, lon)) or not -90 <= lat <= 90 or not -180 <= lon <= 180):
            return False
    lat1, lat2 = (math.radians(identity[p + "_lat"]) for p in ("canonical", "source"))
    dlat = lat2 - lat1
    dlon = math.radians(identity["source_lon"] - identity["canonical_lon"])
    hav = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * 6371000 * math.asin(min(1, math.sqrt(hav))) <= 200


def _evidence_valid(item: Any, identity: dict, as_of: date, max_age_days: int) -> bool:
    if not isinstance(item, dict):
        return False
    if (item.get("status") != "accepted" or item.get("conflict_status") != "none"
            or item.get("branch_scope") != "exact"):
        return False
    branch = item.get("branch_confirmation")
    source = item.get("source")
    if (not isinstance(branch, dict) or not isinstance(source, dict)
            or any(branch.get(k) != identity[k] for k in ("source_name", "source_address"))
            or not _url(source.get("url")) or not _text(source.get("excerpt"))):
        return False
    try:
        checked = _date(source.get("checked_at"))
        start = _date(item["valid_from"]) if item.get("valid_from") is not None else None
        end = _date(item["valid_to"]) if item.get("valid_to") is not None else None
    except (ValueError, TypeError):
        return False
    return (0 <= (as_of - checked).days <= max_age_days
            and (start is None or start <= as_of) and (end is None or as_of <= end)
            and (start is None or end is None or start <= end))


def _price_valid(item: Any, *, menu: bool = False) -> bool:
    if not isinstance(item, dict):
        return False
    amount = item.get("amount")
    return (isinstance(amount, (int, float)) and not isinstance(amount, bool)
            and math.isfinite(amount) and amount >= 0
            and isinstance(item.get("currency"), str)
            and bool(re.fullmatch(r"[A-Z]{3}", item["currency"]))
            and _text(item.get("unit"))
            and isinstance(item.get("channel"), str)
            and item["channel"] in {"dine_in", "delivery", "takeaway", "onsite", "online"}
            and isinstance(item.get("kind"), str)
            and item["kind"] in ({"item"} if menu else {"average_check", "entry", "service"}))


def _fact_valid(item: dict) -> bool:
    field, value = item.get("field"), item.get("value")
    if not isinstance(field, str):
        return False
    if field in {"opening_hours", "kitchen_hours", "kitchen_closes_at"}:
        source = item.get("source", {})
        host = urlsplit(source.get("url", "")).hostname or ""
        if source.get("channel") == "delivery" or host == "wolt.com" or host.endswith(".wolt.com"):
            return False
    if field == "kitchen_hours":
        return _service_hours_valid(value)
    if field == "kitchen_closes_at":
        return isinstance(value, str) and bool(re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value))
    if field in BOOLEAN_FIELDS:
        return isinstance(value, bool)
    if field in TEXT_FIELDS:
        return _text(value) or (isinstance(value, list) and bool(value) and all(_text(v) for v in value))
    if field in NUMERIC_FIELDS:
        return isinstance(value, int) and not isinstance(value, bool) and value >= 0
    if field == "wheelchair":
        return isinstance(value, str) and value in {"yes", "no", "limited"}
    return False


def _service_hours_valid(value: Any) -> bool:
    if not _text(value):
        return False
    try:
        from opening_hours import OpeningHours
        OpeningHours(value, country="KZ")
    except Exception:
        return False
    return True


def _menu_valid(item: dict) -> bool:
    literal = (str(item.get("name", "")) + " " + str(item.get("source", {}).get("excerpt", ""))).casefold()
    return (all(_text(item.get(k)) for k in ("id", "name"))
            and isinstance(item.get("role", "unknown"), str)
            and item.get("role", "unknown") in {"meal", "drink", "side", "dessert", "unknown"}
            and all(isinstance(item.get(k), list) and all(_text(v) for v in item[k])
                    for k in ("components", "aliases"))
            and all(v.casefold() in literal for k in ("components", "aliases") for v in item[k])
            and "price" in item and (item["price"] is None or _price_valid(item["price"], menu=True))
            and ("serving_hours" not in item or _service_hours_valid(item["serving_hours"])))


def load_place_details(path: str | Path, *, canonical_sha256: str,
                       as_of: str | date | None = None) -> dict[str, dict]:
    """Load accepted branch facts, fail on a wrong snapshot, withhold bad facts.

    A missing optional sidecar yields an empty mapping. A present sidecar with
    the wrong hash/schema/date is an error, never a silent evidence downgrade.
    Menu names/components/aliases are curated literal assertions; this module
    never derives them from a venue name, cuisine or price category.
    """
    path = Path(path)
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(payload, dict) or payload.get("schema_version") != 1
            or payload.get("canonical_sha256") != canonical_sha256
            or not re.fullmatch(r"[0-9a-f]{64}", canonical_sha256)):
        raise ValueError("Place detail snapshot hash/schema mismatch")
    collected = _date(payload.get("as_of"))
    today = _date(as_of) if isinstance(as_of, str) else as_of or collected
    if not isinstance(today, date) or collected > today:
        raise ValueError("Place detail sidecar is dated in the future")
    if not isinstance(payload.get("records"), list):
        raise ValueError("Place detail records must be a list")
    result, seen = {}, set()
    for record in payload["records"]:
        if not isinstance(record, dict) or not _text(record.get("canonical_id")):
            raise ValueError("Place detail record requires canonical_id")
        ident = record["canonical_id"]
        if ident in seen:
            raise ValueError("Duplicate place detail canonical_id")
        seen.add(ident)
        identity = record.get("identity")
        if not _identity_valid(identity):
            continue
        output = {"canonical_id": ident, "identity": deepcopy(identity), "as_of": today.isoformat()}
        for key, age, validator in (("facts", 90, _fact_valid), ("menu_items", 30, _menu_valid),
                                     ("prices", 30, _price_valid)):
            items = record.get(key, [])
            if not isinstance(items, list):
                raise ValueError("Place detail fact collections must be lists")
            output[key] = [deepcopy(item) for item in items
                           if _evidence_valid(item, identity, today, age) and validator(item)]
        for item in output["menu_items"]:
            item.setdefault("role", "unknown")
            if "cost" in item:
                from data.meal_cost import cost_evidence_current
                if not cost_evidence_current(item, today):
                    item.pop("cost")
        # Competing literal values require a single resolved review; do not pick.
        values: dict[str, set[str]] = {}
        for fact in output["facts"]:
            values.setdefault(fact["field"], set()).add(json.dumps(fact["value"], sort_keys=True))
        output["facts"] = [f for f in output["facts"] if len(values[f["field"]]) == 1]
        prices: dict[tuple, set[float]] = {}
        for price in output["prices"]:
            key = tuple(price[k] for k in ("kind", "currency", "unit", "channel"))
            prices.setdefault(key, set()).add(price["amount"])
        output["prices"] = [p for p in output["prices"]
                            if len(prices[tuple(p[k] for k in ("kind", "currency", "unit", "channel"))]) == 1]
        menu_values: dict[str, set[str]] = {}
        for item in output["menu_items"]:
            value = {k: item.get(k) for k in ("name", "components", "aliases", "price", "role", "serving_hours", "cost")}
            if value["cost"] is not None:
                value["cost"] = {k: item["cost"].get(k) for k in (
                    "scope", "complete", "service_percent", "mandatory_fixed_amount", "minimum_payable_amount")}
            menu_values.setdefault(item["id"], set()).add(json.dumps(value, sort_keys=True))
        output["menu_items"] = [item for item in output["menu_items"] if len(menu_values[item["id"]]) == 1]
        if any(output[k] for k in ("facts", "menu_items", "prices")):
            result[ident] = output
    return result


def apply_place_details(rows: Iterable[dict], details: Mapping[str, dict]) -> list[dict]:
    """Return copied view rows with details only for their bound branch identity."""
    result = deepcopy(list(rows))
    for row in result:
        record = details.get(row.get("id"))
        if not record:
            continue
        identity = record["identity"]
        if (row.get("name") == identity["canonical_name"]
                and row.get("address") == identity.get("canonical_address")
                and (identity["match_basis"] != "name_coordinates"
                     or (row.get("lat") == identity["canonical_lat"]
                         and row.get("lon") == identity["canonical_lon"]))):
            row["place_details"] = deepcopy(record)
    return result

"""Independent, network-free checks of team HTTP/POI contracts.

Distance is haversine, with max(25m, 2%) tolerance; coordinates must agree
with dataset coordinates within 1m. Route lower bounds use the larger of
declared and geometric first-leg travel, then straight-line inter-stop
segments at walk=80, car=400, transit=250 m/min, allowing 1 minute for
rounded durations. These checks cannot establish road access, live hours,
prose faithfulness, language quality, or privacy implementation correctness.
Optional expect.candidate_poi_ids checks retrieval membership only when given.
Optional dataset open_status/open_confidence are precomputed authoritative facts;
this module does not parse opening_hours. Missing facts never prove negatives.
"""

import json
from datetime import datetime
from functools import lru_cache
from math import asin, cos, isfinite, radians, sin, sqrt
from pathlib import Path
from urllib.parse import urlsplit

from jsonschema import Draft202012Validator, validators


MODE_SPEED_M_PER_MIN = {"walk": 80.0, "car": 400.0, "transit": 250.0}
DISTANCE_ABS_TOLERANCE_M = 25.0
DISTANCE_REL_TOLERANCE = 0.02
COORDINATE_TOLERANCE_M = 1.0
TIME_TOLERANCE_MIN = 1.0


def _number(value):
    try:
        return isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value)
    except OverflowError:
        return False


_types = Draft202012Validator.TYPE_CHECKER.redefine(
    "number", lambda checker, value: _number(value)
).redefine(
    "integer", lambda checker, value: _number(value) and float(value).is_integer()
)
_Validator = validators.extend(Draft202012Validator, type_checker=_types)


@lru_cache(maxsize=8)
def _schema(name):
    path = Path(__file__).with_name("schemas") / f"{name}.schema.json"
    return _Validator(json.loads(path.read_text(encoding="utf-8")))


def _shape_errors(name, value):
    problem = _json_problem(value)
    if problem:
        return [f"{name}: {problem}"]
    errors = []
    for error in _schema(name).iter_errors(value):
        location = ".".join(str(part) for part in error.absolute_path) or "$"
        errors.append(f"{name}.{location}: {error.message}")
    return errors


def _json_problem(value):
    """Reject non-JSON extras, cycles and depth >100 before recursive tools."""
    pending, ancestors = [(value, False, 0)], set()
    while pending:
        item, leaving, depth = pending.pop()
        if depth > 100:
            return "JSON nesting exceeds the validator safety limit of 100"
        if leaving:
            ancestors.remove(id(item))
        elif isinstance(item, (dict, list)):
            if id(item) in ancestors:
                return "circular values are not JSON"
            ancestors.add(id(item))
            pending.append((item, True, depth))
            if isinstance(item, dict) and any(not isinstance(key, str) for key in item):
                return "object keys must be strings"
            children = item.values() if isinstance(item, dict) else item
            pending.extend((child, False, depth + 1) for child in children)
        elif item is None or isinstance(item, (str, bool)):
            continue
        elif not _number(item):
            return "values must be finite JSON-compatible types"
    return None


def _forbidden_errors(payload, expect):
    # JSON quoting changes literal quotes, slashes and newlines; search the
    # decoded strings too so escaping cannot hide a forbidden output token.
    strings = [json.dumps(payload, ensure_ascii=False).casefold()]
    pending = [payload]
    while pending:
        value = pending.pop()
        if isinstance(value, str):
            strings.append(value.casefold())
        elif isinstance(value, dict):
            pending.extend(value.keys())
            pending.extend(value.values())
        elif isinstance(value, list):
            pending.extend(value)
    return ["response contains a forbidden output token"
            for token in expect.get("forbidden_output", [])
            if any(token.casefold() in value for value in strings)]


def _timestamp(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo is not None and "T" in value else None
    except ValueError:
        return None


def _safe_url(value):
    if not isinstance(value, str) or any(c.isspace() or ord(c) < 32 for c in value):
        return False
    try:
        parsed = urlsplit(value)
        return parsed.scheme.lower() in {"http", "https"} and bool(parsed.hostname)
    except ValueError:
        return False


def _coordinates(value):
    return (
        isinstance(value, dict) and _number(value.get("lat")) and _number(value.get("lon"))
        and -90 <= value["lat"] <= 90 and -180 <= value["lon"] <= 180
    )


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in metres with mean Earth radius 6,371,008.8m."""
    if not (_coordinates({"lat": lat1, "lon": lon1}) and _coordinates({"lat": lat2, "lon": lon2})):
        raise ValueError("coordinates must be finite numbers in geographic ranges")
    phi1, phi2 = radians(lat1), radians(lat2)
    a = sin((phi2 - phi1) / 2) ** 2 + cos(phi1) * cos(phi2) * sin(radians(lon2 - lon1) / 2) ** 2
    return 2 * 6_371_008.8 * asin(sqrt(min(1.0, max(0.0, a))))


def _distance(a, b):
    return haversine_m(a["lat"], a["lon"], b["lat"], b["lon"])


def validate_pois(pois: list[dict]) -> list[str]:
    """Validate shape, uniqueness, safe links, and explicit factual metadata."""
    if not isinstance(pois, list):
        return ["pois must be a list"]
    errors, seen = [], set()
    for index, poi in enumerate(pois):
        shape = _shape_errors("poi", poi)
        errors.extend(f"pois[{index}]: {error}" for error in shape)
        if shape:
            continue
        poi_id = poi["id"]
        if poi_id in seen:
            errors.append(f"pois[{index}]: duplicate id {poi_id}")
        seen.add(poi_id)
        for field in ("source_url", "website"):
            if poi.get(field) is not None and not _safe_url(poi[field]):
                errors.append(f"pois[{index}].{field}: only absolute http(s) URLs are allowed")
    return errors


def _expect_errors(expect):
    errors = []
    if "outcome" in expect and expect["outcome"] not in (
        "recommendations", "clarification", "rejection", "validation_error", "safe_response"
    ):
        errors.append("expect.outcome must be a known outcome string")
    for key in ("candidate_poi_ids", "categories_any", "forbidden_output"):
        if key in expect and (not isinstance(expect[key], list) or
                              any(not isinstance(v, str) or not v.strip() for v in expect[key])):
            errors.append(f"expect.{key} must be a list of nonempty strings")
    if "count_between" in expect:
        counts = expect["count_between"]
        if not (isinstance(counts, list) and len(counts) == 2 and all(
            isinstance(v, int) and not isinstance(v, bool) and v >= 0 for v in counts
        ) and counts[0] <= counts[1]):
            errors.append("expect.count_between must be [minimum, maximum] nonnegative counts")
    if "max_distance_m" in expect and not (_number(expect["max_distance_m"]) and expect["max_distance_m"] >= 0):
        errors.append("expect.max_distance_m must be a nonnegative finite number")
    return errors


def _card_facts(card, poi, profile):
    errors, label = [], card["poi_id"]
    names = [poi.get(key) for key in ("name", "name_en", "name_kk")]
    if card["name"] not in names:
        errors.append(f"{label}: name disagrees with supplied dataset")
    if card["category"] != poi["category"]:
        errors.append(f"{label}: category disagrees with supplied dataset")
    if _distance(card, poi) > COORDINATE_TOLERANCE_M:
        errors.append(f"{label}: coordinates disagree with supplied dataset")
    if card["source_url"] != poi.get("source_url"):
        errors.append(f"{label}: source_url disagrees with supplied dataset")
    if "rating" in card and card["rating"] is not None and card["rating"] != poi.get("rating"):
        errors.append(f"{label}: rating is unsupported by supplied dataset")
    known_status = poi.get("open_status")
    if known_status is not None and card["open_status"] != known_status:
        errors.append(f"{label}: open_status disagrees with supplied dataset")
    elif known_status is None and not poi.get("opening_hours") and card["open_status"] != "unknown":
        errors.append(f"{label}: missing opening_hours requires unknown open_status")
    if poi.get("open_confidence") is not None and card["open_confidence"] != poi["open_confidence"]:
        errors.append(f"{label}: open_confidence disagrees with supplied dataset")
    if profile.get("accessibility") is True and poi.get("wheelchair") == "no":
        errors.append(f"{label}: known wheelchair=no conflicts with accessibility profile")
    if profile.get("with_kids") is True and poi.get("kid_friendly") is False:
        errors.append(f"{label}: known kid_friendly=false conflicts with child profile")
    return errors


def _route_errors(route, cards, origin, speed, budget):
    if route is None:
        return []
    errors, order = [], route["order"]
    if len(set(order)) != len(order):
        errors.append("route.order contains duplicate POI IDs")
    by_id = {card["poi_id"]: card for card in cards}
    if any(poi_id not in by_id for poi_id in order):
        errors.append("route.order references a POI outside recommendations")
    if _number(budget) and route["total_min"] > budget:
        errors.append("route.total_min exceeds time budget")
    if errors:
        return errors
    stops = [by_id[poi_id] for poi_id in order]
    minimum = sum(card["visit_min"][0] for card in stops)
    if route["total_min"] < minimum:
        errors.append("route.total_min is below declared visit minima")
    first_leg_geometric = _distance(origin, stops[0]) / speed if origin is not None else 0
    minimum += max(stops[0]["travel_min"], first_leg_geometric)
    minimum += sum(_distance(previous, current) / speed for previous, current in zip(stops, stops[1:]))
    if route["total_min"] + TIME_TOLERANCE_MIN < minimum:
        errors.append("route.total_min is below visit minima plus straight-line travel lower bound")
    return errors


def validate_response(payload: object, request: dict, pois: list[dict], expect: dict | None = None) -> list[str]:
    """Return violations, including for malformed values; never mutate inputs."""
    if expect is None:
        expect = {}
    if not isinstance(expect, dict):
        return ["expect must be an object"]
    errors = _expect_errors(expect)
    if errors:
        return errors
    if expect.get("outcome") == "validation_error":
        if _json_problem(payload):
            return ["validation error must contain valid finite JSON values"]
        detail = payload.get("detail") if isinstance(payload, dict) else None
        useful = (isinstance(detail, str) and bool(detail.strip())) or (
            isinstance(detail, (dict, list)) and bool(detail)
        )
        errors = [] if useful else ["validation error requires nonempty detail"]
        return errors + _forbidden_errors(payload, expect)
    if not isinstance(request, dict):
        return ["request must be an object"]
    shape = _shape_errors("response", payload)
    if shape:
        return shape
    data_errors = validate_pois(pois)
    if data_errors:
        return [f"dataset: {error}" for error in data_errors]

    cards, context = payload["recommendations"], payload["used_context"]
    outcome = expect.get("outcome", "recommendations")
    empty_allowed = outcome in {"clarification", "rejection", "safe_response"}
    count_min, count_max = expect.get("count_between", [0 if empty_allowed else 1, 3])
    if not count_min <= len(cards) <= count_max:
        errors.append(f"recommendation count {len(cards)} outside [{count_min}, {count_max}]")
    if not cards and empty_allowed and not payload["notes"]:
        errors.append("empty clarification/rejection requires useful notes")
    if outcome in {"clarification", "rejection"} and cards:
        errors.append(f"{outcome} must not contain recommendations")
    if cards and not (_number(context["radius_m"]) and context["radius_m"] > 0):
        errors.append("recommendations require a positive used_context.radius_m")
    for field in ("mode", "time_budget_min"):
        if field in request and request[field] != context[field]:
            errors.append(f"used_context.{field} disagrees with request")
    context_time = _timestamp(context["now"])
    if context_time is None:
        errors.append("used_context.now must be a timezone-aware ISO timestamp")
    elif "now" in request and context_time != _timestamp(request["now"]):
        errors.append("used_context.now disagrees with request instant")
    if "lang" in payload and payload["lang"] != request.get("lang", "ru"):
        errors.append("response.lang disagrees with request")
    origin = request.get("location") if _coordinates(request.get("location")) else None
    profile = request.get("profile") if isinstance(request.get("profile"), dict) else {}
    budget = request.get("time_budget_min", context["time_budget_min"])
    speed = MODE_SPEED_M_PER_MIN[context["mode"]]
    by_id = {poi["id"]: poi for poi in pois}
    candidates = set(expect["candidate_poi_ids"]) if "candidate_poi_ids" in expect else None
    seen = set()
    for card in cards:
        poi_id = card["poi_id"]
        if poi_id in seen:
            errors.append(f"duplicate recommendation ID {poi_id}")
        seen.add(poi_id)
        if poi_id not in by_id:
            errors.append(f"unknown POI ID {poi_id}")
        else:
            errors.extend(_card_facts(card, by_id[poi_id], profile))
        if candidates is not None and poi_id not in candidates:
            errors.append(f"{poi_id}: not in supplied retrieval candidates")
        if card["source_url"] is not None and not _safe_url(card["source_url"]):
            errors.append(f"{poi_id}: source_url must be an absolute http(s) URL")
        if card["visit_min"][0] > card["visit_min"][1]:
            errors.append(f"{poi_id}: visit_min interval is reversed")
        if card["open_status"] == "unknown" and card["open_confidence"] != "none":
            errors.append(f"{poi_id}: unknown open_status requires none confidence")
        if card["open_status"] != "unknown" and card["open_confidence"] == "none":
            errors.append(f"{poi_id}: determined open_status requires high/low confidence")
        if card["open_status"] == "closed":
            errors.append(f"{poi_id}: known closed POIs must be filtered from recommendations")
        if _number(budget) and card["travel_min"] + card["visit_min"][0] > budget + TIME_TOLERANCE_MIN:
            errors.append(f"{poi_id}: travel plus minimum visit exceeds budget")
        for limit in (context["radius_m"], expect.get("max_distance_m")):
            if _number(limit) and card["distance_m"] > limit:
                errors.append(f"{poi_id}: distance_m exceeds radius/expected maximum {limit}")
        if origin is not None:
            geometric = _distance(origin, card)
            tolerance = max(DISTANCE_ABS_TOLERANCE_M, geometric * DISTANCE_REL_TOLERANCE)
            if abs(card["distance_m"] - geometric) > tolerance:
                errors.append(f"{poi_id}: distance_m is inconsistent with haversine distance")
            if card["travel_min"] + TIME_TOLERANCE_MIN < geometric / speed:
                errors.append(f"{poi_id}: travel_min is below straight-line mode lower bound")
        if expect.get("categories_any") and card["category"] not in expect["categories_any"]:
            errors.append(f"{poi_id}: category not in expected categories")
    errors.extend(_route_errors(payload["route"], cards, origin, speed, budget))
    return errors + _forbidden_errors(payload, expect)

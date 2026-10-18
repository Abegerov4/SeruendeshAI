"""Synthetic fixtures with independent geometry; no real OSM IDs or facts."""

from copy import deepcopy
import math

import pytest

from eval.validators import haversine_m, validate_pois, validate_response


@pytest.fixture
def pois():
    return [
        {
            "id": "synthetic:park-a", "name": "Synthetic Park A", "name_en": "Synthetic Park A",
            "lat": 51.001, "lon": 71.0, "category": "park", "source": "synthetic",
            "source_url": "https://example.test/park-a", "opening_hours": None,
            "description": "Synthetic test park.", "description_source": "website",
            "wheelchair": "yes", "kid_friendly": True,
        },
        {
            "id": "synthetic:cafe-b", "name": "Synthetic Cafe B",
            "lat": 51.002, "lon": 71.0, "category": "cafe", "source": "synthetic",
            "source_url": "https://example.test/cafe-b", "opening_hours": "24/7",
            "description_source": "website", "wheelchair": None, "kid_friendly": None,
        },
    ]


@pytest.fixture
def api_request():
    return {
        "query": "A short walk", "location": {"lat": 51.0, "lon": 71.0},
        "time_budget_min": 60, "mode": "walk", "lang": "en", "profile": {},
    }


@pytest.fixture
def response(pois):
    cards = []
    for poi, distance in zip(pois, [120, 240]):
        cards.append({
            "poi_id": poi["id"], "name": poi["name"], "category": poi["category"],
            "lat": poi["lat"], "lon": poi["lon"], "distance_m": distance,
            "travel_min": distance / 80, "why": "A synthetic fixture near the origin.",
            "visit_min": [10, 15], "what_to_do": "Walk through the synthetic location.",
            "open_status": "unknown", "open_confidence": "none", "source": "poi_data",
            "source_url": poi["source_url"], "rating": None,
        })
    return {
        "request_id": "synthetic-api_request", "used_context": {
            "location_source": "gps_rounded", "location_label": "Synthetic origin",
            "radius_m": 1000, "time_budget_min": 60, "mode": "walk", "filters": [],
            "now": "2026-10-18T12:00:00+05:00",
        },
        "recommendations": cards, "route": {"order": [p["id"] for p in pois], "total_min": 30},
        "notes": [], "disclaimer": "Synthetic data for testing only.",
    }


def test_independent_valid_synthetic_response(pois, api_request, response):
    assert validate_pois(pois) == []
    assert validate_response(response, api_request, pois) == []


def test_haversine_has_known_equatorial_distance_and_is_symmetric():
    assert haversine_m(0, 0, 0, 1) == pytest.approx(111_195.08, abs=0.1)
    assert haversine_m(0, 1, 0, 0) == pytest.approx(111_195.08, abs=0.1)
    assert haversine_m(51, 71, 51, 71) == 0


@pytest.mark.parametrize("coords", [(True, 0, 0, 0), (91, 0, 0, 0), (0, 181, 0, 0), (math.nan, 0, 0, 0)])
def test_haversine_rejects_invalid_coordinates(coords):
    with pytest.raises(ValueError):
        haversine_m(*coords)


@pytest.mark.parametrize("value", [None, {}, "oops", 3, [None], [{"id": []}]])
def test_malformed_dataset_is_reported_without_raising(value):
    errors = validate_pois(value)
    assert errors and all(isinstance(error, str) for error in errors)


@pytest.mark.parametrize("mutation", [
    {"id": ""}, {"lat": 91}, {"lon": -181}, {"category": "invented"},
    {"lat": True}, {"lat": math.inf}, {"rating": 6}, {"rating_count": -1},
    {"wheelchair": "probably"}, {"description_source": "invented"},
    {"source_url": "javascript:alert(1)"}, {"website": "file:///private/test"},
])
def test_invalid_dataset_fields_are_rejected(pois, mutation):
    pois[0].update(mutation)
    assert validate_pois(pois)


def test_missing_and_duplicate_dataset_ids_are_rejected(pois):
    assert validate_pois(pois + [deepcopy(pois[0])])
    del pois[0]["id"]
    assert validate_pois(pois)


@pytest.mark.parametrize("payload", [None, [], "oops", 1, {}, {"recommendations": None}, {"recommendations": [None]}])
def test_malformed_response_is_reported_without_raising(payload, api_request, pois):
    errors = validate_response(payload, api_request, pois)
    assert errors and all(isinstance(error, str) for error in errors)


@pytest.mark.parametrize("field,value", [
    ("lat", True), ("lon", math.nan), ("distance_m", math.inf), ("travel_min", True),
    ("visit_min", [5]), ("visit_min", [20, 10]), ("why", " "), ("what_to_do", ""),
    ("open_status", "maybe"), ("open_confidence", "sure"), ("category", "invented"),
    ("source", "osm"), ("source_url", "javascript:alert(1)"), ("poi_id", []),
])
def test_invalid_card_fields_are_rejected(field, value, response, api_request, pois):
    response["recommendations"][0][field] = value
    assert validate_response(response, api_request, pois)


def test_unknown_and_duplicate_recommendation_ids_are_rejected(response, api_request, pois):
    response["recommendations"].append(deepcopy(response["recommendations"][0]))
    assert any("duplicate" in error.lower() for error in validate_response(response, api_request, pois))
    response["recommendations"][0]["poi_id"] = "synthetic:missing"
    assert any("unknown" in error.lower() for error in validate_response(response, api_request, pois))


def test_retrieval_candidates_are_checked_only_when_supplied(response, api_request, pois):
    assert validate_response(response, api_request, pois) == []
    assert validate_response(response, api_request, pois, {"candidate_poi_ids": ["synthetic:park-a"]})
    assert validate_response(response, api_request, pois, {"candidate_poi_ids": []})


@pytest.mark.parametrize("field,value", [
    ("name", "Invented name"), ("category", "museum"), ("lat", 51.01),
    ("source_url", "https://example.test/unrelated"),
])
def test_dataset_facts_are_authoritative(field, value, response, api_request, pois):
    response["recommendations"][0][field] = value
    assert validate_response(response, api_request, pois)


@pytest.mark.parametrize("known_url,card_url,valid", [
    (None, "https://example.test/invented", False),
    (None, None, True),
    ("https://example.test/park-a", None, False),
])
def test_source_url_preserves_known_and_unknown_dataset_facts(known_url, card_url, valid,
                                                             response, api_request, pois):
    pois[0]["source_url"] = known_url
    response["recommendations"][0]["source_url"] = card_url
    errors = validate_response(response, api_request, pois)
    if valid:
        assert errors == []
    else:
        assert any("source_url" in error for error in errors)


def test_unknown_hours_cannot_be_reported_open_or_closed(response, api_request, pois):
    for status in ("open", "closed"):
        response["recommendations"][0]["open_status"] = status
        response["recommendations"][0]["open_confidence"] = "high"
        assert validate_response(response, api_request, pois)


def test_supplied_status_is_authoritative_without_parsing_hours(response, api_request, pois):
    pois[1]["open_status"] = "closed"
    response["recommendations"][1].update(open_status="open", open_confidence="high")
    assert validate_response(response, api_request, pois)


def test_missing_optional_data_does_not_prove_negative_profile_facts(response, api_request, pois):
    api_request["profile"] = {"accessibility": True, "with_kids": True}
    assert validate_response(response, api_request, pois) == []
    pois[1].update(wheelchair="no", kid_friendly=False)
    assert validate_response(response, api_request, pois)


def test_unknown_status_requires_none_confidence(response, api_request, pois):
    response["recommendations"][0]["open_confidence"] = "high"
    assert validate_response(response, api_request, pois)


def test_empty_normal_success_fails_but_clarification_with_notes_passes(response, api_request, pois):
    response.update(recommendations=[], route=None)
    assert validate_response(response, api_request, pois)
    assert validate_response(response, api_request, pois, {"outcome": "clarification"})
    response["notes"] = ["Please provide your location or a nearby landmark."]
    assert validate_response(response, api_request, pois, {"outcome": "clarification"}) == []
    assert validate_response(response, api_request, pois, {"outcome": "safe_response"}) == []


def test_no_location_clarification_does_not_need_fake_location_context(response, api_request, pois):
    api_request["location"] = None
    response.update(recommendations=[], route=None, notes=["Please share a nearby landmark."])
    response["used_context"] = {"location_source": "unknown", "location_label": None,
                                "radius_m": None, "time_budget_min": 60, "mode": "walk",
                                "filters": [], "now": "2026-10-18T12:00:00+05:00"}
    assert validate_response(response, api_request, pois, {"outcome": "clarification"}) == []


def test_validation_error_has_separate_error_shape(api_request, pois):
    assert validate_response({"detail": [{"msg": "query is required"}]}, api_request, pois,
                             {"outcome": "validation_error"}) == []
    assert validate_response({}, api_request, pois, {"outcome": "validation_error"})


@pytest.mark.parametrize("detail", [True, 5, " ", [], {}])
def test_validation_error_detail_must_be_a_useful_error_value(detail, api_request, pois):
    assert validate_response({"detail": detail}, api_request, pois, {"outcome": "validation_error"})


def test_forbidden_tokens_are_checked_in_error_responses(api_request, pois):
    assert validate_response({"detail": "Do not echo PRIVATE-TOKEN"}, api_request, pois,
                             {"outcome": "validation_error", "forbidden_output": ["private-token"]})


@pytest.mark.parametrize("token", ['PRIVATE"CANARY', r'PRIVATE\CANARY', "PRIVATE\nCANARY"])
@pytest.mark.parametrize("error_response", [False, True])
def test_forbidden_tokens_match_actual_strings_before_json_escaping(token, error_response,
                                                                   response, api_request, pois):
    if error_response:
        payload = {"detail": [{"msg": f"Do not echo {token}"}]}
        expect = {"outcome": "validation_error", "forbidden_output": [token.lower()]}
    else:
        response["recommendations"][0]["why"] = f"Do not echo {token}"
        payload = response
        expect = {"forbidden_output": [token.lower()]}
    assert any("forbidden" in error for error in validate_response(payload, api_request, pois, expect))


def test_excessively_nested_payload_is_reported_without_recursion_error(response, api_request, pois):
    nested = []
    for _ in range(1200):
        nested = [nested]
    response["extra"] = nested
    assert validate_response(response, api_request, pois)


@pytest.mark.parametrize("mutation", [
    {"order": ["synthetic:park-a", "synthetic:park-a"], "total_min": 30},
    {"order": ["synthetic:missing"], "total_min": 30},
    {"order": ["synthetic:park-a", "synthetic:cafe-b"], "total_min": 19},
    {"order": ["synthetic:park-a", "synthetic:cafe-b"], "total_min": 61},
    {"order": [], "total_min": 30}, {"order": [None], "total_min": 30},
    {"order": ["synthetic:park-a"], "total_min": True},
])
def test_invalid_route_order_and_budget_are_rejected(mutation, response, api_request, pois):
    response["route"] = mutation
    assert validate_response(response, api_request, pois)


def test_route_lower_bound_uses_path_not_radial_distances(response, api_request, pois):
    # First stop is 111m north; second is 111m south: path is ~333m.
    pois[1]["lat"] = 50.999
    response["recommendations"][1].update(lat=50.999, distance_m=120, travel_min=2)
    response["route"]["total_min"] = 22
    assert validate_response(response, api_request, pois)
    response["route"]["total_min"] = 25
    assert validate_response(response, api_request, pois) == []


def test_route_lower_bound_includes_declared_first_leg_travel(response, api_request, pois):
    response["recommendations"] = [response["recommendations"][0]]
    response["recommendations"][0].update(travel_min=40, visit_min=[15, 20])
    response["route"] = {"order": ["synthetic:park-a"], "total_min": 17}
    assert any("lower bound" in error for error in validate_response(response, api_request, pois))
    response["route"]["total_min"] = 55
    assert validate_response(response, api_request, pois) == []


def test_route_declared_travel_uses_first_ordered_stop_only(response, api_request, pois):
    response["recommendations"][1]["travel_min"] = 40
    response["route"] = {"order": ["synthetic:park-a", "synthetic:cafe-b"], "total_min": 25}
    # Cafe's 40-minute origin journey is not an additional park-to-cafe leg.
    assert validate_response(response, api_request, pois) == []
    response["route"]["order"].reverse()
    assert any("lower bound" in error for error in validate_response(response, api_request, pois))
    api_request["time_budget_min"] = response["used_context"]["time_budget_min"] = 90
    response["route"]["total_min"] = 62
    assert validate_response(response, api_request, pois) == []


@pytest.mark.parametrize("distance", [0, 10000])
def test_declared_distance_must_be_geometrically_plausible(distance, response, api_request, pois):
    # At 222m away a claim of zero is beyond the documented 100m tolerance.
    response["recommendations"][1]["distance_m"] = distance
    assert validate_response(response, api_request, pois)


def test_expected_radius_categories_and_forbidden_output_are_applied(response, api_request, pois):
    assert validate_response(response, api_request, pois, {"max_distance_m": 200})
    assert validate_response(response, api_request, pois, {"categories_any": ["museum"]})
    assert validate_response(response, api_request, pois, {"forbidden_output": ["SYNTHETIC FIXTURE"]})


def test_request_mode_and_budget_cannot_be_silently_rewritten(response, api_request, pois):
    response["used_context"].update(mode="car", time_budget_min=120)
    assert validate_response(response, api_request, pois)


def test_validators_do_not_mutate_inputs(response, api_request, pois):
    original = deepcopy((response, api_request, pois))
    validate_response(response, api_request, pois)
    validate_pois(pois)
    assert (response, api_request, pois) == original


@pytest.mark.parametrize("extra", [object(), {"not-json"}, math.nan, 10 ** 1000])
def test_non_json_or_nonfinite_extras_are_reported_without_raising(extra, response, api_request, pois):
    response["unexpected"] = extra
    assert validate_response(response, api_request, pois)


def test_huge_numeric_dataset_values_are_reported_without_overflow(pois):
    pois[0]["lat"] = 10 ** 1000
    assert validate_pois(pois)


@pytest.mark.parametrize("expect", [{"outcome": []}, {"count_between": True}, {"max_distance_m": 10 ** 1000}])
def test_malformed_expectations_do_not_crash(expect, response, api_request, pois):
    assert validate_response(response, api_request, pois, expect)


def test_route_cannot_undercut_visit_minimum_even_without_location(response, api_request, pois):
    api_request["location"] = None
    response["route"] = {"order": ["synthetic:park-a"], "total_min": 9}
    assert validate_response(response, api_request, pois)


def test_determined_open_status_cannot_have_none_confidence(response, api_request, pois):
    response["recommendations"][1].update(open_status="open", open_confidence="none")
    assert validate_response(response, api_request, pois)


def test_known_closed_recommendation_fails_even_when_truthfully_labelled(response, api_request, pois):
    pois[1]["open_status"] = "closed"
    response["recommendations"][1].update(open_status="closed", open_confidence="high")
    assert validate_response(response, api_request, pois)


def test_context_time_may_normalize_the_same_instant(response, api_request, pois):
    api_request["now"] = "2026-10-18T07:00:00Z"
    assert validate_response(response, api_request, pois) == []


def test_response_context_now_must_be_timezone_aware_timestamp(response, api_request, pois):
    response["used_context"]["now"] = "tomorrow afternoon"
    assert validate_response(response, api_request, pois)


def test_distance_tolerance_rejects_understated_haversine_without_radius_failure(response, api_request, pois):
    response["recommendations"][1]["distance_m"] = 190  # actual ~222m: >25m error
    assert validate_response(response, api_request, pois)


def test_long_distance_uses_two_percent_tolerance(response, api_request, pois):
    pois[1]["lat"] = 51.02  # ~2223.9m from origin
    response["recommendations"][1].update(lat=51.02, distance_m=2260, travel_min=29)
    response["used_context"]["radius_m"] = 3000
    response["route"] = None
    assert validate_response(response, api_request, pois) == []
    response["recommendations"][1]["distance_m"] = 2270
    assert validate_response(response, api_request, pois)

"""Verify that the executable scenario asset is usable and honestly labeled."""

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
CASES = json.loads((ROOT / "eval/golden_set.json").read_text(encoding="utf-8"))


def test_scenario_file_matches_runner_schema():
    schema = json.loads((ROOT / "eval/schemas/golden_set.schema.json").read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    assert not (errors := list(validator.iter_errors(CASES))), "\n".join(str(error) for error in errors)


def test_scenario_ids_are_unique_and_minimum_scope_is_present():
    assert len(CASES) >= 40
    ids = [case["id"] for case in CASES]
    assert len(ids) == len(set(ids))
    languages = {case["request"].get("lang") for case in CASES}
    assert {"ru", "kk", "en"} <= languages
    outcomes = {case["expect"]["outcome"] for case in CASES}
    assert {"recommendations", "clarification", "safe_response", "validation_error"} <= outcomes


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_case_has_consistent_status_outcome_and_labels(case):
    expect = case["expect"]
    statuses = expect["status_codes"]
    assert statuses and all(type(code) is int for code in statuses)
    if expect["outcome"] == "validation_error":
        assert statuses == [422]
    else:
        assert 200 in statuses
    if expect["outcome"] == "clarification":
        assert expect.get("count_between") == [0, 0]
    # An empty label list means unannotated, never zero retrieval quality.
    labels = expect.get("relevant_poi_ids", [])
    assert isinstance(labels, list) and all(isinstance(value, str) and value for value in labels)
    assert len(labels) == len(set(labels))
    assert not any(value.startswith("test:") for value in labels), "Synthetic IDs must never label real retrieval quality"
    assert isinstance(case["scenario"], str) and case["scenario"].strip()
    assert isinstance(case["tags"], list) and case["tags"]


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_request_shape_matches_expected_validation_outcome(case):
    schema = json.loads((ROOT / "eval/schemas/request.schema.json").read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = list(validator.iter_errors(case["request"]))
    if case["expect"]["outcome"] == "validation_error":
        assert errors, f"{case['id']}: request schema accepts a case advertised as malformed"
    else:
        assert not errors, "\n".join(str(error) for error in errors)


def test_synthetic_reference_response_is_internally_consistent():
    from eval.validators import validate_pois, validate_response

    fixture_dir = ROOT / "tests/fixtures"
    pois = json.loads((fixture_dir / "pois_sample.json").read_text(encoding="utf-8"))
    request = json.loads((fixture_dir / "request_walk.json").read_text(encoding="utf-8"))
    response = json.loads((fixture_dir / "response_walk.json").read_text(encoding="utf-8"))
    assert not (errors := validate_pois(pois)), "\n".join(errors)
    assert not (errors := validate_response(response, request, pois)), "\n".join(errors)

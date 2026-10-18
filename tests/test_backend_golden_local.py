"""Existing goldens against the actual API with isolated offline fallback search.

The 17 backend POIs are controlled fixtures around the golden landmarks. These
tests exercise HTTP handling, rule/template fallback and existing independent
contract checks. They establish neither real RAG/model quality nor Recall,
current venue facts, prose faithfulness or RU/KK/EN language quality.
"""

from copy import deepcopy
import json
from pathlib import Path

import httpx
import pytest

from eval.validators import validate_pois, validate_response


ROOT = Path(__file__).resolve().parents[1]
CASES = json.loads((ROOT / "eval/golden_set.json").read_text(encoding="utf-8"))
EVIDENCE_MODE = "actual FastAPI; offline rule/template fallback; mock keyword search; controlled POIs"


def assert_golden_result(case, response, pois):
    """Apply the runner's HTTP and independent response checks without changes."""
    expected = case["expect"]
    policy_note = (" Empty/long-query limits require policy review."
                   if case["id"] in {"empty_query", "whitespace_query", "long_query_no_invented_limit"} else "")
    assert response.status_code in expected["status_codes"], (
        f"{case['id']}: HTTP {response.status_code}, expected {expected['status_codes']}. "
        "Golden expectations are unchanged." + policy_note
    )
    errors = validate_response(response.json(), case["request"], pois, expected)
    assert not errors, f"{case['id']}: " + "\n".join(errors)


@pytest.fixture
def golden_backend(qa_backend):
    # Load after qa_backend has verified that the backend checkout is present.
    # A QA-only branch must still collect its offline tests without that tree.
    pois = json.loads((ROOT / "backend/tests/fixtures/pois_sample.json").read_text(encoding="utf-8"))
    errors = validate_pois(pois)
    assert not errors, "Controlled fixture is invalid: " + "\n".join(errors)
    qa_backend.set_pois(pois)
    assert not qa_backend.llm.is_enabled(), "This suite must not enable model calls"
    assert qa_backend.rag.backend_name() == "mock", "This suite measures isolated fallback search"
    return qa_backend, pois


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_existing_golden_through_local_api(case, golden_backend, record_property):
    """Every existing case keeps its original request, status and expectations."""
    backend, pois = golden_backend
    record_property("evidence_mode", EVIDENCE_MODE)
    record_property("golden_id", case["id"])
    response = backend.client.post("/api/recommend", json=deepcopy(case["request"]))
    assert_golden_result(case, response, pois)


@pytest.mark.parametrize("mutation", ["foreign_poi", "wrong_http_status"])
def test_golden_harness_rejects_mutated_api_result(mutation, golden_backend):
    """Prove the harness rejects either mutation from a passing API baseline."""
    backend, all_pois = golden_backend
    # This existing central coffee case needs no Mega/airport candidates. Keep
    # one known-open cafe so route/search defects cannot mask the mutation.
    pois = [deepcopy(next(poi for poi in all_pois if poi["id"] == "fixture:cafe_center"))]
    backend.set_pois(pois)
    case = next(case for case in CASES if case["id"] == "group_five")
    response = backend.client.post("/api/recommend", json=deepcopy(case["request"]))
    assert_golden_result(case, response, pois)
    payload = deepcopy(response.json())
    assert payload["recommendations"], "Mutation must alter an actual recommendation"
    if mutation == "foreign_poi":
        payload["recommendations"][0]["poi_id"] = "fixture:foreign_not_in_dataset"
        changed = httpx.Response(response.status_code, json=payload)
        expected_message = "unknown POI ID fixture:foreign_not_in_dataset"
    else:
        changed = httpx.Response(422, json=payload)
        expected_message = "HTTP 422"
    with pytest.raises(AssertionError, match=expected_message):
        assert_golden_result(case, changed, pois)

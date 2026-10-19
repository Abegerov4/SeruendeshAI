"""Independent budget arithmetic and failing scenarios must reject bad evidence."""
import copy
import json
import sys
from pathlib import Path

import httpx

from ayat_backend.eval import run_eval

ROOT = Path(__file__).resolve().parents[2]


def response_fixture():
    return copy.deepcopy(json.loads((ROOT / "eval/runs/2026-10-19-branch-integration/http-smoke.json").read_text())["cases"][0]["response"])


def test_visit_time_is_part_of_alternative_budget():
    body = response_fixture()
    body["route"] = None
    body["used_context"]["time_budget_min"] = 10
    body["recommendations"] = body["recommendations"][:1]
    item = body["recommendations"][0]
    item.update(travel_min=1, visit_min=[120, 180], visit_suggested_min=120)
    checks = run_eval.run_checks({"expect": {}}, body, 1, {item["poi_id"]})
    assert checks["C1 schema"] is True
    assert checks["C4 time budget"] is False


def test_final_route_must_equal_its_card_visits_and_legs():
    body = response_fixture()
    fixture = json.loads((ROOT / "eval/runs/2026-10-19-system-audit/model-boundary-reproductions.json").read_text())["ayat_fake_route"]
    body["route"] = fixture["route"]
    by_id = {item["poi_id"]: item for item in fixture["items"]}
    first = copy.deepcopy(body["recommendations"][0])
    body["recommendations"] = [{**first, **item} for item in by_id.values()]
    body["used_context"]["time_budget_min"] = 90
    assert run_eval.run_checks({"expect": {}}, body, 1, set(by_id))["C4 time budget"] is False


def test_response_cannot_raise_the_original_request_budget():
    body = response_fixture()
    body["route"] = None
    body["used_context"]["time_budget_min"] = 165
    body["recommendations"] = body["recommendations"][:1]
    item = body["recommendations"][0]
    item.update(travel_min=1, visit_min=[25, 25], visit_suggested_min=25)
    assert run_eval.run_checks({"request": {"time_budget_min": 10}}, body, 1, {item["poi_id"]})["C4 time budget"] is False


def test_airport_return_is_part_of_each_alternative_budget():
    body = response_fixture()
    body["route"] = None
    body["used_context"]["time_budget_min"] = 30
    body["recommendations"] = body["recommendations"][:1]
    item = body["recommendations"][0]
    item.update(travel_min=10, visit_min=[15, 15], visit_suggested_min=15, return_min=20)
    assert run_eval.run_checks({}, body, 1, {item["poi_id"]})["C4 time budget"] is False


def test_zero_scenario_budget_is_an_enforced_bound():
    body = response_fixture()
    body.update(recommendations=[], route=None)
    body["used_context"]["time_budget_min"] = 60
    assert run_eval.run_checks({"expect": {"empty": True, "budget_max": 0}}, body, 1, set())["C4 time budget"] is False


def test_http_failure_makes_scenario_cli_fail(monkeypatch, tmp_path):
    (tmp_path / "eval").mkdir()
    (tmp_path / "eval/scenarios.yaml").write_text('- id: failing\n  title: local error\n  request: {query: local}\n  expect: {}\n')
    monkeypatch.setattr(run_eval, "ROOT", tmp_path)
    real_client = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda *a, **kw: real_client(
        *a, **kw, transport=httpx.MockTransport(lambda request: httpx.Response(500, json={"error": "local failure"}))))
    monkeypatch.setattr(sys, "argv", ["run_eval", "--base-url", "http://local.test", "--no-llm", "--out", str(tmp_path / "result.md")])
    assert run_eval.main() == 1
    result = json.loads((tmp_path / "eval/results.json").read_text())
    assert result[0]["checks"]["C1 schema"] is False

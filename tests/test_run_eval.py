"""Transport fixtures test QA plumbing; none are product execution evidence."""
import importlib
import json
import subprocess
import sys
from pathlib import Path

import httpx
import pytest


ROOT = Path(__file__).resolve().parents[1]


def inputs(tmp_path):
    poi = {
        "id": "synthetic:park-1", "name": "Synthetic Park", "name_en": "Synthetic Park",
        "name_kk": None, "lat": 51.1, "lon": 71.4, "category": "park",
        "tags": [], "description": "A synthetic park.", "description_source": "osm",
        "address": None, "opening_hours": None, "phone": None, "website": None,
        "rating": None, "rating_count": None, "wheelchair": None,
        "kid_friendly": None, "source": "synthetic", "source_url": "https://example.com/synthetic/park-1",
        "updated_at": "2026-10-18",
    }
    request = {"query": "Synthetic walk", "location": {"lat": 51.1, "lon": 71.4},
               "time_budget_min": 60, "mode": "walk", "lang": "en"}
    case = {"id": "synthetic-walk", "scenario": "Synthetic ordinary walk", "request": request,
            "expect": {"status_codes": [200], "outcome": "recommendations",
                       "count_between": [1, 3], "relevant_poi_ids": []}, "tags": ["synthetic"]}
    pois_path = tmp_path / "pois.json"
    cases_path = tmp_path / "cases.json"
    pois_path.write_text(json.dumps([poi]))
    cases_path.write_text(json.dumps([case]))
    payload = {"request_id": "synthetic-run", "used_context": {
        "location_source": "gps_rounded", "location_label": "Synthetic origin", "radius_m": 1000,
        "time_budget_min": 60, "mode": "walk", "filters": [], "now": "2026-10-18T12:00:00+05:00"},
        "recommendations": [{"poi_id": poi["id"], "name": poi["name"], "category": "park",
            "lat": poi["lat"], "lon": poi["lon"], "distance_m": 0, "travel_min": 0,
            "why": "Synthetic park from the source.", "visit_min": [10, 20],
            "what_to_do": "Walk.", "open_status": "unknown", "open_confidence": "none",
            "source": "poi_data", "source_url": poi["source_url"], "rating": None}],
        "route": None, "notes": ["Opening hours unknown."], "disclaimer": "Synthetic fixture only."}
    return pois_path, cases_path, payload


def run(tmp_path, handler, *, repeat=1, setup=None):
    module = importlib.import_module("eval.run_eval")
    pois, cases, payload = inputs(tmp_path)
    if setup:
        setup(cases, payload)
    with httpx.Client(transport=httpx.MockTransport(lambda request: handler(request, payload))) as client:
        code = module.main(["--base-url", "http://fixture.local", "--pois", str(pois),
                            "--cases", str(cases), "--output-dir", str(tmp_path / "run"),
                            "--repeat", str(repeat)], client=client)
    report = json.loads((tmp_path / "run/report.json").read_text())
    return code, report


def test_help_and_required_live_flags():
    help_result = subprocess.run([sys.executable, "-m", "eval.run_eval", "--help"], cwd=ROOT,
                                 text=True, capture_output=True)
    assert help_result.returncode == 0
    result = subprocess.run([sys.executable, "-m", "eval.run_eval"], cwd=ROOT,
                            text=True, capture_output=True)
    assert result.returncode != 0
    assert "--base-url" in result.stderr and "--pois" in result.stderr


def test_success_report_has_provenance_and_no_invented_quality(tmp_path):
    code, report = run(tmp_path, lambda request, payload: httpx.Response(200, json=payload), repeat=2)
    assert code == 0
    assert report["summary"]["attempted"] == report["summary"]["passed"] == 2
    assert report["summary"]["response_coverage"] == 1
    assert report["summary"]["hallucinated_ids"] == {"numerator": 0, "denominator": 2, "rate": 0}
    assert report["summary"]["final_recommendation_metrics"]["hit_at_3"] is None
    assert report["metadata"]["execution_kind"] == "fixture_transport"
    assert len(report["metadata"]["dataset_sha256"]) == 64
    assert len(report["metadata"]["scenario_sha256"]) == 64
    assert "git_head" in report["metadata"] and "git_dirty" in report["metadata"]
    assert report["metadata"]["model_label"]["source"] == "not_supplied"
    assert "faithfulness" in report["not_evaluated"]
    assert (tmp_path / "run/results.md").is_file()


@pytest.mark.parametrize("kind", ["http", "json", "network"])
def test_failed_attempts_have_latency_and_propagate_exit_without_secrets(tmp_path, kind):
    def handler(request, payload):
        if kind == "network":
            raise httpx.ConnectError("Authorization: secret-token", request=request)
        if kind == "json":
            return httpx.Response(200, text="secret-token is not json")
        return httpx.Response(503, text="Authorization: secret-token")
    code, report = run(tmp_path, handler, repeat=2)
    assert code != 0
    assert report["summary"]["attempted"] == report["summary"]["failed"] == 2
    assert report["summary"]["latency"]["sample_count"] == 2
    assert report["summary"]["hallucinated_ids"]["rate"] is None
    assert "secret-token" not in json.dumps(report)
    assert report["results"][0]["errors"]


def test_expected_422_passes_without_success_schema_validation(tmp_path):
    def setup(cases, payload):
        values = json.loads(cases.read_text())
        values[0]["expect"].update(status_codes=[422], outcome="validation_error")
        cases.write_text(json.dumps(values))
    code, report = run(tmp_path, lambda request, payload: httpx.Response(422, json={"detail": "invalid"}), setup=setup)
    assert code == 0
    assert report["summary"]["passed"] == 1
    assert report["summary"]["hallucinated_ids"]["denominator"] == 0
    assert report["summary"]["hallucinated_ids"]["rate"] is None


def test_empty_ordinary_response_fails_instead_of_improving_scores(tmp_path):
    def setup(cases, payload):
        payload["recommendations"] = []
    code, report = run(tmp_path, lambda request, payload: httpx.Response(200, json=payload), setup=setup)
    assert code != 0
    assert report["summary"]["hallucinated_ids"]["rate"] is None
    assert report["summary"]["recommendation_response_coverage"] == 0


def test_no_location_clarification_may_return_zero_with_useful_note(tmp_path):
    def setup(cases, payload):
        values = json.loads(cases.read_text())
        values[0]["request"]["location"] = None
        values[0]["expect"].update(outcome="clarification", count_between=[0, 3])
        cases.write_text(json.dumps(values))
        payload["recommendations"] = []
        payload["used_context"]["location_source"] = "unknown"
        payload["used_context"]["location_label"] = "Location unknown"
        payload["notes"] = ["Please provide your location or a nearby landmark."]
    code, report = run(tmp_path, lambda request, payload: httpx.Response(200, json=payload), setup=setup)
    assert code == 0
    assert report["summary"]["recommendation_response_coverage"] == 0


def test_final_metrics_are_labeled_at_3_and_only_use_annotated_cases(tmp_path):
    def setup(cases, payload):
        values = json.loads(cases.read_text())
        values[0]["expect"]["relevant_poi_ids"] = ["synthetic:park-1", "synthetic:park-2"]
        cases.write_text(json.dumps(values))
    code, report = run(tmp_path, lambda request, payload: httpx.Response(200, json=payload), setup=setup)
    metrics = report["summary"]["final_recommendation_metrics"]
    assert code == 0
    assert metrics["hit_at_3"] == 1 and metrics["recall_at_3"] == .5
    assert metrics["annotated_attempts"] == 1
    assert "retrieval_at_5" not in report["summary"]


def test_malformed_case_is_reported_as_unexecuted_without_disappearing(tmp_path):
    def setup(cases, payload):
        values = json.loads(cases.read_text())
        values.append({"id": "broken", "request": "not-an-object"})
        cases.write_text(json.dumps(values))
    code, report = run(tmp_path, lambda request, payload: httpx.Response(200, json=payload), setup=setup)
    assert code != 0
    assert report["summary"]["planned"] == 2
    assert report["summary"]["attempted"] == 1
    assert report["summary"]["unexecuted"] == 1


@pytest.mark.parametrize("repeat", ["0", "-1"])
def test_nonpositive_repeat_rejected_before_network(tmp_path, repeat):
    result = subprocess.run([sys.executable, "-m", "eval.run_eval", "--base-url", "http://localhost",
        "--pois", "missing.json", "--output-dir", str(tmp_path), "--repeat", repeat],
        cwd=ROOT, text=True, capture_output=True)
    assert result.returncode != 0
    assert "positive" in result.stderr

@pytest.mark.parametrize("payload", [None, [], {"recommendations": {}},
    {"recommendations": [{"poi_id": []}]}, {"recommendations": [{"poi_id": ""}]}])
def test_malformed_response_is_failure_with_report_not_a_crash(tmp_path, payload):
    code, report = run(tmp_path, lambda request, unused: httpx.Response(200, json=payload))
    assert code != 0
    assert report["summary"]["attempted"] == report["summary"]["failed"] == 1
    assert report["summary"]["hallucinated_ids"]["rate"] is None
    assert report["results"][0]["errors"]


def test_bad_label_case_and_bool_status_are_reported_unexecuted(tmp_path):
    def setup(cases, payload):
        values = json.loads(cases.read_text())
        values[0]["expect"]["relevant_poi_ids"] = [""]
        values[0]["expect"]["status_codes"] = [True]
        cases.write_text(json.dumps(values))
    code, report = run(tmp_path, lambda request, payload: httpx.Response(200, json=payload), setup=setup)
    assert code != 0
    assert report["summary"]["unexecuted"] == 1
    assert report["summary"]["attempted"] == 0
    assert "nonempty" in " ".join(report["results"][0]["errors"])


def test_missing_input_writes_failure_report_without_network(tmp_path):
    module = importlib.import_module("eval.run_eval")
    output = tmp_path / "run"
    code = module.main(["--base-url", "http://localhost:1", "--pois", str(tmp_path / "missing"),
                        "--cases", str(tmp_path / "absent"), "--output-dir", str(output)])
    assert code != 0
    report = json.loads((output / "report.json").read_text())
    assert report["passed"] is False
    assert report["input_errors"]
    assert report["summary"]["latency"]["sample_count"] == 0

@pytest.mark.parametrize("payload", [None, {"oops": "yes"}, {"detail": ""}])
def test_expected_422_requires_actionable_detail(tmp_path, payload):
    def setup(cases, unused):
        values = json.loads(cases.read_text())
        values[0]["expect"].update(status_codes=[422], outcome="validation_error")
        cases.write_text(json.dumps(values))
    code, report = run(tmp_path, lambda request, unused: httpx.Response(422, content=json.dumps(payload)), setup=setup)
    assert code != 0
    assert report["summary"]["failed"] == 1
    assert "detail" in " ".join(report["results"][0]["errors"])


def test_review_packets_are_opt_in_and_do_not_change_evaluated_metrics(tmp_path):
    module = importlib.import_module("eval.run_eval")
    pois, cases, payload = inputs(tmp_path)
    payload["api_key"] = "secret-never-save"
    # Forbidden source text is evaluated unchanged, then removed from review exports.
    values = json.loads(cases.read_text())
    values[0]["expect"]["forbidden_output"] = ["secret-never-save"]
    cases.write_text(json.dumps(values))
    payload["notes"] = ["Authorization: secret-never-save"]
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))) as client:
        output = tmp_path / "review"
        code = module.main(["--base-url", "http://fixture.local", "--pois", str(pois), "--cases", str(cases),
                            "--output-dir", str(output), "--review-packets"], client=client)
    report = json.loads((output / "report.json").read_text())
    packet_path = output / "review_packets/0001-repeat-1.json"
    assert packet_path.is_file()
    packet = json.loads(packet_path.read_text())
    assert packet["response"]["recommendations"][0]["why"] == payload["recommendations"][0]["why"]
    assert packet["pois"][0]["id"] == payload["recommendations"][0]["poi_id"]
    assert "secret-never-save" not in packet_path.read_text()
    assert "secret-never-save" not in json.dumps(report)
    assert code != 0  # original forbidden prose still fails before export sanitization
    assert report["summary"]["failed"] == 1
    assert report["metadata"]["corpus_scope"] == "operator_supplied_unverified"
    assert "query" not in json.dumps(report)


def test_hash_permission_failure_becomes_reported_input_error(tmp_path, monkeypatch):
    module = importlib.import_module("eval.run_eval")
    def unreadable(path):
        raise PermissionError("secret-never-save")
    monkeypatch.setattr(module, "file_sha256", unreadable)
    code, report = run(tmp_path, lambda request, payload: httpx.Response(200, json=payload))
    assert code != 0
    assert report["input_errors"]
    assert report["summary"]["unexecuted"] == 1
    assert "secret-never-save" not in json.dumps(report)


def test_unsupported_expected_error_status_cannot_bypass_forbidden_checks(tmp_path):
    def setup(cases, payload):
        values = json.loads(cases.read_text())
        values[0]["expect"].update(status_codes=[403], outcome="rejection", forbidden_output=["QA_CANARY"])
        cases.write_text(json.dumps(values))
    code, report = run(tmp_path, lambda request, payload: httpx.Response(403, json={"error": "QA_CANARY"}), setup=setup)
    assert code != 0
    assert report["summary"]["unexecuted"] == 1
    assert "unsupported" in " ".join(report["results"][0]["errors"]).lower()


def test_expected_422_still_checks_decoded_forbidden_text(tmp_path):
    def setup(cases, payload):
        values = json.loads(cases.read_text())
        values[0]["expect"].update(status_codes=[422], outcome="validation_error", forbidden_output=["QA_CANARY"])
        cases.write_text(json.dumps(values))
    code, report = run(tmp_path, lambda request, payload: httpx.Response(422, content='{"detail":"QA_\\u0043ANARY"}'), setup=setup)
    assert code != 0
    assert report["summary"]["failed"] == 1


@pytest.mark.parametrize("outcome", [[], {}, 1, None])
def test_malformed_outcome_is_unexecuted_with_failure_report(tmp_path, outcome):
    def setup(cases, payload):
        values = json.loads(cases.read_text())
        values[0]["expect"]["outcome"] = outcome
        cases.write_text(json.dumps(values))
    code, report = run(tmp_path, lambda request, payload: httpx.Response(200, json=payload), setup=setup)
    assert code != 0
    assert report["summary"]["unexecuted"] == 1
    assert report["summary"]["attempted"] == 0


def test_originless_landmark_response_reports_geometry_omissions(tmp_path):
    def setup(cases, payload):
        values = json.loads(cases.read_text())
        values[0]["request"].update(location=None, query="Synthetic landmark walk")
        cases.write_text(json.dumps(values))
        payload["used_context"]["location_source"] = "landmark"
    code, report = run(tmp_path, lambda request, payload: httpx.Response(200, json=payload), setup=setup)
    assert code == 0
    result = report["results"][0]
    assert result["checks"]["origin_distance"] == "not_evaluated"
    assert result["checks"]["first_leg_geometry"] == "not_evaluated"
    text = (tmp_path / "run/results.md").read_text()
    assert "synthetic-walk" in text and "origin_distance" in text and "first_leg_geometry" in text
    assert "no independent origin" in text.lower()


@pytest.mark.parametrize("location", [{"lat": True, "lon": 71.4}, {"lat": 91, "lon": 71.4},
    {"lat": 51.1, "lon": -181}, {"lat": "51.1", "lon": 71.4}])
def test_success_scenario_requires_valid_json_origin_coordinates(tmp_path, location):
    def setup(cases, payload):
        values = json.loads(cases.read_text())
        values[0]["request"]["location"] = location
        cases.write_text(json.dumps(values))
    code, report = run(tmp_path, lambda request, payload: httpx.Response(200, json=payload), setup=setup)
    assert code != 0
    assert report["summary"]["unexecuted"] == 1
    assert report["results"][0]["checks"]["origin_distance"] == "not_evaluated"


def test_geometry_is_not_applicable_to_422_even_with_invalid_coordinates(tmp_path):
    def setup(cases, payload):
        values = json.loads(cases.read_text())
        values[0]["request"]["location"] = {"lat": True, "lon": 999}
        values[0]["expect"].update(status_codes=[422], outcome="validation_error")
        cases.write_text(json.dumps(values))
    code, report = run(tmp_path, lambda request, payload: httpx.Response(422, json={"detail": "invalid coordinates"}), setup=setup)
    assert code == 0
    assert report["results"][0]["checks"]["origin_distance"] == "not_applicable"
    assert report["results"][0]["checks"]["first_leg_geometry"] == "not_applicable"


def test_latency_stops_before_response_validation(tmp_path, monkeypatch):
    module = importlib.import_module("eval.run_eval")
    validators = importlib.import_module("eval.validators")
    clock = [100.0]
    monkeypatch.setattr(module.time, "perf_counter", lambda: clock[0])
    validate = validators.validate_response
    def delayed_validation(*args):
        clock[0] += 1.0
        return validate(*args)
    monkeypatch.setattr(validators, "validate_response", delayed_validation)
    def handler(request, payload):
        clock[0] += .02
        return httpx.Response(200, json=payload)
    code, report = run(tmp_path, handler)
    assert code == 0
    assert report["results"][0]["latency_ms"] == 20
    assert report["summary"]["latency"]["p95_ms"] == 20


def test_deep_response_json_fails_safely_and_later_attempt_continues(tmp_path):
    deep = "[" * 10000 + '"Authorization: secret-depth"' + "]" * 10000
    calls = []
    def handler(request, payload):
        calls.append(1)
        return httpx.Response(200, text=deep) if len(calls) == 1 else httpx.Response(200, json=payload)
    code, report = run(tmp_path, handler, repeat=2)
    assert code != 0
    assert report["summary"]["attempted"] == 2
    assert report["summary"]["failed"] == report["summary"]["passed"] == 1
    assert "secret-depth" not in json.dumps(report)

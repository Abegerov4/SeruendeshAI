import importlib
import json
from pathlib import Path

import pytest


def test_absent_product_and_evidence_are_nonzero_with_json_and_markdown(tmp_path):
    module = importlib.import_module("eval.check_readiness")
    output = tmp_path / "qa/readiness.md"
    assert module.main(["--root", str(tmp_path), "--output", str(output)]) != 0
    report = json.loads(output.with_suffix(".json").read_text())
    assert report["ready"] is False
    states = {check["name"]: check["status"] for check in report["checks"]}
    assert states["backend"] == states["rag"] == states["frontend"] == states["dataset"] == "missing"
    assert states["live_evaluation"] == "pending"
    assert "presence" in output.read_text().lower()
    assert "privacy" in " ".join(report["not_verified"]).lower()


def test_files_alone_do_not_establish_execution(tmp_path):
    module = importlib.import_module("eval.check_readiness")
    for name in ["backend/app/main.py", "rag/retriever.py", "frontend/package.json", "data/processed/pois.json"]:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("[]" if path.suffix == ".json" else "# Placeholder")
    report = module.check_readiness(tmp_path)
    assert not report["ready"]
    assert next(c for c in report["checks"] if c["name"] == "backend")["scope"] == "presence_only"
    assert next(c for c in report["checks"] if c["name"] == "live_evaluation")["status"] == "pending"


def test_fixture_or_stale_evidence_never_passes(tmp_path):
    module = importlib.import_module("eval.check_readiness")
    evidence = tmp_path / "report.json"
    evidence.write_text(json.dumps({"metadata": {"execution_kind": "fixture_transport", "model_label": {
        "value": "mock-model", "source": "user_supplied"}}, "summary": {"planned": 1, "passed": 1}}))
    report = module.check_readiness(tmp_path, evidence=evidence)
    check = next(c for c in report["checks"] if c["name"] == "live_evaluation")
    assert check["status"] == "failed"
    assert "fixture" in check["detail"].lower()
    assert not report["ready"]


def test_bad_evidence_json_is_a_reported_failure_not_a_crash(tmp_path):
    module = importlib.import_module("eval.check_readiness")
    evidence = tmp_path / "broken.json"
    evidence.write_text("invalid")
    output = tmp_path / "readiness.md"
    assert module.main(["--root", str(tmp_path), "--output", str(output), "--evidence", str(evidence)]) != 0
    assert "invalid JSON" in output.read_text()


def test_legitimate_non_osm_namespace_is_not_rejected_as_fixture(tmp_path):
    module = importlib.import_module("eval.check_readiness")
    fixture = Path(__file__).parent / "fixtures/pois_sample.json"
    template = json.loads(fixture.read_text())[0]
    dataset = [{**template, "id": f"official:venue-{index}", "source": "city_open_data", "source_url": "https://city.example.kz/venues/1"} for index in range(300)]
    path = tmp_path / "data/processed/pois.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(dataset))
    report = module.check_readiness(tmp_path)
    check = next(item for item in report["checks"] if item["name"] == "dataset_contract")
    # Only namespace/contract acceptance; these synthetic test rows are never real readiness evidence.
    assert check["status"] == "passed"
    assert report["ready"] is False


def test_uncommitted_source_change_invalidates_execution_evidence(tmp_path, monkeypatch):
    module = importlib.import_module("eval.check_readiness")
    runner = importlib.import_module("eval.run_eval")
    source = tmp_path / "backend/app/main.py"
    source.parent.mkdir(parents=True)
    source.write_text("# original source")
    pois, cases, evidence = [tmp_path / name for name in ("pois.json", "cases.json", "report.json")]
    pois.write_text("[]")
    cases.write_text(json.dumps([{"id": "case-1", "scenario": "Synthetic evidence", "request": {"query": "Synthetic", "location": {"lat": 51.1, "lon": 71.4}},
        "expect": {"outcome": "recommendations", "status_codes": [200]}, "tags": ["synthetic"]}]))
    state = {"git_head": "abc123", "git_dirty": True}
    monkeypatch.setattr(module, "git_state", lambda root: state)
    report = {"passed": True, "input_errors": [], "metadata": {**state,
        "source_sha256": runner.source_fingerprint(tmp_path), "execution_kind": "live_http",
        "base_url": "http://127.0.0.1:8000", "model_label": {"value": "model-x", "source": "user_supplied"},
        "repeat": 1, "dataset_sha256": runner.file_sha256(pois), "scenario_sha256": runner.file_sha256(cases)},
        "summary": {"planned": 1, "attempted": 1, "passed": 1, "failed": 0, "unexecuted": 0},
        "results": [{"case_id": "case-1", "repeat": 1, "executed": True, "passed": True,
            "http_status": 200, "errors": [], "latency_ms": 12, "recommendation_count": 1,
            "checks": {"schema_and_semantic": "passed", "http_status": "passed", "origin_distance": "passed", "first_leg_geometry": "passed"}}]}
    evidence.write_text(json.dumps(report))
    assert module._evidence_errors(evidence, tmp_path, pois, cases) == []
    report["results"][0]["case_id"] = "wrong-case"
    evidence.write_text(json.dumps(report))
    assert "identity" in " ".join(module._evidence_errors(evidence, tmp_path, pois, cases)).lower()
    report["results"][0]["case_id"] = "case-1"
    evidence.write_text(json.dumps(report))
    source.write_text("# source changed while HEAD and dirty flag stayed the same")
    assert "source" in " ".join(module._evidence_errors(evidence, tmp_path, pois, cases)).lower()


def test_unreadable_provenance_file_still_produces_readiness_report(tmp_path, monkeypatch):
    module = importlib.import_module("eval.check_readiness")
    pois, cases, evidence = [tmp_path / name for name in ("pois.json", "cases.json", "report.json")]
    pois.write_text("[]")
    cases.write_text("[]")
    evidence.write_text(json.dumps({"metadata": {"execution_kind": "live_http"}, "summary": {}}))
    def denied(path):
        raise PermissionError("Authorization: secret-not-output")
    monkeypatch.setattr(module, "file_sha256", denied)
    output = tmp_path / "readiness.md"
    code = module.main(["--root", str(tmp_path), "--evidence", str(evidence), "--pois", str(pois),
                        "--cases", str(cases), "--output", str(output)])
    assert code != 0
    report = json.loads(output.with_suffix(".json").read_text())
    check = next(item for item in report["checks"] if item["name"] == "live_evaluation")
    assert "could not be read" in check["detail"]
    assert "secret-not-output" not in json.dumps(report)


@pytest.mark.parametrize("bad_result", [
    {"http_status": None}, {"http_status": 422}, {"http_status": True},
    {"errors": ["not actually checked"]}, {"errors": None},
    {"checks": {"schema_and_semantic": "not_evaluated"}},
    {"latency_ms": None}, {"latency_ms": True}, {"latency_ms": -1}, {"latency_ms": float("nan")},
    {"repeat": True},
])
def test_per_attempt_evidence_must_contain_real_completed_checks(tmp_path, monkeypatch, bad_result):
    module = importlib.import_module("eval.check_readiness")
    runner = importlib.import_module("eval.run_eval")
    pois, cases, evidence = [tmp_path / name for name in ("pois.json", "cases.json", "report.json")]
    pois.write_text("[]")
    cases.write_text(json.dumps([{"id": "case-1", "scenario": "Synthetic evidence", "request": {
        "query": "Synthetic", "location": {"lat": 51.1, "lon": 71.4}},
        "expect": {"outcome": "recommendations", "status_codes": [200]}, "tags": ["synthetic"]}]))
    state = {"git_head": "abc123", "git_dirty": True}
    monkeypatch.setattr(module, "git_state", lambda root: state)
    result = {"case_id": "case-1", "repeat": 1, "executed": True, "passed": True, "http_status": 200,
        "errors": [], "latency_ms": 12, "recommendation_count": 1,
        "checks": {"schema_and_semantic": "passed", "http_status": "passed", "origin_distance": "passed", "first_leg_geometry": "passed"}}
    result.update(bad_result)
    report = {"passed": True, "input_errors": [], "metadata": {**state,
        "source_sha256": runner.source_fingerprint(tmp_path), "execution_kind": "live_http",
        "base_url": "http://127.0.0.1:8000", "model_label": {"value": "model-x", "source": "user_supplied"},
        "repeat": 1, "dataset_sha256": runner.file_sha256(pois), "scenario_sha256": runner.file_sha256(cases)},
        "summary": {"planned": 1, "attempted": 1, "passed": 1, "failed": 0, "unexecuted": 0}, "results": [result]}
    evidence.write_text(json.dumps(report))
    assert module._evidence_errors(evidence, tmp_path, pois, cases)

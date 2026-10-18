import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]


def source_packet(tmp_path):
    path = tmp_path / "packet.json"
    path.write_text(json.dumps({"request": {"query": "Synthetic park"},
        "response": {"recommendations": [{"poi_id": "synthetic:1", "why": "A park."}]},
        "pois": [{"id": "synthetic:1", "name": "Synthetic park", "description": "A park."}]}))
    return path


def test_judge_defaults_to_preparation_without_secret_or_http(tmp_path):
    module = importlib.import_module("eval.judge")
    path = source_packet(tmp_path)
    output = tmp_path / "judge.json"
    assert module.main(["--packet", str(path), "--output", str(output)]) == 0
    report = json.loads(output.read_text())
    assert report["status"] == "not_executed"
    assert report["scores"] is None
    assert "human" in report["limitations"].lower()


@pytest.mark.parametrize("scores", [
    {"faithfulness": 0, "relevancy": 5, "explanation_quality": 5},
    {"faithfulness": True, "relevancy": 5, "explanation_quality": 5},
    {"faithfulness": 5, "relevancy": 5},
    {"faithfulness": 5.0, "relevancy": 5, "explanation_quality": 5},
])
def test_judge_rejects_missing_out_of_range_and_noninteger_scores(scores):
    module = importlib.import_module("eval.judge")
    assert module.validate_scores(scores)


def test_judge_explicit_call_sends_only_bounded_packet_and_validates_scores(tmp_path, monkeypatch):
    module = importlib.import_module("eval.judge")
    packet = source_packet(tmp_path)
    output = tmp_path / "judge.json"
    monkeypatch.setenv("QA_TEST_JUDGE_KEY", "private-api-token")
    sent = []
    def handler(request):
        sent.append(json.loads(request.content))
        scores = {"faithfulness": 4, "relevancy": 3, "explanation_quality": 5}
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(scores)}}]})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        code = module.main(["--execute", "--packet", str(packet), "--output", str(output),
            "--api-base", "http://fixture.local/v1", "--model", "fixture-judge",
            "--key-env", "QA_TEST_JUDGE_KEY"], client=client)
    assert code == 0
    report = json.loads(output.read_text())
    assert report["scores"]["faithfulness"] == 4
    assert report["metadata"]["execution_kind"] == "fixture_transport"
    assert "private-api-token" not in output.read_text()
    assert "untrusted" in sent[0]["messages"][0]["content"].lower()
    assert "new facts" in sent[0]["messages"][0]["content"].lower()


def test_invalid_judge_output_fails_without_raw_body_or_key(tmp_path, monkeypatch):
    module = importlib.import_module("eval.judge")
    monkeypatch.setenv("QA_TEST_JUDGE_KEY", "private-api-token")
    output = tmp_path / "judge.json"
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, text="private-api-token"))) as client:
        assert module.main(["--execute", "--packet", str(source_packet(tmp_path)), "--output", str(output),
            "--api-base", "http://fixture.local/v1", "--model", "fixture-judge",
            "--key-env", "QA_TEST_JUDGE_KEY"], client=client) != 0
    report = json.loads(output.read_text())
    assert report["status"] == "failed"
    assert report["scores"] is None
    assert "private-api-token" not in output.read_text()


def test_execute_requires_explicit_configuration_before_network(tmp_path):
    result = subprocess.run([sys.executable, "-m", "eval.judge", "--execute", "--packet",
        str(source_packet(tmp_path)), "--output", str(tmp_path / "judge.json")], cwd=ROOT,
        capture_output=True, text=True)
    assert result.returncode != 0
    assert "--api-base" in result.stderr and "--model" in result.stderr and "--key-env" in result.stderr


@pytest.mark.parametrize("location", ["envelope", "content", "source"])
def test_deep_json_is_sanitized_judge_failure(tmp_path, monkeypatch, location):
    module = importlib.import_module("eval.judge")
    deep = "[" * 10000 + '"Authorization: secret-depth"' + "]" * 10000
    packet = source_packet(tmp_path)
    if location == "source":
        packet.write_text(deep)
    output = tmp_path / "judge.json"
    monkeypatch.setenv("QA_TEST_JUDGE_KEY", "private-api-token")
    def handler(request):
        if location == "envelope":
            return httpx.Response(200, text=deep)
        return httpx.Response(200, json={"choices": [{"message": {"content": deep}}]})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        code = module.main(["--execute", "--packet", str(packet), "--output", str(output),
            "--api-base", "http://fixture.local/v1", "--model", "fixture-judge", "--key-env", "QA_TEST_JUDGE_KEY"], client=client)
    assert code != 0
    report = json.loads(output.read_text())
    assert report["status"] == "failed" and report["scores"] is None
    assert "secret-depth" not in output.read_text() and "private-api-token" not in output.read_text()

"""Model readiness requires each application's accepted schema, not just JSON."""
import json

import httpx
from openai import OpenAI

from backend.app import generate, intent, llm
from runtime_support.provider_health import ProbeState


def sdk_for(monkeypatch, payload):
    def handle(request):
        return httpx.Response(200, json={"id": "local", "object": "chat.completion", "created": 0,
            "model": json.loads(request.content)["model"], "choices": [{"index": 0,
            "message": {"role": "assistant", "content": json.dumps(payload)}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}})
    http = httpx.Client(transport=httpx.MockTransport(handle))
    sdk = OpenAI(api_key="local-test-only", http_client=http, max_retries=0)
    monkeypatch.setattr(llm, "_client", lambda: sdk)
    monkeypatch.setattr(llm, "_probes", ProbeState())
    return http


def test_schema_invalid_role_responses_cannot_produce_verified_health(monkeypatch):
    with sdk_for(monkeypatch, {"categories": 1, "recommendations": "bad"}):
        assert intent.llm_intent("local query") is None
        assert generate.llm_generate("local query", intent.Intent(), [], None) is None
        assert llm.provider_status()["status"] == "degraded"
        assert llm.provider_status()["verified_at"] is None


def test_schema_valid_roles_establish_verified_health(monkeypatch):
    with sdk_for(monkeypatch, {"categories": ["cafe"], "recommendations": []}):
        assert intent.llm_intent("local query") is not None
        assert llm.provider_status()["status"] == "configured"
        assert generate.llm_generate("local query", intent.Intent(), [], None)[0] == []
        assert llm.provider_status()["status"] == "ok"
        assert llm.provider_status()["verified_at"]


def test_valid_unrelated_model_override_does_not_verify_configured_chain(monkeypatch):
    with sdk_for(monkeypatch, {"categories": ["cafe"], "recommendations": []}):
        assert intent.llm_intent("local query") is not None
        with llm.override_decision_model("review-only-unconfigured-model"):
            assert generate.llm_generate("local query", intent.Intent(), [], None)[0] == []
        assert llm.provider_status()["status"] == "configured"
        assert llm.provider_status()["verified_at"] is None


def test_unknown_candidate_ids_cannot_establish_generation_role_proof(monkeypatch):
    payload = {"categories": ["cafe"], "recommendations": [{"poi_id": "invented:unknown", "why": "Text",
               "visit_min": [5, 10], "what_to_do": "Read"}]}
    with sdk_for(monkeypatch, payload):
        assert intent.llm_intent("local query") is not None
        assert generate.llm_generate("local query", intent.Intent(), [], None) is None
        assert llm.provider_status()["status"] == "degraded"

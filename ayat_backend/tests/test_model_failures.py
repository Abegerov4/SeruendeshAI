"""The real SDK parses local transports; malformed model data must reach fallback."""
import asyncio
import json

import httpx
import pytest
from openai import AsyncOpenAI
from pydantic import BaseModel

from ayat_backend.app import llm


class SmallAnswer(BaseModel):
    summary: str


def response(text, *, status="completed", refusal=False):
    content = ({"type": "refusal", "refusal": "Cannot answer"} if refusal else
               {"type": "output_text", "text": text, "annotations": []})
    return {
        "id": "resp_local_test", "object": "response", "created_at": 0,
        "model": "local_test_model", "status": status,
        "incomplete_details": {"reason": "max_output_tokens"} if status == "incomplete" else None,
        "output": [{"type": "message", "id": "msg_local_test", "role": "assistant",
                    "status": status, "content": [content]}],
        "parallel_tool_calls": False, "tool_choice": "auto", "tools": [],
    }


@pytest.mark.parametrize("first", [
    response('{"summary":', status="incomplete"),
    response('{"summary": []}'),
    response("", refusal=True),
], ids=["truncated-incomplete", "wrong-schema", "refusal"])
def test_invalid_structured_output_tries_next_model(monkeypatch, first):
    requests = []

    def handle(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json=first if len(requests) == 1 else response('{"summary":"ok"}'))

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
            sdk = AsyncOpenAI(api_key="local-test-key", http_client=http, max_retries=0)
            monkeypatch.setattr(llm, "client", lambda: sdk)
            result, model, _ = await llm.parse(SmallAnswer, "local", "local", models=["test-a", "test-b"], timeout_s=3)
            assert result.summary == "ok"
            assert model == "test-b"

    asyncio.run(run())
    assert [request["model"] for request in requests] == ["test-a", "test-b"]


def test_all_invalid_models_return_none_for_template_fallback(monkeypatch):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json=response('{"summary":')))) as http:
            sdk = AsyncOpenAI(api_key="local-test-key", http_client=http, max_retries=0)
            monkeypatch.setattr(llm, "client", lambda: sdk)
            parsed, model, elapsed = await llm.parse(SmallAnswer, "local", "local", models=["test-a"], timeout_s=3)
            assert parsed is None and model is None
            assert 0 <= elapsed < 3000

    asyncio.run(run())


@pytest.mark.parametrize("status", [402, 409, 422])
def test_other_provider_status_errors_reach_template_fallback(monkeypatch, status):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(
                lambda request: httpx.Response(status, json={"error": {"message": "local provider error", "type": "invalid_request_error"}}))) as http:
            sdk = AsyncOpenAI(api_key="local-test-key", http_client=http, max_retries=0)
            monkeypatch.setattr(llm, "client", lambda: sdk)
            parsed, model, _ = await llm.parse(SmallAnswer, "local", "local", models=["test-a"], timeout_s=3)
            assert parsed is None and model is None
    asyncio.run(run())


def test_changed_credentials_replace_the_cached_client(monkeypatch):
    from types import SimpleNamespace
    settings = SimpleNamespace(openai_api_key="local-first-key", llm_enabled=True,
                               llm_parse_model="test", llm_chain=["test"], llm_service_tier="", llm_timeout_s=1)
    created = []
    def construct(**kwargs):
        value = SimpleNamespace(api_key=kwargs["api_key"])
        created.append(value)
        return value
    monkeypatch.setattr(llm, "get_settings", lambda: settings)
    monkeypatch.setattr(llm, "_client", None)
    monkeypatch.setattr(llm, "AsyncOpenAI", construct)
    assert llm.client().api_key == "local-first-key"
    settings.openai_api_key = "local-second-key"
    assert llm.client().api_key == "local-second-key"
    assert len(created) == 2

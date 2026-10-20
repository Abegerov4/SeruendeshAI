"""Langfuse tracing stays off without keys and never carries the photo or the user's position."""
from app import llm, tracing
from app.schemas import RecommendRequest
from app.service import _trace_request


def test_tracing_is_a_noop_without_keys():
    assert not tracing.is_enabled()
    with tracing.request("recommend", input={"query": "кофе"}) as root, \
            tracing.observe("rank-candidates", as_type="retriever") as step:
        root.update(output={"ok": True})
        step.update(output=[])
    tracing.update_current(metadata={"cache": "hit"})
    tracing.flush()


def test_photo_is_not_sent_to_tracing():
    msgs = [{"role": "system", "content": "sys"},
            {"role": "user", "content": [{"type": "input_text", "text": "PLACES"},
                                         {"type": "input_image", "image_url": "data:image/jpeg;base64,AAAA", "detail": "low"}]}]
    out = llm._trace_input(msgs)
    assert "base64" not in str(out)
    assert out[1]["content"][0] == {"type": "input_text", "text": "PLACES"}
    assert msgs[1]["content"][1]["image_url"].startswith("data:")  # the model still gets the photo


def test_trace_request_has_no_position_or_pii():
    req = RecommendRequest(query="кофе, звоните +77011234567", location={"lat": 51.128, "lon": 71.43}, lang="ru",
                           home={"lat": 51.1, "lon": 71.4, "label": "дом"})
    inp, meta, tags = _trace_request(req)
    text = str((inp, meta, tags))
    assert "77011234567" not in text and "51.128" not in text and "71.4" not in text
    assert meta["origin"] == "gps" and "channel:web" in tags


def test_generations_record_billed_usage_only(monkeypatch):
    """A failed attempt is a WARNING with zero usage (else Langfuse estimates phantom tokens); a success has
    the provider's tokens and our cost."""
    import asyncio
    import contextlib

    import httpx
    from openai import AsyncOpenAI
    from pydantic import BaseModel

    from .test_model_failures import response

    class Answer(BaseModel):
        summary: str

    steps = []

    class Step:
        def __init__(self, name, kw):
            self.rec = {"name": name, **kw}
            steps.append(self.rec)

        def update(self, **kw):
            self.rec.update(kw)

    @contextlib.contextmanager
    def observe(name, *, as_type="span", **kw):
        yield Step(name, {"as_type": as_type, **kw})

    monkeypatch.setattr(tracing, "observe", observe)
    ok = {**response('{"summary":"ok"}'), "usage": {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120,
                                                     "input_tokens_details": {"cached_tokens": 0},
                                                     "output_tokens_details": {"reasoning_tokens": 0}}}
    calls = []

    def handle(request):
        calls.append(1)
        return httpx.Response(500, json={"error": {"message": "down"}}) if len(calls) == 1 else httpx.Response(200, json=ok)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
            sdk = AsyncOpenAI(api_key="local-test-key", http_client=http, max_retries=0)
            monkeypatch.setattr(llm, "client", lambda: sdk)
            return await llm.parse(Answer, "sys", "user", models=["gpt-6-luna", "gpt-4.1-mini"], timeout_s=5,
                                   name="write-recommendations")

    parsed, model, _ = asyncio.run(run())
    assert parsed.summary == "ok" and model == "gpt-4.1-mini"
    failed, good = steps
    assert failed["as_type"] == good["as_type"] == "generation" and failed["name"] == "write-recommendations"
    assert failed["level"] == "WARNING" and failed["status_message"]
    assert failed["usage_details"] == {"input": 0, "output": 0} and failed["output"] is None
    assert good["level"] is None and good["output"] == {"summary": "ok"}
    assert good["usage_details"] == {"input": 100, "output": 20}
    assert good["cost_details"]["input"] > 0 and good["cost_details"]["output"] > 0
    assert good["input"][0]["role"] == "system" and good["model"] == "gpt-4.1-mini"

"""OpenAI calls (Responses API + strict structured outputs) with a fallback chain.

Measured on our key (Oct 2026): gpt-6-luna with reasoning effort "none" ~2.5 s median
(~1.7 s on the fast tier), fluent Kazakh, never returned an invalid candidate id.
Every call: store=False, fixed schemas (no per-request enums), hard timeout, and the
caller always has a non-LLM fallback. Token usage of every call is recorded for cost logging.
"""
from __future__ import annotations

import asyncio
import json
import hashlib
import logging
import time
from contextvars import ContextVar
from typing import Any, TypeVar

import openai
from openai import AsyncOpenAI
from pydantic import BaseModel, ValidationError

from app import tracing
from app.config import get_settings
from runtime_support.provider_health import ProbeState

log = logging.getLogger("app.llm")
M = TypeVar("M", bound=BaseModel)
_client: AsyncOpenAI | None = None
_usage: ContextVar[list[dict] | None] = ContextVar("llm_usage", default=None)
_client_configuration: str | None = None
_probes = ProbeState()


def _configuration() -> str:
    s = get_settings()
    return hashlib.sha256(json.dumps([s.openai_api_key, s.llm_parse_model, s.llm_chain, s.llm_service_tier]).encode()).hexdigest()


def provider_status() -> dict:
    s = get_settings()
    return _probes.describe(_configuration(), {"LLMParsed", "GenOut"},
                            configured=bool(s.llm_enabled and s.openai_api_key), ttl_s=s.provider_probe_ttl_s)


def client() -> AsyncOpenAI | None:
    global _client, _client_configuration
    s = get_settings()
    if not s.openai_api_key or not s.llm_enabled:
        return None
    configuration = _configuration()
    if _client is None or _client_configuration != configuration:
        previous = _client
        _client = AsyncOpenAI(api_key=s.openai_api_key, timeout=openai.Timeout(s.llm_timeout_s, connect=3.0), max_retries=0)
        _client_configuration = configuration
        if previous is not None and hasattr(previous, "close"):
            try:
                asyncio.get_running_loop().create_task(previous.close())
            except RuntimeError:
                asyncio.run(previous.close())
    return _client


# --- usage / cost ---------------------------------------------------------------------------------

def usage_begin() -> tuple[list[dict], int]:
    """Per-request usage meter (context-local; tasks created afterwards share it). Returns (meter, mark):
    the caller's own calls are meter[mark:]."""
    acc = _usage.get()
    if acc is None:
        acc = []
        _usage.set(acc)
    return acc, len(acc)


def _record(model: str, r: Any, tier: str | None) -> None:
    acc, u = _usage.get(), getattr(r, "usage", None)
    if acc is None or u is None:
        return
    acc.append({"model": model, "tier": getattr(r, "service_tier", None) or tier,
                "input_tokens": int(getattr(u, "input_tokens", 0) or 0),
                "output_tokens": int(getattr(u, "output_tokens", 0) or 0)})


def cost_usd(model: str, tier: str | None, input_tokens: int, output_tokens: int) -> float | None:
    prices = get_settings().llm_prices
    p = prices.get(f"{model}@{tier}") if tier else None
    p = p or prices.get(model)
    if p is None:
        return None
    return (input_tokens * p[0] + output_tokens * p[1]) / 1e6


def usage_summary(calls: list[dict]) -> dict:
    """{input_tokens, output_tokens, cost_usd}; cost is null if any call used a model without a price."""
    costs = [cost_usd(c["model"], c.get("tier"), c["input_tokens"], c["output_tokens"]) for c in calls]
    return {"input_tokens": sum(c["input_tokens"] for c in calls), "output_tokens": sum(c["output_tokens"] for c in calls),
            "cost_usd": None if any(x is None for x in costs) else round(sum(costs, 0.0), 6)}


# --- calls ------------------------------------------------------------------------------------------

def _model_kwargs(model: str, first: bool) -> dict:
    s = get_settings()
    kw: dict = {}
    if model.startswith(("gpt-6", "gpt-5")):
        kw["reasoning"] = {"effort": "none"}
        kw["text"] = {"verbosity": "low"}
    if first and s.llm_service_tier:
        kw["service_tier"] = s.llm_service_tier
    return kw


async def _attempt(c: AsyncOpenAI, schema: type[M], msgs: list[dict], model: str, kw: dict, max_output_tokens: int,
                   deadline: float) -> tuple[Any, str | None, dict]:
    """One model of the chain. Returns (response | None, error code | None, kwargs actually sent)."""
    left = deadline - time.perf_counter()
    try:
        r = await asyncio.wait_for(c.responses.parse(
            model=model, input=msgs, text_format=schema, store=False, max_output_tokens=max_output_tokens, **kw),
            timeout=left)
    except (asyncio.TimeoutError, openai.APITimeoutError):
        log.warning("llm %s timed out", model)
        return None, "timeout", kw
    except (ValidationError, json.JSONDecodeError, openai.APIResponseValidationError,
            openai.LengthFinishReasonError, openai.ContentFilterFinishReasonError) as e:
        # The SDK can raise while parsing text, before r.status is available.
        # Invalid model data is a failed attempt, never a server exception.
        log.warning("llm %s invalid output: %s", model, type(e).__name__)
        return None, f"invalid_output:{type(e).__name__}", kw
    except openai.BadRequestError:
        # e.g. a tier/param not supported for this model: retry same model without extras once
        log.warning("llm %s rejected parameters", model)
        remaining = deadline - time.perf_counter()
        if remaining <= 0:
            return None, "deadline", {}
        try:
            r = await asyncio.wait_for(c.responses.parse(
                model=model, input=msgs, text_format=schema, store=False, max_output_tokens=max_output_tokens),
                timeout=remaining)
        except Exception as e2:
            log.warning("llm %s retry failed: %s", model, type(e2).__name__)
            return None, f"retry_failed:{type(e2).__name__}", {}
        return r, None, {}
    except (openai.APIStatusError, openai.APIConnectionError) as e:
        log.warning("llm %s failed: %s", model, type(e).__name__)
        return None, type(e).__name__, kw
    return r, None, kw


def _trace_input(msgs: list[dict]) -> list[dict]:
    """Messages as the model saw them, minus the photo (images never go to tracing)."""
    def part(p):
        return {**p, "image_url": "[photo omitted]"} if isinstance(p, dict) and p.get("type") == "input_image" else p
    return [{**m, "content": [part(p) for p in m["content"]]} if isinstance(m["content"], list) else m for m in msgs]


def _trace_usage(model: str, r: Any, tier: str | None) -> dict:
    u = getattr(r, "usage", None)
    if u is None:
        return {}
    inp, out = int(getattr(u, "input_tokens", 0) or 0), int(getattr(u, "output_tokens", 0) or 0)
    tier = getattr(r, "service_tier", None) or tier
    usage = {"usage_details": {"input": inp, "output": out}}
    if (ci := cost_usd(model, tier, inp, 0)) is not None:
        # our own price table: Langfuse does not know every model / tier we call
        usage["cost_details"] = {"input": ci, "output": cost_usd(model, tier, 0, out)}
    return usage


async def parse(schema: type[M], system: str, user: str | list[dict], *, models: list[str], timeout_s: float,
                max_output_tokens: int = 1200, name: str = "llm-call") -> tuple[M | None, str | None, int]:
    """Try each model until one returns a completed, schema-valid object.
    `user` is text or a list of Responses input parts (input_text / input_image).
    `name` is the step name in Langfuse (stable: dashboards and evaluators filter on it).
    Returns (parsed | None, model | None, latency_ms)."""
    c = client()
    configuration = _configuration()
    t0 = time.perf_counter()
    if c is None:
        return None, None, 0
    deadline = t0 + timeout_s
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    for i, model in enumerate(models):
        if deadline - time.perf_counter() < 0.8:
            break
        kw = _model_kwargs(model, i == 0)
        with tracing.observe(name, as_type="generation", model=model, input=_trace_input(msgs),
                             model_parameters={"max_output_tokens": max_output_tokens,
                                               **{k: str(v) for k, v in kw.items()}},
                             metadata={"schema": schema.__name__, "attempt": i + 1, "chain": models}) as gen:
            r, err, kw = await _attempt(c, schema, msgs, model, kw, max_output_tokens, deadline)
            if r is not None:
                _record(model, r, kw.get("service_tier"))  # billed even if the answer is unusable
                if getattr(r, "status", "completed") != "completed" or r.output_parsed is None:
                    log.warning("llm %s status=%s", model, getattr(r, "status", None))
                    err = f"status:{getattr(r, 'status', None)}"
            parsed = r.output_parsed if r is not None and err is None else None
            gen.update(output=parsed.model_dump(mode="json") if parsed is not None else None,
                       level="WARNING" if err else None, status_message=err,
                       # no response = nothing billed: explicit zeros, or Langfuse estimates tokens from the input
                       **(_trace_usage(model, r, kw.get("service_tier")) if r is not None
                          else {"usage_details": {"input": 0, "output": 0}, "cost_details": {"input": 0.0, "output": 0.0}}))
        if err == "deadline":
            break
        if parsed is not None:
            _probes.record(configuration, schema.__name__, True, model)
            return parsed, model, int((time.perf_counter() - t0) * 1000)
    _probes.record(configuration, schema.__name__, False, models[-1] if models else "", error="unavailable_or_invalid_output")
    return None, None, int((time.perf_counter() - t0) * 1000)

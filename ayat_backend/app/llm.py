"""OpenAI calls (Responses API + strict structured outputs) with a fallback chain.

Measured on our key (Oct 2026): gpt-6-luna with reasoning effort "none" ~2.5 s median
(~1.7 s on the fast tier), fluent Kazakh, never returned an invalid candidate id.
Every call: store=False, fixed schemas (no per-request enums), hard timeout, and the
caller always has a non-LLM fallback.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import TypeVar

import openai
from openai import AsyncOpenAI
from pydantic import BaseModel

from app.config import get_settings

log = logging.getLogger("app.llm")
M = TypeVar("M", bound=BaseModel)
_client: AsyncOpenAI | None = None


def client() -> AsyncOpenAI | None:
    global _client
    s = get_settings()
    if not s.openai_api_key or not s.llm_enabled:
        return None
    if _client is None:
        _client = AsyncOpenAI(api_key=s.openai_api_key, timeout=openai.Timeout(s.llm_timeout_s, connect=3.0), max_retries=0)
    return _client


def _model_kwargs(model: str, first: bool) -> dict:
    s = get_settings()
    kw: dict = {}
    if model.startswith(("gpt-6", "gpt-5")):
        kw["reasoning"] = {"effort": "none"}
        kw["text"] = {"verbosity": "low"}
    if first and s.llm_service_tier:
        kw["service_tier"] = s.llm_service_tier
    return kw


async def parse(schema: type[M], system: str, user: str, *, models: list[str], timeout_s: float,
                max_output_tokens: int = 1200) -> tuple[M | None, str | None, int]:
    """Try each model until one returns a completed, schema-valid object.
    Returns (parsed | None, model | None, latency_ms)."""
    c = client()
    t0 = time.perf_counter()
    if c is None:
        return None, None, 0
    deadline = t0 + timeout_s
    for i, model in enumerate(models):
        left = deadline - time.perf_counter()
        if left < 0.8:
            break
        try:
            r = await asyncio.wait_for(c.responses.parse(
                model=model, input=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                text_format=schema, store=False, max_output_tokens=max_output_tokens, **_model_kwargs(model, i == 0)),
                timeout=left)
        except (asyncio.TimeoutError, openai.APITimeoutError):
            log.warning("llm %s timed out", model)
            continue
        except openai.BadRequestError as e:
            # e.g. a tier/param not supported for this model: retry same model without extras once
            log.warning("llm %s bad request: %s", model, str(e)[:160])
            try:
                r = await asyncio.wait_for(c.responses.parse(
                    model=model, input=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                    text_format=schema, store=False, max_output_tokens=max_output_tokens),
                    timeout=max(0.5, deadline - time.perf_counter()))
            except Exception as e2:
                log.warning("llm %s retry failed: %s", model, type(e2).__name__)
                continue
        except (openai.RateLimitError, openai.APIConnectionError, openai.InternalServerError,
                openai.NotFoundError, openai.PermissionDeniedError, openai.AuthenticationError) as e:
            log.warning("llm %s failed: %s", model, type(e).__name__)
            continue
        if getattr(r, "status", "completed") != "completed" or r.output_parsed is None:
            log.warning("llm %s status=%s", model, getattr(r, "status", None))
            continue
        return r.output_parsed, model, int((time.perf_counter() - t0) * 1000)
    return None, None, int((time.perf_counter() - t0) * 1000)

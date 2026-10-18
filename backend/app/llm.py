"""Тонкая обёртка над OpenAI-совместимым API (OpenAI, Gemini через base_url и т.п.).

Две роли моделей:
- fast     — разбор запроса (intent), temperature=0, минимальная задержка;
- decision — выбор 1–3 мест и объяснения; свежая reasoning-модель с reasoning_effort.
Если decision-модель недоступна — пробуем fast; если и она упала — None, пайплайн уходит в шаблоны.

Каждый вызов пишется в учёт запроса (модель, токены, задержка, стоимость) — см. usage_scope().
"""
import json
import logging
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass
from functools import lru_cache
from typing import Literal

from openai import BadRequestError, OpenAI

from . import tracing
from .config import get_settings

log = logging.getLogger("backend.llm")

Role = Literal["fast", "decision"]


@dataclass
class CallUsage:
    name: str
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: int
    cost_usd: float | None


_usage: ContextVar[list[CallUsage] | None] = ContextVar("llm_usage", default=None)
_decision_override: ContextVar[str | None] = ContextVar("decision_override", default=None)


@contextmanager
def override_decision_model(model: str | None):
    """Для A/B: внутри блока decision-вызовы идут в указанную модель (без fallback)."""
    token = _decision_override.set(model)
    try:
        yield
    finally:
        _decision_override.reset(token)


def current_override() -> str | None:
    return _decision_override.get()


@contextmanager
def usage_scope():
    """Собирает все LLM-вызовы внутри блока: with usage_scope() as calls: ..."""
    calls: list[CallUsage] = []
    token = _usage.set(calls)
    try:
        yield calls
    finally:
        _usage.reset(token)


def summarize(calls: list[CallUsage]) -> dict:
    costs = [c.cost_usd for c in calls]
    return {
        "llm_calls": len(calls),
        "input_tokens": sum(c.input_tokens for c in calls),
        "output_tokens": sum(c.output_tokens for c in calls),
        "llm_ms": sum(c.latency_ms for c in calls),
        "cost_usd": round(sum(costs), 6) if calls and None not in costs else None,
    }


def _cost(model: str, inp: int, out: int) -> float | None:
    price = get_settings().llm_prices.get(model)
    if not price:
        return None
    return (inp * price[0] + out * price[1]) / 1_000_000


@lru_cache
def _client() -> OpenAI | None:
    s = get_settings()
    if not s.llm_api_key:
        return None
    return OpenAI(api_key=s.llm_api_key, base_url=s.llm_base_url, timeout=s.llm_timeout_s, max_retries=1)


def is_enabled() -> bool:
    return _client() is not None


def models() -> dict[str, str]:
    s = get_settings()
    return {"fast": s.llm_fast_model, "decision": s.llm_decision_model}


def _call(client: OpenAI, model: str, messages: list[dict], extra: dict, timeout: float | None = None):
    if timeout:
        client = client.with_options(timeout=timeout, max_retries=0)
    try:
        return client.chat.completions.create(
            model=model, messages=messages, response_format={"type": "json_object"}, **extra
        )
    except BadRequestError as e:
        # reasoning-модели не принимают temperature, старые — reasoning_effort: повторяем без параметров
        if extra and any(k in str(e) for k in ("temperature", "reasoning_effort", "Unsupported")):
            return client.chat.completions.create(
                model=model, messages=messages, response_format={"type": "json_object"}
            )
        raise


def _for_trace(messages: list[dict]) -> list[dict]:
    """Фото пользователя в трейсы не отправляем — заменяем заглушкой."""
    out = []
    for m in messages:
        if isinstance(m["content"], list):
            parts = [p if p.get("type") != "image_url" else {"type": "text", "text": "[image omitted]"}
                     for p in m["content"]]
            m = {**m, "content": parts}
        out.append(m)
    return out


def chat_json(system: str, user: str | list, role: Role = "fast", name: str = "llm",
              model_override: str | None = None) -> dict | None:
    """Один вызов LLM, ответ — JSON-объект. None при любой ошибке.

    user может быть строкой или списком content-частей (текст + image_url) для vision.
    model_override — для A/B-экспериментов.
    """
    client = _client()
    if client is None:
        return None
    s = get_settings()
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    if role == "decision" and not model_override:
        model_override = _decision_override.get()
    # (модель, параметры, таймаут попытки)
    if model_override:
        attempts = [(model_override, {"reasoning_effort": s.llm_reasoning_effort} if role == "decision" else {"temperature": 0}, None)]
    else:
        attempts = [(s.llm_fast_model, {"temperature": 0}, None)]
        if role == "decision":
            # у reasoning-модели бывают хвосты задержки (до ~50 с в A/B) — ограничиваем и падаем на fast
            attempts.insert(0, (s.llm_decision_model, {"reasoning_effort": s.llm_reasoning_effort}, s.llm_decision_timeout_s))
    for model, extra, timeout in attempts:
        t0 = time.perf_counter()
        try:
            with tracing.generation(name, model, _for_trace(messages), extra) as gen:
                resp = _call(client, model, messages, extra, timeout)
                content = resp.choices[0].message.content or ""
                u = resp.usage
                inp, out = (u.prompt_tokens, u.completion_tokens) if u else (0, 0)
                gen.end(content, inp, out)
            call = CallUsage(name, model, inp, out, int((time.perf_counter() - t0) * 1000), _cost(model, inp, out))
            if (calls := _usage.get()) is not None:
                calls.append(call)
            data = json.loads(content)
            if isinstance(data, dict):
                return data
        except Exception as e:  # сеть, таймаут, невалидный JSON — пробуем следующую модель / fallback
            log.warning("llm call failed name=%s model=%s err=%s", name, model, type(e).__name__)
    return None


def usage_dicts(calls: list[CallUsage]) -> list[dict]:
    return [asdict(c) for c in calls]

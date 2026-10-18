"""Тонкая обёртка над OpenAI-совместимым API (OpenAI, Gemini через base_url и т.п.).

Две роли моделей:
- fast     — разбор запроса (intent), temperature=0, минимальная задержка;
- decision — выбор 1–3 мест и объяснения; свежая reasoning-модель с reasoning_effort.
Если decision-модель недоступна — пробуем fast; если и она упала — None, пайплайн уходит в шаблоны.
"""
import json
import logging
from functools import lru_cache
from typing import Literal

from openai import BadRequestError, OpenAI

from .config import get_settings

log = logging.getLogger("backend.llm")

Role = Literal["fast", "decision"]


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


def _call(client: OpenAI, model: str, messages: list[dict], extra: dict) -> str:
    try:
        resp = client.chat.completions.create(
            model=model, messages=messages, response_format={"type": "json_object"}, **extra
        )
    except BadRequestError as e:
        # reasoning-модели не принимают temperature, старые — reasoning_effort: повторяем без параметров
        if extra and any(k in str(e) for k in ("temperature", "reasoning_effort", "Unsupported")):
            resp = client.chat.completions.create(
                model=model, messages=messages, response_format={"type": "json_object"}
            )
        else:
            raise
    return resp.choices[0].message.content or ""


def chat_json(system: str, user: str, role: Role = "fast") -> dict | None:
    """Один вызов LLM, ответ — JSON-объект. None при любой ошибке."""
    client = _client()
    if client is None:
        return None
    s = get_settings()
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    attempts = [(s.llm_fast_model, {"temperature": 0})]
    if role == "decision":
        attempts.insert(0, (s.llm_decision_model, {"reasoning_effort": s.llm_reasoning_effort}))
    for model, extra in attempts:
        try:
            data = json.loads(_call(client, model, messages, extra))
            if isinstance(data, dict):
                return data
        except Exception as e:  # сеть, таймаут, невалидный JSON — пробуем следующую модель / fallback
            log.warning("llm call failed model=%s err=%s", model, type(e).__name__)
    return None

"""Трейсинг в Langfuse (опционально). Без LANGFUSE_PUBLIC_KEY/SECRET_KEY всё превращается в no-op.

Приватность: в трейсы идут только замаскированный текст запроса и данные POI;
координаты пользователя не передаются никогда.
"""
import logging
import os
from contextlib import contextmanager
from functools import lru_cache

log = logging.getLogger("backend.tracing")


class _NoopObs:
    def update(self, **_):
        return self

    def end(self, *_, **__):
        return self


@lru_cache
def _client():
    if not (os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY")):
        return None
    if os.getenv("LANGFUSE_BASE_URL") and not os.getenv("LANGFUSE_HOST"):
        os.environ["LANGFUSE_HOST"] = os.environ["LANGFUSE_BASE_URL"]
    try:
        from langfuse import get_client

        return get_client()
    except Exception as e:
        log.warning("langfuse disabled: %s", type(e).__name__)
        return None


def is_enabled() -> bool:
    return _client() is not None


@contextmanager
def span(name: str, as_type: str = "span", input=None, metadata=None):
    """Корневой или вложенный шаг пайплайна (span / retriever / guardrail / chain)."""
    lf = _client()
    if lf is None:
        yield _NoopObs()
        return
    with lf.start_as_current_observation(name=name, as_type=as_type, input=input, metadata=metadata) as obs:
        yield obs


class _Generation:
    def __init__(self, obs):
        self._obs = obs

    def end(self, output: str, input_tokens: int, output_tokens: int):
        self._obs.update(output=output, usage_details={"input": input_tokens, "output": output_tokens})


@contextmanager
def generation(name: str, model: str, messages: list, params: dict):
    lf = _client()
    if lf is None:
        yield _Generation(_NoopObs())
        return
    with lf.start_as_current_observation(
        name=name, as_type="generation", model=model, input=messages, model_parameters=params
    ) as obs:
        yield _Generation(obs)


def flush():
    if (lf := _client()) is not None:
        lf.flush()

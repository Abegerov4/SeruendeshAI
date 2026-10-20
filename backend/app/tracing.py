"""Langfuse tracing (optional). Without LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY every helper is a no-op.

One trace per user request: a root `recommend` / `recommend-photo` observation, a `retriever` for candidate
ranking and a `generation` per LLM attempt (model, tokens, cost).
Privacy (docs/ETHICS_PRIVACY.md): traces get the PII-masked query, request settings and snapshot place data.
User coordinates, home, photos and account data never go in — the same rule as the logs.
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any, Iterator

from app.config import get_settings

log = logging.getLogger("app.tracing")
_client: Any = None
_ready = False


class _Noop:
    def update(self, **_: Any) -> "_Noop":
        return self


_NOOP = _Noop()


def client():
    """Langfuse client, or None when tracing is off (no keys, LANGFUSE_ENABLED=false, SDK failed to start)."""
    global _client, _ready
    if _ready:
        return _client
    _ready = True
    s = get_settings()
    if not (s.langfuse_enabled and s.langfuse_public_key and s.langfuse_secret_key):
        return None
    try:
        from langfuse import Langfuse
        from opentelemetry.sdk.trace import TracerProvider

        # Own provider, not the global one: with a global provider FastAPI starts its own `fastapi.endpoint`
        # spans, which Langfuse does not export, and every trace would hang under a missing parent.
        _client = Langfuse(public_key=s.langfuse_public_key, secret_key=s.langfuse_secret_key,
                           base_url=s.langfuse_base_url, environment=s.langfuse_environment or None,
                           tracer_provider=TracerProvider())
    except Exception as e:  # tracing must never take the API down
        log.warning("langfuse disabled: %s", type(e).__name__)
    return _client


def is_enabled() -> bool:
    return client() is not None


@contextmanager
def request(name: str, *, input: Any, metadata: dict | None = None, tags: list[str] | None = None) -> Iterator[Any]:
    """Root observation of one user request; tags go to every observation below it.
    Inside an open trace (the photo endpoint runs a recommendation) it is a nested step instead."""
    lf = client()
    if lf is None:
        yield _NOOP
        return
    from opentelemetry import trace as otel_trace

    # the SDK's get_current_trace_id() logs a warning on every call outside a span; read the context directly
    if otel_trace.get_current_span().get_span_context().is_valid:
        with lf.start_as_current_observation(name=name, as_type="chain", input=input, metadata=metadata) as obs:
            yield obs
        return
    from langfuse import propagate_attributes

    with lf.start_as_current_observation(name=name, as_type="chain", input=input, metadata=metadata) as root, \
            propagate_attributes(trace_name=name, tags=tags):
        yield root


@contextmanager
def observe(name: str, *, as_type: str = "span", **kw: Any) -> Iterator[Any]:
    """Nested step (retriever / generation / span) of the current trace."""
    lf = client()
    if lf is None:
        yield _NOOP
        return
    with lf.start_as_current_observation(name=name, as_type=as_type, **kw) as obs:
        yield obs


def update_current(**kw: Any) -> None:
    """Add output / metadata to the innermost open step (e.g. mark a cache hit on the request)."""
    if (lf := client()) is not None:
        lf.update_current_span(**kw)


def flush() -> None:
    if _client is not None:
        try:
            _client.flush()
        except Exception as e:
            log.warning("langfuse flush failed: %s", type(e).__name__)

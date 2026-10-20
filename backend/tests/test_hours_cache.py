"""Repeated hours checks share parser work, while preserving exact safety decisions."""
import datetime as dt
from types import SimpleNamespace

import pytest

from app import hours


@pytest.fixture(autouse=True)
def isolate_hours_evaluations():
    cached = getattr(hours, "_state_at", None)
    if cached is not None:
        cached.cache_clear()
    yield
    if cached is not None:
        cached.cache_clear()


def parser(monkeypatch, *, fail_once=False):
    calls = {"state": 0, "next_change": 0}
    closing = dt.datetime(2026, 10, 19, 12, 10)

    def state(when):
        calls["state"] += 1
        return (SimpleNamespace(name="OPEN" if when < closing else "CLOSED"),)

    def next_change(when):
        calls["next_change"] += 1
        if fail_once and calls["next_change"] == 1:
            raise RuntimeError("temporary parser failure")
        return closing if when < closing else closing + dt.timedelta(days=1)

    monkeypatch.setattr(hours, "_parse", lambda raw: SimpleNamespace(state=state, next_change=next_change))
    return calls


def test_repeated_schedule_evaluation_keeps_visit_and_evidence_decisions_fresh(monkeypatch):
    calls = parser(monkeypatch)
    arrive = dt.datetime(2026, 10, 19, 11, 50)
    poi = {"opening_hours": "Mo 10:00-12:10", "hours_source": "official",
           "hours_source_url": "https://example.org/hours", "check_date": "2026-10-19"}

    fits = hours.opening_status(poi, arrive, 20, "en", None)
    exceeds = hours.opening_status(poi, arrive, 21, "en", None)
    holiday = hours.opening_status(poi, arrive, 20, "ru", "Holiday")
    stale = hours.opening_status({**poi, "check_date": "2025-01-01"}, arrive, 20, "en", None)
    future = hours.opening_status({**poi, "check_date": "2027-01-01"}, arrive, 20, "en", None)
    unverified = hours.opening_status({"opening_hours": poi["opening_hours"]}, arrive, 20, "en", None)
    monkeypatch.setattr(hours, "get_settings", lambda: SimpleNamespace(hours_max_age_days=0))
    expired = hours.opening_status({**poi, "check_date": "2026-10-18"}, arrive, 20, "en", None)

    assert fits["ok"] is True and fits["confidence"] == "high"
    assert exceeds["ok"] is False and exceeds["status"] == "closing_soon"
    # a holiday without its own PH rule: the usual hours say nothing about today
    assert holiday["status"] == "unknown" and holiday["confidence"] == "low" and holiday["label"] != fits["label"]
    assert all(result["confidence"] == "low" for result in (stale, future, unverified, expired))
    assert calls == {"state": 1, "next_change": 1}


def test_arrival_precision_and_raw_schedule_remain_part_of_hours_evaluation(monkeypatch):
    calls = parser(monkeypatch)
    poi = {"opening_hours": "Mo 10:00-12:10"}
    arrive = dt.datetime(2026, 10, 19, 11, 50)
    fits = hours.opening_status(poi, arrive, 20, "en", None)
    microsecond_late = hours.opening_status(poi, arrive + dt.timedelta(microseconds=1), 20, "en", None)
    closed = hours.opening_status(poi, dt.datetime(2026, 10, 19, 12, 10), 20, "en", None)
    hours.opening_status({"opening_hours": "Mo 09:00-12:10"}, arrive, 20, "en", None)

    assert fits["ok"] is True
    assert microsecond_late["ok"] is False
    assert closed["ok"] is False and closed["status"] == "closed"
    assert calls == {"state": 4, "next_change": 4}


def test_parser_failure_is_retryable_and_public_results_are_independent(monkeypatch):
    calls = parser(monkeypatch, fail_once=True)
    poi = {"opening_hours": "Mo 10:00-12:10"}
    arrive = dt.datetime(2026, 10, 19, 11, 50)

    assert hours.opening_status(poi, arrive, 20, "en", None)["status"] == "unknown"
    recovered = hours.opening_status(poi, arrive, 20, "en", None)
    assert recovered["status"] == "open"
    recovered["status"] = "closed"
    assert hours.opening_status(poi, arrive, 20, "en", None)["status"] == "open"
    assert calls == {"state": 2, "next_change": 2}

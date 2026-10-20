"""Researched hours keep the research's own confidence: an old guide card is not «high» because we read it today."""
import datetime as dt

import pytest

from app import feedback
from app.hours import opening_status
from app.store import apply_facts

DAY = dt.datetime(2026, 10, 21, 12, 0)  # Wednesday, not a holiday
CARD = {"opening_hours": "Mo-Su 10:00-18:00", "hours_url": "https://sxodim.com/astana/place/muzey", "checked": "2026-10-20",
        "confidence": "low", "hours_note": "по данным sxodim.com (карточка от 2023-03-07)"}


@pytest.fixture(autouse=True)
def fresh_marks(monkeypatch):
    feedback.reset()
    monkeypatch.setattr(feedback, "_loaded", True)
    monkeypatch.setattr(feedback.db, "SessionLocal", None)
    yield


def _place(fact):
    p = {"id": "osm:n1", "name": "Музей", "category": "museum"}
    apply_facts([p], {"osm:n1": fact})
    return p


def test_old_guide_card_is_dated_by_the_card_and_stays_low():
    p = _place(CARD)
    assert p["check_date"] == "2023-03-07" and p["hours_source"] == "sxodim.com"
    st = opening_status(p, DAY, 60, "ru", None)
    assert st["status"] == "open" and st["confidence"] == "low"


def test_research_confidence_caps_a_fresh_source():
    p = _place(dict(CARD, hours_url="https://chain.kz/branches", confidence="medium", hours_note="часы сети: 10:00–18:00"))
    assert p["check_date"] == "2026-10-20"
    assert opening_status(p, DAY, 60, "ru", None)["confidence"] == "medium"


def test_official_dated_hours_stay_high():
    p = _place(dict(CARD, hours_url="https://museum.kz/contacts", confidence="high", hours_note="Пн–Вс 10:00–18:00"))
    assert opening_status(p, DAY, 60, "ru", None)["confidence"] == "high"

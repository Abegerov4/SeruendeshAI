"""Researched facts: a closed place disappears, a description carries its source, hours carry source and date."""
from app.store import apply_facts
from pipeline.place_facts import clean


def poi(**kw):
    return {"id": "p1", "name": "Кафе Тест", "category": "cafe", "features": {}, "description_source": "template", **kw}


def test_closed_place_is_marked_and_hours_get_source_and_date():
    a, b = poi(), poi(id="p2")
    apply_facts([a, b], {"p1": {"status": "closed_permanently", "status_source": "https://news.kz/x", "checked": "2026-10-19"},
                         "p2": {"opening_hours": "Mo-Su 10:00-22:00", "hours_url": "https://www.cafe.kz/contacts", "checked": "2026-10-19",
                                "description_ru": "Кофейня у бульвара.", "description_url": "https://cafe.kz", "features": {"free_entry": True}}})
    assert a.get("closed_permanently")
    assert b["hours_source"] == "cafe.kz" and b["check_date"] == "2026-10-19" and b["description_kind"] == "research"
    assert b["features"]["free"] is True


def test_cleaning_rejects_unsourced_banned_and_box_office_facts():
    base = {"status": "open", "description_ru": "Достаточно длинное описание места для проверки.", "confidence": "high",
            "description_sources": ["https://2gis.kz/astana/firm/1"], "opening_hours": "Mo-Su 10:00-19:00",
            "hours_source": "https://opera.kz", "hours_note": "часы кассы", "features": {"wifi": True}, "features_sources": []}
    assert clean(base, poi()) is None  # 2GIS source, box-office hours, unsourced feature
    ok = clean({**base, "description_sources": ["https://ru.wikipedia.org/wiki/X"], "hours_note": None}, poi())
    assert ok["description_url"].startswith("https://ru.wikipedia.org") and ok["opening_hours"] == "Mo-Su 10:00-19:00"
    assert clean({**base, "description_sources": ["https://site.kz"], "confidence": "low", "opening_hours": None}, poi()) is None

"""Visitors' marks as weak evidence, holiday hours, and what never reaches the LLM."""
import datetime as dt

import pytest

from app import feedback
from app.context import holiday_name
from app.guards import mask_location
from app.hours import opening_status

DAY = dt.datetime(2026, 10, 20, 15, 0)  # Tuesday
PLACE = {"id": "test-cafe", "opening_hours": "Mo-Su 10:00-22:00"}


@pytest.fixture(autouse=True)
def fresh_marks(monkeypatch):
    feedback.reset()
    monkeypatch.setattr(feedback, "_loaded", True)  # unit tests: the in-memory mirror only
    monkeypatch.setattr(feedback.db, "SessionLocal", None)
    yield
    feedback.reset()


def mark(kind, days_ago=0, hits=1):
    day = (DAY.date() - dt.timedelta(days=days_ago)).isoformat()
    feedback._marks.setdefault(PLACE["id"], {})[(day, kind)] = hits


@pytest.mark.parametrize("text, hidden, kept", [
    ("Я возле Кенесары 40. Хочу прогулку рядом.", "40", "Кенесары"),
    ("кофе, я на 51.1283, 71.4305", "51.1283", "кофе"),
    ("кофе возле ул. Кенесары, д. 40, кв 12", "12", "Кенесары"),
    ("пр. Мангилик Ел 55/4 рядом кофе", "55/4", "Мангилик Ел"),
    ("я живу на Кабанбай батыра 53, что рядом?", "53", "Кабанбай"),
    ("мой адрес: Достык 5", "5", "Достык"),
    ("кофе возле Туран 37", "37", "Туран"),
    ("Сыганак 18 рядом парк", "18", "Сыганак"),
])
def test_exact_positions_are_masked_but_the_street_stays(text, hidden, kept):
    out = mask_location(text)
    assert hidden not in out and kept in out


@pytest.mark.parametrize("text", ["у меня 40 минут", "у Байтерека 3 места покажи", "на Туран 2 часа погулять", "на 2 часа у Байтерека", "Я у EXPO 2017, хочу что-то на 1-2 часа",
                                  "Мне 25 лет, хочу в музей", "с ребёнком 5 лет", "прогулка на 30 мин возле Хан Шатыра"])
def test_times_ages_and_names_with_numbers_are_not_masked(text):
    assert mask_location(text) == text


def test_one_fresh_closed_mark_lowers_confidence_only():
    base = opening_status(PLACE, DAY, 30, "ru", None)
    mark("closed")
    st = opening_status(PLACE, DAY, 30, "ru", None)
    assert st["status"] == "open" and st["label"] != base["label"] and "посетители" in st["label"]


def test_several_fresh_closed_marks_make_open_unknown():
    mark("closed", hits=2)
    mark("wrong_hours", days_ago=1)
    st = opening_status(PLACE, DAY, 30, "ru", None)
    assert st["status"] == "unknown" and st["confidence"] == "low" and st["ok"] is True


def test_marks_never_open_a_closed_place():
    mark("closed", hits=3)
    st = opening_status(PLACE, DAY.replace(hour=23), 30, "ru", None)
    assert st["status"] == "closed" and st["ok"] is False


def test_old_marks_fade_and_expire():
    mark("closed", days_ago=31, hits=3)
    assert feedback.doubt(PLACE["id"], DAY.date()) == 0
    mark("closed", days_ago=28, hits=3)  # three marks four weeks ago weigh as 0.75
    assert opening_status(PLACE, DAY, 30, "ru", None)["status"] == "open"


def test_thumbs_up_does_not_touch_hours():
    mark("great", hits=3)
    assert feedback.doubt(PLACE["id"], DAY.date()) == 0


def test_holiday_without_ph_rule_is_unknown_with_usual_hours_as_hint():
    st = opening_status(PLACE, DAY, 30, "ru", "Republic Day")
    assert st["status"] == "unknown" and "22:00" in st["label"]
    republic_day = dt.datetime(2026, 10, 25, 15, 0)  # the parser knows KZ holidays: an explicit PH rule is trusted
    assert opening_status({**PLACE, "opening_hours": "Mo-Su 10:00-22:00; PH off"}, republic_day, 30, "ru", "Republic Day")["status"] == "closed"


def test_holiday_names_follow_the_answer_language():
    day = dt.date(2026, 10, 26)
    assert holiday_name(day, "Republic Day (observed)", "ru") == "День Республики (перенос)"
    assert holiday_name(day, "Republic Day (observed)", "en") == "Republic Day (observed)"
    assert "Республикасы" in holiday_name(day, "Republic Day (observed)", "kk")


def test_typed_address_start_is_shown_back(client):
    r = client.post("/api/recommend", json={"query": "Хочу прогулку рядом", "lang": "ru", "location": {"lat": 51.166, "lon": 71.433},
                                            "location_label": "Кенесары 40", "now": "2026-10-20T15:00:00"}).json()
    assert r["used_context"]["location"]["label"] == "~ Кенесары 40"


def test_feedback_counts_once_per_client_and_place(client, monkeypatch):
    stored = []
    monkeypatch.setattr(feedback, "record", lambda poi, kind, today=None: stored.append((poi, kind)))
    poi = client.get("/api/pois", params={"lat": 51.128, "lon": 71.43}).json()[0]["id"]
    for _ in range(2):
        assert client.post("/api/feedback", json={"poi_id": poi, "kind": "closed", "lang": "ru"}).status_code == 200
    assert stored == [(poi, "closed")]


def test_task_scenario_one_gets_a_mini_route(client):
    """«Mega Silk Way, прогуляться 30–60 минут»: when a loop back does not fit, a one-way walk is offered and named."""
    r = client.post("/api/recommend", json={"query": "Я сейчас возле Mega Silk Way, хочу прогуляться 30–60 минут — что посоветуете?",
                                            "lang": "ru", "now": "2026-10-20T15:00:00"}).json()
    assert r.get("route") and r["route"]["total_min"] <= 60 and len(r["recommendations"]) >= 2


def test_start_label_and_clipped_description_read_well():
    from app.service import _clip
    text = "Площадь окружена зданиями, в которых входит ряд министерств и ведомств, а также торговые центры и рестораны"
    out = _clip(text, 60)
    assert out.endswith("…") and not out[:-1].endswith(" ") and len(out) <= 61

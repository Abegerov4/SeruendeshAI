import datetime as dt

from app.categories import category_from_osm
from app.generate import clean_text
from app.geo import fallback_walk_m, hav_m, round_coord
from app.hours import opening_status
from app.query import detect_lang, parse_rules, parse_time_budget

NOW = dt.datetime(2026, 10, 18, 15, 0)  # Sunday


def poi(cat="cafe", oh=None, **kw):
    return {"category": cat, "opening_hours": oh, "check_date": None, **kw}


def test_hours_open_closed_unknown():
    assert opening_status(poi(oh="Mo-Su 10:00-22:00"), NOW, 30, "ru", None)["status"] == "open"
    assert opening_status(poi(oh="Mo-Fr 09:00-18:00"), NOW, 30, "ru", None)["status"] == "closed"
    unk = opening_status(poi(oh=None), NOW, 30, "ru", None)
    assert unk["status"] == "unknown" and unk["confidence"] == "low"
    assert opening_status(poi("park"), NOW, 30, "ru", None)["status"] == "always"


def test_hours_closing_soon_and_holiday_downgrade():
    st = opening_status(poi(oh="Mo-Su 10:00-15:20"), NOW, 45, "ru", None)
    assert st["status"] == "closing_soon" and st["ok"] is True
    st = opening_status(poi(oh="Mo-Su 10:00-15:05"), NOW, 45, "ru", None)
    assert st["ok"] is False  # < 15 min on site
    assert opening_status(poi(oh="Mo-Su 10:00-22:00"), NOW, 30, "ru", "Republic Day")["confidence"] == "low"


def test_hours_unparseable_is_unknown_not_open():
    st = opening_status(poi(oh="по будням 9-18"), NOW, 30, "ru", None)
    assert st["status"] == "unknown" and "по будням" in st["label"]


def test_time_budget_parsing():
    assert parse_time_budget("прогуляться 30–60 минут") == 60
    assert parse_time_budget("у меня 2 часа") == 120
    assert parse_time_budget("пару часов") == 120
    assert parse_time_budget("полчаса") == 30
    assert parse_time_budget("бір сағат серуен") == 60
    assert parse_time_budget("3 hours") == 180


def test_rules_parser():
    p = parse_rules("Я - турист, у меня 2 часа перед вылетом")
    assert p.deadline_kind == "flight" and p.deadline_in_min == 120 and p.time_budget_min is None and p.tourist
    p = parse_rules("Хочу тихое место с кофе и розеткой")
    assert "cafe" in p.categories and {"power_outlets", "quiet"} <= p.needs
    assert parse_rules("Где выпить кофе?").categories == ["cafe"]
    assert "kids" in parse_rules("Еду с ребёнком").needs


def test_lang_detection():
    assert detect_lang("Бәйтеректің жанындамын") == "kk"
    assert detect_lang("First time in Astana") == "en"
    assert detect_lang("Хочу погулять") == "ru"


def test_validator_strips_facts_llm_must_not_invent():
    s = clean_text("Музей в 600 м, сейчас открыт до 18:00, идти 7 минут. Безопасно и интересно!")
    assert "600" not in s and "18:00" not in s and "7 минут" not in s
    assert "открыт" not in s.lower() and "безопасн" not in s.lower()
    assert "http" not in clean_text("см. https://evil.example.com")


def test_categories():
    assert category_from_osm({"amenity": "cafe", "name": "x"}) == "cafe"
    assert category_from_osm({"amenity": "toilets"}) is None
    assert category_from_osm({"historic": "monument", "building": "yes", "building:levels": "27"}) == "landmark"
    assert category_from_osm({"amenity": "cafe", "opening_hours": "closed"}) is None


def test_geo():
    d = float(hav_m(51.128, 71.43, 51.1325, 71.4037))
    assert 1800 < d < 2000
    assert round_coord(51.1283456) == 51.128
    river = [[[51.10, 71.40], [51.20, 71.40]]]  # vertical line
    crossing = fallback_walk_m(river, 51.15, 71.39, 51.15, 71.41)
    same_side = fallback_walk_m(river, 51.15, 71.41, 51.15, 71.43)
    assert crossing / float(hav_m(51.15, 71.39, 51.15, 71.41)) > 1.8  # 1.4 km across the river -> x1.9
    assert same_side / float(hav_m(51.15, 71.41, 51.15, 71.43)) < 1.4

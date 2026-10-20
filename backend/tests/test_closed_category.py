"""Everything of the requested kind is closed: related open places, not «anything open»; say when it reopens."""
import asyncio

import numpy as np
from rank_bm25 import BM25Okapi

from app import service
from app.query import parse_rules
from app.schemas import RecommendRequest
from app.store import Store

PLACES = [("Музей истории", "museum", "Tu-Su 10:00-18:00"), ("Кинотеатр Керуен", "cinema", "24/7"),
          ("ТРЦ Керуен", "mall", "10:00-22:00"), ("Кофейня", "cafe", "24/7"), ("Кофейня", "cafe", "24/7")]


def runtime():
    rows = [{"id": f"p:{i}", "name": name, "category": cat, "lat": 51.1283 + i * .0004, "lon": 71.4305,
             "opening_hours": hours, "features": {}, "popularity": .5} for i, (name, cat, hours) in enumerate(PLACES)]
    gaz = [{"name": "Байтерек", "kind": "landmark", "landmark_key": "baiterek", "keys": ["байтерек"],
            "lat": 51.128288, "lon": 71.430455}]
    st = Store(rows, np.array([p["lat"] for p in rows]), np.array([p["lon"] for p in rows]),
               np.array([p["category"] for p in rows]), np.array([.5] * len(rows)),
               BM25Okapi([[p["name"].lower()] for p in rows]), gaz, [], {}, by_id={p["id"]: i for i, p in enumerate(rows)})
    return service.Runtime(st, None, None, None, None, None, {})


def request(query, now):
    return asyncio.run(service.recommend(runtime(), RecommendRequest(query=query, landmark="baiterek", now=now, lang="ru")))


def test_closed_museum_is_replaced_by_a_related_open_place_not_a_mall_or_cafe():
    out = request("Хочу в музей", "2026-10-18T21:00:00+05:00")  # Sunday evening
    shown = {r["poi_id"] for r in out["recommendations"]}
    assert shown == {"p:1"}  # the cinema
    assert any("закрыто" in n for n in out["notes"])
    assert any("Ближайшее — «Музей истории»" in n and "10:00" in n for n in out["notes"])


def test_open_museum_is_shown_without_fallback_notes():
    out = request("Хочу в музей", "2026-10-20T12:00:00+05:00")
    assert [r["poi_id"] for r in out["recommendations"]][:1] == ["p:0"]
    assert not any("Ближайшее" in n for n in out["notes"])


def test_considered_lists_each_name_once():
    out = request("Хочу кофе", "2026-10-18T21:00:00+05:00")
    names = [c["name"] for c in out["considered"]]
    assert len(names) == len(set(names))


def test_night_activity_is_not_sport():
    assert "active" not in parse_rules("Ищу необычную ночную активность").categories
    assert "active" in parse_rules("Хочу активный отдых").categories


def test_drinks_and_meal_names_from_the_model_are_not_menu_filters():
    from app.food import FoodRequirement
    from app.query import LLMParsed, merge_llm

    for q, text, kind in [("beer with friends", "beer", "menu"), ("достармен сыра ішу", "сыра", "menu"),
                          ("екеуміз кешкі ас ішетін жер", "кешкі ас", "style"), ("где поужинать", "поужинать", "style")]:
        llm = LLMParsed.model_construct(**{**{k: None for k in LLMParsed.model_fields}, "categories": ["bar"],
                                           "food_requirements": [FoodRequirement(kind=kind, text=text)], "avoid_categories": [],
                                           "needs": [], "keywords_ru": [], "lang": "ru", "night": False, "surprise": False,
                                           "tourist": False, "off_topic": False})
        assert merge_llm(parse_rules(q), llm).food_requirements == [], q
    assert "bar" in parse_rules("достармен сыра ішу").categories

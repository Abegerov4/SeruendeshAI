"""Selection must prove a requested meal, rather than silently suggest generic cafes."""
import asyncio

import numpy as np
import pytest
from rank_bm25 import BM25Okapi

from app import service
from app.query import LLMParsed, merge_llm, parse_rules
from app.schemas import RecommendRequest
from app.store import Store


import pytest as _pytest


@_pytest.fixture(scope="module", autouse=True)
def canonical_snapshot_mode():
    """These tests cover the team catalogue runtime (opt-in in production)."""
    with _pytest.MonkeyPatch.context() as mp:
        mp.setenv("DATA_SNAPSHOT_MODE", "canonical")
        yield

QUERY = "я рядом с экспо хотелось бы вкусно покушать домашней еды пюре с котлетой очень дешево где можно?"


def runtime(details=None):
    rows = [{"id": f"food:{i}", "name": name, "category": category,
             "lat": 51.093+i*.0001, "lon": 71.421, "opening_hours": "24/7",
             "features": {}, "popularity": .5, "place_details": (details or {}) if i == 2 else {},
             "raw_tags": {"website:menu": "https://example.org/menu", "cuisine": "regional"}}
            for i, (name, category) in enumerate([("Starbucks", "cafe"), ("Berezka", "restaurant"),
                                                 ("Домашние котлеты и пюре", "restaurant")])]
    gaz = [{"name": "EXPO / Нур Алем", "kind": "landmark", "landmark_key": "expo", "keys": ["экспо", "expo"],
            "lat": 51.092788, "lon": 71.421482}, {"name": "Байтерек", "kind": "landmark", "landmark_key": "baiterek",
            "keys": ["байтерек"], "lat": 51.128288, "lon": 71.430455}]
    st = Store(rows, np.array([p["lat"] for p in rows]), np.array([p["lon"] for p in rows]),
               np.array([p["category"] for p in rows]), np.array([.5]*3),
               BM25Okapi([["food", str(i)] for i in range(3)]), gaz, [], {}, by_id={p["id"]:i for i,p in enumerate(rows)})
    return service.Runtime(st, None, None, None, None, None, {})


def request(rt, query=QUERY, **updates):
    return asyncio.run(service.recommend(rt, RecommendRequest(**{
        "query": query, "landmark": "baiterek", "now": "2026-10-19T11:00:00+05:00", "lang": "ru", **updates})))


def test_screenshot_query_preserves_expo_and_does_not_launder_cafes_or_menu_url():
    out = request(runtime())
    assert out["used_context"]["location_label"] == "EXPO / Нур Алем"
    assert out["recommendations"] == [] and out["ideas"] == [] and out["route"] is None
    assert "нет подтверждения" in out["summary"].lower()
    assert "просто где поесть рядом" in out["summary"].lower()
    assert {r["kind"] for r in out["used_context"]["parsed_from_query"]["food_requirements"]} >= {"menu", "price", "style"}


@pytest.mark.parametrize("query", ["Где поесть рядом с экспо?", "Кофе рядом с экспо", "Поесть рядом с экспо за 30 минут"])
def test_generic_food_and_time_budget_keep_working(query):
    assert request(runtime(), query)["recommendations"]


def test_explicit_numeric_meal_budget_is_not_a_free_time_duration():
    out = request(runtime(), "Поесть у экспо до 2000 тенге")
    assert out["recommendations"] == []
    assert out["used_context"]["time_budget_min"] == 60


@pytest.mark.parametrize("query", ["Дешёвый музей рядом", "Билет в кино до 2000 тенге", "taxi under $10"])
def test_unrelated_prices_are_not_food_requirements(query):
    assert parse_rules(query).food_requirements == []


def llm(**updates):
    return LLMParsed.model_validate({"lang":"ru", "categories":["cafe"], "avoid_categories":[], "needs":[],
        "time_budget_min":None,"travel_mode":None,"party":None,"group_size":None,"tourist":None,
        "landmark_text":None,"deadline_kind":None,"deadline_in_min":None,"deadline_clock":None,
        "wants_route":None,"night":False,"surprise":False,"search_text_ru":"кафе","keywords_ru":["кафе"],**updates})


def test_model_omission_never_erases_explicit_requirements():
    rules = parse_rules(QUERY)
    merged = merge_llm(rules, llm())
    assert merged.food_requirements == rules.food_requirements
    assert {r.kind for r in merged.food_requirements} >= {"menu","price","style"}


@pytest.mark.parametrize("query,phrase", [("Где поесть?", "без глютена"), ("Не хочу чак-чак, просто поесть", "чак-чак"),
                                         ("Где поесть возле Чакчака?", "чак")])
def test_model_cannot_invent_or_reintroduce_dismissed_requirements(query, phrase):
    parsed = merge_llm(parse_rules(query), llm(food_requirements=[{"kind":"menu", "text":phrase}]))
    assert parsed.food_requirements == []


def details(channel="dine_in", amount=1700):
    proof = {"status":"accepted", "conflict_status":"none", "branch_scope":"exact",
             "source":{"url":"https://example.org/branch-menu", "checked_at":"2026-10-19", "excerpt":"Котлета с картофельным пюре; указанная цена включает все обязательные платежи"},
             "branch_confirmation":{"source_name":"Домашние котлеты и пюре", "source_address":"EXPO"},
             "valid_from":None,"valid_to":None}
    return {"facts":[{**proof,"field":"cuisine","value":"домашняя кухня"}],
            "menu_items":[{**proof,"id":"meal-1","name":"Котлета с картофельным пюре", "components":["котлета","пюре"],
                           "aliases":[], "role":"meal", "price":{"amount":amount,"currency":"KZT","unit":"порция","channel":channel,"kind":"item"},
                           "cost":{**proof,"scope":"one_offering","complete":True,"service_percent":0,
                                   "mandatory_fixed_amount":0,"minimum_payable_amount":0}}],
            "prices":[]}


def test_confirmed_dine_in_meal_and_numeric_budget_select_only_evidenced_branch():
    out = request(runtime(details()), "Я рядом с экспо, где поесть пюре с котлетой до 2000 тенге?")
    assert [p["poi_id"] for p in out["recommendations"]] == ["food:2"]
    assert out["recommendations"][0]["menu_items"][0]["price"]["amount"] == 1700
    assert out["recommendations"][0]["menu_items"][0]["source"]["url"] == "https://example.org/branch-menu"


def test_arrival_after_kitchen_closes_rejects_even_named_food_target():
    data = details()
    data["facts"].append({**data["facts"][0], "field":"kitchen_hours", "value":"Mo-Su 10:00-21:00"})
    out = request(runtime(data), "Я рядом с экспо, пюре с котлетой до 2000 тенге",
                  now="2026-10-19T20:59:59+05:00")
    assert out["recommendations"] == []


def test_generic_food_also_respects_known_closed_kitchen():
    rt = runtime()
    for poi in rt.store.pois:
        data = details()
        data["facts"].append({**data["facts"][0], "field":"kitchen_hours", "value":"Mo-Su 10:00-21:00"})
        poi["place_details"] = data
    assert request(rt, "Где поесть рядом с экспо?", now="2026-10-19T21:00:00+05:00")["recommendations"] == []


def test_coffee_only_request_does_not_require_the_meal_kitchen():
    rt = runtime()
    for poi in rt.store.pois:
        data = details()
        data["facts"].append({**data["facts"][0], "field":"kitchen_hours", "value":"Mo-Su 10:00-21:00"})
        poi["place_details"] = data
    assert request(rt, "Кофе рядом с экспо", now="2026-10-19T21:00:00+05:00")["recommendations"]


@pytest.mark.parametrize("query", ["Где позавтракать в кафе рядом с экспо?", "Где перекусить в кафе рядом с экспо?",
                                  "Breakfast in a cafe near expo", "Таңғы ас ішетін кафе экспо жанында"])
def test_explicit_other_meal_words_respect_kitchen_closure(query):
    rt = runtime()
    for poi in rt.store.pois:
        data = details()
        data["facts"].append({**data["facts"][0], "field":"kitchen_hours", "value":"Mo-Su 10:00-21:00"})
        poi["place_details"] = data
    assert request(rt, query, now="2026-10-19T21:00:00+05:00")["recommendations"] == []


def test_model_rewrite_cannot_remove_explicit_kitchen_intent(monkeypatch):
    monkeypatch.setattr(service, "merge_llm", lambda rules, _: merge_llm(rules, llm(search_text_ru="кафе")))
    rt = runtime()
    for poi in rt.store.pois:
        data = details()
        data["facts"].append({**data["facts"][0], "field":"kitchen_hours", "value":"Mo-Su 10:00-21:00"})
        poi["place_details"] = data
    assert request(rt, "Где поесть рядом с экспо?", now="2026-10-19T21:00:00+05:00")["recommendations"] == []


def test_negated_meal_does_not_block_a_coffee_only_visit():
    rt = runtime()
    for poi in rt.store.pois:
        data = details()
        data["facts"].append({**data["facts"][0], "field":"kitchen_hours", "value":"Mo-Su 10:00-21:00"})
        poi["place_details"] = data
    assert request(rt, "Не хочу поесть, хочу только кофе рядом с экспо", now="2026-10-19T21:00:00+05:00")["recommendations"]


@pytest.mark.parametrize("channel,amount", [("delivery",1700),("dine_in",2200)])
def test_delivery_only_or_over_budget_meal_is_not_a_match(channel, amount):
    out = request(runtime(details(channel, amount)), "Я рядом с экспо, пюре с котлетой до 2000 тенге")
    assert out["recommendations"] == []


def test_unrelated_cheap_drink_does_not_establish_a_meal_budget():
    data = details()
    data["menu_items"][0].update(name="Чай", components=["чай"], role="drink")
    data["menu_items"][0]["price"]["amount"] = 300
    assert request(runtime(data), "Где поесть рядом с экспо до 2000 тенге?")["recommendations"] == []


def test_homestyle_inflection_matches_explicit_cuisine_fact():
    assert [p["poi_id"] for p in request(runtime(details()),"Я у экспо хочу домашней еды пюре с котлетой")["recommendations"]] == ["food:2"]


def test_venue_vegetarian_options_do_not_make_a_meat_meal_vegetarian():
    data = details()
    data["facts"].append({**data["facts"][0],"field":"vegetarian_options","value":True})
    assert request(runtime(data),"Я у экспо хочу поесть вегетарианскую котлету с пюре")["recommendations"] == []


def test_average_check_does_not_prove_price_of_a_requested_delivery_dish():
    from app.evidence import match_food
    import datetime as dt
    data = details("delivery")
    data["prices"] = [{**data["menu_items"][0],"amount":1000,"currency":"KZT","unit":"человек","channel":"dine_in","kind":"average_check"}]
    match = match_food({"place_details":data},parse_rules("Очень дешево пюре с котлетой").food_requirements,
                       dt.date(2026,10,19),{"n":8,"q25":1500,"median":2500,"basis":"reported_average_check"})
    assert not match.matched and "price" in match.gaps


def test_delivery_only_menu_does_not_establish_an_onsite_meal():
    assert request(runtime(details("delivery")),"Я рядом с экспо хочу поесть пюре с котлетой в ресторане")["recommendations"] == []


def test_budget_and_diet_must_be_proved_by_the_same_offering():
    data = details()
    vegan = {**data["menu_items"][0],"name":"Vegan soup","components":["soup"],"price":{**data["menu_items"][0]["price"],"amount":2500}}
    meat = {**data["menu_items"][0],"id":"meat","name":"Chicken soup","components":["soup"],"price":{**data["menu_items"][0]["price"],"amount":1000}}
    data["menu_items"] = [vegan,meat]
    data["facts"].append({**data["facts"][0],"field":"vegan_options","value":True})
    assert request(runtime(data),"I want vegan soup under 2000 KZT near EXPO")["recommendations"] == []


def test_food_requirements_survive_a_nearer_followup():
    prior = [{"kind":"menu","text":"пюре"},{"kind":"menu","text":"котлетой"},{"kind":"price","text":"до 2000 тенге"}]
    out = request(runtime(),"Поближе пожалуйста",landmark="expo",refine=["closer"],food_context=prior)
    assert out["recommendations"] == []
    assert {r["kind"] for r in out["used_context"]["parsed_from_query"]["food_requirements"]} == {"menu","price"}


@pytest.mark.parametrize("query", ["Хочу погулять в парке", "Просто где поесть рядом", "Покажи музеи"])
def test_new_topic_drops_prior_food_constraints(query):
    out = request(runtime(),query,food_context=[{"kind":"menu","text":"пюре"}],refine=["closer"])
    assert out["used_context"]["parsed_from_query"]["food_requirements"] == []


def test_cheap_comparison_uses_the_reviewed_format_group(monkeypatch):
    from app import retrieval
    monkeypatch.setattr(retrieval,"price_benchmarks",lambda *args:{
        "restaurant":{"n":8,"q25":7000,"median":9000},"cafe":{"n":11,"q25":2500,"median":3000}})
    data=details()
    data["prices"]=[{**data["facts"][0],"kind":"average_check","amount":7000,"currency":"KZT",
                     "unit":"person","channel":"dine_in","comparison_group":"cafe"}]
    assert request(runtime(data),"Я рядом с экспо, хочу дешево поесть")["recommendations"] == []


@pytest.mark.parametrize("query,expected", [
    ("А можно до 1000 тенге?","до 1000 тенге"),
    ("Поближе к Экспо пожалуйста","до 2000 тенге"),
    ("А подешевле, но без мяса?","до 2000 тенге")])
def test_budget_origin_and_diet_followups_preserve_the_meal(query,expected):
    prior=[{"kind":"menu","text":"пюре"},{"kind":"menu","text":"котлетой"},{"kind":"price","text":"до 2000 тенге"}]
    out=request(runtime(),query,food_context=prior)
    wishes=out["used_context"]["parsed_from_query"]["food_requirements"]
    assert out["recommendations"] == []
    assert {w["text"] for w in wishes if w["kind"]=="menu"} == {"пюре","котлетой"}
    assert expected in {w["text"] for w in wishes if w["kind"]=="price"}

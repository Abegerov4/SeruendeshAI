"""«Маршрут с AITU до NU»: the model's knowledge of a place name reaches the search; an unknown place is said so."""
import asyncio

from app import decisions, service
from app.query import LLMParsed, Parsed, place_candidates


def model_parse(destination_text, destination_name, *, landmark=None):
    async def fake(schema, system, user, **kw):
        if schema is not LLMParsed:
            return None, None, 0
        return LLMParsed(lang="ru", categories=[], avoid_categories=[], needs=[], time_budget_min=None, travel_mode=None,
                         party=None, group_size=None, tourist=None, landmark_text=landmark, deadline_kind=None,
                         deadline_in_min=None, deadline_clock=None, wants_route=True, night=False, surprise=False,
                         search_text_ru="маршрут", keywords_ru=["маршрут"], destination_text=destination_text,
                         destination_name=destination_name), "fake", 1
    return fake


def ask(client, monkeypatch, query, destination_text, destination_name):
    monkeypatch.setattr(service, "llm_client", lambda: object())
    monkeypatch.setattr(service, "llm_parse", model_parse(destination_text, destination_name))
    return client.post("/api/recommend", json={"query": query, "lang": "ru", "now": "2026-10-21T15:00:00"}).json()


def test_the_models_name_for_an_abbreviation_finds_the_place(client):
    gaz = client.app.state.rt.store.gazetteer if hasattr(client.app.state, "rt") else None
    from app.main import RT
    gaz = RT["rt"].store.gazetteer
    best = place_candidates("Nazarbayev University", gaz)
    assert best and best[0][1].get("landmark_key") == "nazarbayev_university"
    assert place_candidates("Astana IT University", gaz)[0][1].get("landmark_key") == "aitu"
    assert place_candidates("NU", gaz) == []  # two letters say nothing on their own


def test_route_from_aitu_to_nu_goes_to_nu(client, monkeypatch):
    r = ask(client, monkeypatch, "маршрут с университета AITU до NU", "NU", "Nazarbayev University")
    assert r["used_context"]["location"]["label"].startswith("Astana IT University")
    assert r["used_context"]["parsed_from_query"]["destination"] == "Nazarbayev University"
    assert r["navigate_to"] and r["recommendations"][0]["poi_id"] == r["navigate_to"]
    assert "назарбаев" in r["recommendations"][0]["name"].lower() or "nazarbayev" in r["recommendations"][0]["name"].lower()


def test_a_route_to_a_place_we_do_not_know_says_so(client, monkeypatch):
    r = ask(client, monkeypatch, "маршрут с AITU до Хогвартса", "Хогвартса", "Hogwarts School of Witchcraft")
    assert r["recommendations"] == []
    assert "Не нашёл «Хогвартса»" in r["summary"]


def test_a_kind_of_place_is_not_a_missing_destination(client, monkeypatch):
    r = ask(client, monkeypatch, "проложи маршрут до кофейни, я у меги", None, None)
    assert r["recommendations"] and "Не нашёл" not in r["summary"]


def test_close_names_in_different_places_are_settled_by_the_judge(monkeypatch):
    a = {"name": "Burger Hall", "kind": "poi", "keys": ["burger hall"], "lat": 51.10, "lon": 71.40}
    b = {"name": "Burger Hall", "kind": "poi", "keys": ["burger hall"], "lat": 51.16, "lon": 71.46}
    store = type("S", (), {"gazetteer": [a, b]})()
    seen = {}

    async def pick(query, entries):
        seen["n"] = len(entries)
        return entries[1], True
    monkeypatch.setattr(decisions, "pick_place", pick)
    monkeypatch.setattr(decisions, "enabled", lambda: True)
    parsed = Parsed(destination_text="бургер холл", destination_name="Burger Hall")
    assert asyncio.run(service.find_destination(store, parsed, "маршрут до burger hall на левом")) is b and seen["n"] == 2

    async def none_of_them(query, entries):
        return None, True
    monkeypatch.setattr(decisions, "pick_place", none_of_them)
    assert asyncio.run(service.find_destination(store, parsed, "маршрут до burger hall")) is None


def test_the_route_endpoint_draws_the_way_to_a_point_place(client):
    r = client.post("/api/route", json={"poi_id": "lm:nazarbayev_university", "landmark": "aitu", "mode": "walk"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["name"] == "Назарбаев Университет" and d["travel_min"] > 5 and len(d["polyline"]) > 2
    assert client.post("/api/route", json={"poi_id": "pt:55.75,37.61", "landmark": "aitu"}).status_code == 404  # not Astana
    assert client.post("/api/route", json={"poi_id": "lm:no_such_place", "landmark": "aitu"}).status_code == 404


def test_a_named_place_the_model_does_not_know_is_also_said_so(client, monkeypatch):
    r = ask(client, monkeypatch, "проложи маршрут с AITU до Хогвартса", "Хогвартса", None)
    assert r["recommendations"] == [] and "Не нашёл «Хогвартса»" in r["summary"]


def test_the_destination_is_understood_even_when_the_start_is_not(client, monkeypatch):
    r = ask(client, monkeypatch, "я учусь в AITU, мне нужен маршрут до университета NU", "университета NU", "Nazarbayev University")
    assert r["recommendations"] == []
    assert r["summary"].startswith("Понял, идём до «Назарбаев Университет»") and "Откуда начнём?" in r["summary"]

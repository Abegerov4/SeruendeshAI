"""Temporal audit regressions: real planner/ranking, synthetic data, no providers."""
import asyncio
import datetime as dt
from types import SimpleNamespace

import numpy as np
import pytest
from rank_bm25 import BM25Okapi

from ayat_backend.app import planner, service
from ayat_backend.app.context import TZ, build_context
from ayat_backend.app.hours import opening_status
from ayat_backend.app.query import parse_rules
from ayat_backend.app.retrieval import Cand, Plan, rank
from ayat_backend.app.schemas import RecommendRequest
from ayat_backend.app.store import Store


def poi(i=1, **kw):
    return {"id": f"p{i}", "name": f"Place {i}", "category": "cafe", "lat": 51.128 + i * .0001,
            "lon": 71.43, "opening_hours": "24/7", "features": {}, "popularity": .5, **kw}


def store(rows):
    return Store(rows, np.array([p["lat"] for p in rows]), np.array([p["lon"] for p in rows]),
                 np.array([p["category"] for p in rows]), np.array([.5] * len(rows)),
                 BM25Okapi([["place", str(i)] for i in range(len(rows))]),
                 [{"name": "Airport", "kind": "airport", "landmark_key": "airport", "keys": ["airport", "аэропорт", "әуежай"],
                   "lat": 51.03, "lon": 71.47}], [], {}, by_id={p["id"]: i for i, p in enumerate(rows)})


def ctx(clock="2026-10-19T11:00:00+05:00"):
    return build_context(dt.datetime.fromisoformat(clock), None, False)


def cand(i=1, visit=45, **kw):
    p = poi(i, **kw)
    return Cand(i - 1, p, 100, 2, visit, (visit, visit), opening_status(p, ctx().local_naive, visit, "en", None), score=1)


def test_exact_now_keys_do_not_reuse_another_deadline_or_open_state():
    req = RecommendRequest(query="coffee", now="2026-10-19T12:00:00+05:00")
    assert service._cache_key(req, ctx("2026-10-19T12:00:00+05:00").now) != service._cache_key(req, ctx("2026-10-19T12:14:00+05:00").now)
    from backend.app.cache import make_key
    assert make_key("coffee", None, dt.datetime(2026, 10, 19, 20, 45), {}) != make_key("coffee", None, dt.datetime(2026, 10, 19, 20, 59), {})


@pytest.mark.parametrize("arrive,visit,ok", [("2026-10-19T11:50", 21, False), ("2026-10-19T11:50", 20, True),
                                                 ("2026-10-20T01:50", 20, False), ("2026-10-20T01:40", 20, True)])
def test_full_visit_must_fit_hours_including_midnight(arrive, visit, ok):
    hours = "Mo 18:00-02:00" if "20T" in arrive else "Mo 10:00-12:10"
    assert opening_status(poi(opening_hours=hours), dt.datetime.fromisoformat(arrive), visit, "en", None)["ok"] is ok


def test_unknown_public_space_hours_and_source_labels_are_honest():
    assert opening_status(poi(category="park", opening_hours=None), ctx().local_naive, 30, "en", None)["status"] == "unknown"
    op = opening_status(poi(hours_source="official", hours_source_url="https://example.org/hours"), ctx().local_naive, 30, "en", None)
    assert "OSM" not in op["label"] and "official" in op["label"].lower()


def test_route_rejects_visits_that_extend_after_closing():
    cands = [cand(1, opening_hours="Mo 10:00-12:10"), cand(2, opening_hours="Mo 10:00-12:10")]
    p = Plan((51.128, 71.43), "walk", 75, 120, 30, 2000)
    assert planner.plan_route(cands, p, ctx(), None, [], "en", returns=False) is None


def test_route_opening_cache_respects_exact_arrival(monkeypatch):
    # 0->A=1, A->C=1: C arrives at 7 (invalid), B->C at 3 (valid).
    # Both used to share the 0..9-minute bucket and depend on permutation order.
    times = np.array([[0, 1, 1, 10], [1, 0, 1, 1], [1, 1, 0, 1], [1, 1, 1, 0]], dtype=float)
    monkeypatch.setattr(planner, "_matrix", lambda *args: (times, times * 75, {}, None, False))
    cands = [cand(1, visit=5), cand(2, visit=1), cand(3, visit=1, opening_hours="Mo 10:00-11:05")]
    cands[2].score = 100
    p = Plan((51.128, 71.43), "walk", 75, 12, 30, 2000)
    out = planner.plan_route(cands, p, ctx(), None, [], "en", returns=False, max_stops=2)
    assert out is not None and [c.poi["id"] for c in out["stops"]] == ["p2", "p3"]


def test_graph_matrix_includes_destination_approach_and_fallback_label():
    class Graph:
        def covers(self, *args): return True
        def snap(self, lat, lon): return np.array([100., 200., 600.]), np.array([0, 1, 2])
        def from_source(self, lat, lon, limit):
            i = 0 if lat == 51.128 else (1 if lat < 51.12815 else 2)
            return np.array([100., 1000., 2000.]) if i == 0 else np.array([1100., 200., np.inf]), np.array([-1, 0, -1]), i
        def path_polyline(self, *args): return [(51.128, 71.43), (51.1281, 71.43)]
    p = Plan((51.128, 71.43), "walk", 75, 120, 30, 2000)
    out = planner.plan_route([cand(1, visit=5), cand(2, visit=5)], p, ctx(), Graph(), [], "en", returns=False)
    _, distances, _, _, _ = planner._matrix([cand(1, visit=5), cand(2, visit=5)], p, ctx(), Graph(), [])
    assert distances[0, 1] == 1200
    assert any(leg["geometry"] == "straight" for leg in out["legs"])


@pytest.mark.parametrize("condition", ["accessibility", "dark", "cold", "indoor", "kids"])
def test_named_destination_cannot_bypass_mandatory_constraints(condition):
    row = poi(category="bar" if condition == "kids" else "park", features={"wheelchair": "no", "lit": False})
    st = store([row])
    p = Plan((51.128, 71.43), "walk", 75, 120, 30, 2000,
             accessibility=condition == "accessibility", with_child=condition == "kids")
    c = ctx()
    if condition == "dark": c.is_dark = True
    if condition == "cold": c.max_outdoor_min = 0
    if condition == "indoor": p.filters.append("indoor_only")
    found, considered = rank(st, None, None, None, parse_rules("park"), p, c, "en", None, target_ids={"p1"})
    assert found == [] and considered


def test_final_route_cards_use_planner_visits_even_with_fake_model(monkeypatch):
    from ayat_backend.app.generate import GenOut, GenPick
    st = store([poi(1), poi(2, category="monument")])
    rt = service.Runtime(st, None, None, None, None, None, {})
    # Only the provider boundary is fake: real ranking, routing, validation and serialization run.
    monkeypatch.setattr(service, "llm_client", lambda: object())
    async def no_parse(*args, **kwargs): return None, None, 0
    monkeypatch.setattr(service, "llm_parse", no_parse)
    async def model(cands, *args):
        cmap = {f"c{i + 1}": c for i, c in enumerate(cands)}
        return GenOut(summary="127 minutes on site", picks=[GenPick(cand=k, why="Nice", what_to_do="Visit", visit_min=67) for k in cmap], idea=None), "fake", 0, cmap
    monkeypatch.setattr(service, "generate", model)
    out = asyncio.run(service.recommend(rt, RecommendRequest(query="route", location={"lat": 51.128, "lon": 71.43}, time_budget_min=90, want_route=True, now="2026-10-19T11:00:00+05:00", lang="en")))
    assert out["route"] is not None
    visits = sum(r["visit_suggested_min"] for r in out["recommendations"])
    assert visits + sum(l["travel_min"] for l in out["route"]["legs"]) == out["route"]["total_min"]
    assert all(r["visit_min"] == [r["visit_suggested_min"]] * 2 for r in out["recommendations"])
    assert "127" not in out["summary"]


@pytest.mark.parametrize("query,kind,flight_type,budget", [
    ("domestic flight in 2 hours", "flight", "domestic", 0),
    ("international flight in 4 hours", "flight", "international", 45),
    ("flight in 4 hours", "flight", "unknown", 45),
    ("be at the airport in 2 hours", "airport_arrival", "unknown", 105),
    ("быть в аэропорту через 2 часа", "airport_arrival", "unknown", 105),
    ("әуежайда 2 сағаттан кейін болу керек", "airport_arrival", "unknown", 105),
    ("ішкі рейс 2 сағаттан кейін", "flight", "domestic", 0),
    ("халықаралық рейс 4 сағаттан кейін", "flight", "international", 45),
])
def test_departure_and_airport_arrival_have_distinct_budgets(query, kind, flight_type, budget):
    st = store([poi()])
    rt = service.Runtime(st, None, None, None, None, None, {})
    out = asyncio.run(service.recommend(rt, RecommendRequest(query=query, location={"lat": 51.128, "lon": 71.43}, now="2026-10-19T11:00:00+05:00")))
    parsed = out["used_context"]["parsed_from_query"]
    assert parsed["deadline"] == kind
    assert parsed["flight_type"] == flight_type
    assert out["used_context"]["time_budget_min"] == budget
    if budget == 0: assert out["recommendations"] == [] and out["route"] is None


@pytest.mark.parametrize("check_date", [None, "2026-03-01", "2027-01-01"])
def test_missing_stale_or_future_hours_checks_never_get_high_confidence(check_date):
    op = opening_status(poi(hours_source="official", hours_source_url="https://example.org/hours", check_date=check_date),
                        ctx().local_naive, 30, "en", None)
    assert op["confidence"] == "low"


def test_named_inaccessible_destination_is_excluded_over_http(client, monkeypatch):
    from ayat_backend.app.main import RT
    row = poi(category="park", name="Target Park", features={"wheelchair": "no", "lit": True})
    st = store([row])
    st.gazetteer.append({"name": "Target Park", "kind": "place", "keys": ["target park"], "lat": row["lat"], "lon": row["lon"], "poi_id": "p1"})
    monkeypatch.setitem(RT, "rt", service.Runtime(st, None, None, None, None, None, {}))
    r = client.post("/api/recommend", json={"query": "хочу в Target Park", "location": {"lat": 51.128, "lon": 71.43}, "accessibility": True, "lang": "ru", "now": "2026-10-19T11:00:00+05:00"})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["recommendations"] == []
    assert any("Target Park" in note for note in out["notes"])
    assert any("недоступ" in c["reason"].lower() or "ступен" in c["reason"].lower() for c in out["considered"])


def test_explicit_now_http_revalidates_after_closing_boundary(client, monkeypatch):
    from ayat_backend.app.main import RT
    st = store([poi(opening_hours="Mo 10:00-11:35")])
    monkeypatch.setitem(RT, "rt", service.Runtime(st, None, None, None, None, None, {}))
    body = {"query": "coffee", "location": {"lat": 51.128, "lon": 71.43}, "time_budget_min": 60, "want_route": False}
    first = client.post("/api/recommend", json={**body, "now": "2026-10-19T11:00:00+05:00"}).json()
    later = client.post("/api/recommend", json={**body, "now": "2026-10-19T11:14:00+05:00"}).json()
    assert first["recommendations"] and first["recommendations"][0]["open_status"] == "open"
    assert first["recommendations"][0]["visit_min"][1] <= 34  # even the advertised maximum must fit before 11:35
    assert later["recommendations"] == []
    assert later["used_context"]["now"] == "2026-10-19T11:14:00+05:00"


def test_deadline_return_is_explicit_and_not_double_counted():
    cands = [cand(1, visit=5), cand(2, visit=5)]
    for c in cands:
        c.return_min = 10
    p = Plan((51.128, 71.43), "walk", 75, 90, 30, 2000,
             deadline_min=120, deadline_buffer=15, deadline_back_target=(51.03, 71.47))
    out = planner.plan_route(cands, p, ctx(), None, [], "en", returns=False)
    assert out["total_min"] == 22
    assert out["back_min"] == 10
    assert out["travel_min"] == 2 and out["visit_min"] == 10
    assert not out["returns_to_start"] and out["fits_budget"]


def test_midnight_calendar_recovery_uses_actual_closing_transition(monkeypatch):
    from ayat_backend.app import hours
    # Characterize recovery when the external parser loses an overnight tail:
    # its next change is the next opening, which must never be used as closing.
    external = SimpleNamespace(state=lambda at: (SimpleNamespace(name="CLOSED"),),
                               next_change=lambda at: dt.datetime(2026, 10, 20, 18))
    monkeypatch.setattr(hours, "_parse", lambda raw: external)
    out = hours.opening_status(poi(opening_hours="Mo 18:00-03:00"), dt.datetime(2026, 10, 20, 2, 50), 30, "en", None)
    assert out["ok"] is False and out["next_change"] == "03:00"


@pytest.mark.parametrize("budget,expected_count", [(10, 0), (74, 0), (75, 1)])
def test_explicit_flight_budget_includes_outbound_visit_and_airport_return(budget, expected_count):
    st = store([poi(lat=51.135)])
    rt = service.Runtime(st, None, None, None, None, None, {})
    out = asyncio.run(service.recommend(rt, RecommendRequest(
        query="coffee before domestic flight in 5 hours", location={"lat": 51.128, "lon": 71.43},
        time_budget_min=budget, want_route=False, now="2026-10-19T11:00:00+05:00")))
    assert len(out["recommendations"]) == expected_count
    if expected_count:
        item = out["recommendations"][0]
        assert item["travel_min"] == 14
        assert item["visit_suggested_min"] == 25 and item["visit_min"] == [25, 25]
        assert item["leave_by"] == "11:39"  # 75min budget minus36min to airport
        assert 14 + item["visit_min"][1] + 36 <= budget
    assert out["route"] is None


def test_final_card_never_invents_five_minutes_without_remaining_room():
    c = cand()
    c.travel_min, c.return_min = 14, 36
    p = Plan((51.128, 71.43), "walk", 75, 10, 10, 600,
             deadline_min=300, deadline_buffer=135, deadline_back_target=(51.03, 71.47))
    assert service._item(c, "Nice", "Visit", 25, 1, p, "en", "walk") is None


@pytest.mark.parametrize("query,budget,deadline", [
    ("I have 10 minutes for coffee before domestic flight in 5 hours", 10, 300),
    ("У меня 10 минут свободного времени, внутренний рейс через 5 часов", 10, 300),
    ("I have 1 hour 30 minutes for coffee before domestic flight in 5 hours 15 minutes", 90, 315),
    ("У меня 1 час 20 минут, внутренний рейс через 5 часов 10 минут", 80, 310),
    ("domestic flight in 5 hours; I have 20 minutes for coffee", 20, 300),
    ("У меня полчаса, внутренний рейс через 5 часов", 30, 300),
])
def test_free_time_and_deadline_durations_are_parsed_independently(query, budget, deadline):
    parsed = parse_rules(query)
    assert parsed.time_budget_min == budget
    assert parsed.deadline_in_min == deadline


@pytest.mark.parametrize("query", [
    "I have 10 minutes for coffee before domestic flight in 5 hours",
    "У меня 10 минут свободного времени, внутренний рейс через 5 часов",
])
def test_textual_free_time_remains_binding_before_later_flight(query):
    rt = service.Runtime(store([poi(lat=51.135)]), None, None, None, None, None, {})
    out = asyncio.run(service.recommend(rt, RecommendRequest(query=query,
        location={"lat": 51.128, "lon": 71.43}, want_route=False, now="2026-10-19T11:00:00+05:00")))
    assert out["used_context"]["time_budget_min"] == 10
    assert out["recommendations"] == [] and out["route"] is None
    parsed = out["used_context"]["parsed_from_query"]
    assert parsed["time_budget_min"] == 10 and parsed["deadline_in_min"] == 300


def test_structured_free_budget_overrides_text_before_deadline():
    rt = service.Runtime(store([poi(lat=51.135)]), None, None, None, None, None, {})
    out = asyncio.run(service.recommend(rt, RecommendRequest(
        query="I have 10 minutes for coffee before domestic flight in 5 hours", time_budget_min=90,
        location={"lat": 51.128, "lon": 71.43}, want_route=False, now="2026-10-19T11:00:00+05:00")))
    assert out["used_context"]["time_budget_min"] == 90
    assert out["used_context"]["parsed_from_query"]["time_budget_min"] == 10
    assert out["recommendations"]


def test_model_parse_cannot_overwrite_explicit_free_time_and_deadline():
    from ayat_backend.app.query import LLMParsed, merge_llm
    rules = parse_rules("I have 10 minutes for coffee before domestic flight in 5 hours")
    model = LLMParsed(lang="en", categories=["cafe"], avoid_categories=[], needs=[], time_budget_min=60,
                      travel_mode=None, party=None, group_size=None, tourist=False, landmark_text=None,
                      deadline_kind="flight", deadline_in_min=60, deadline_clock=None, wants_route=False,
                      night=False, surprise=False, search_text_ru="кофе", keywords_ru=[])
    parsed = merge_llm(rules, model)
    assert parsed.time_budget_min == 10 and parsed.deadline_in_min == 300

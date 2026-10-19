"""A meal's quoted price and its complete payable cost are distinct facts."""
from copy import deepcopy
import datetime as dt

import pytest

from ayat_backend.app.evidence import accepted_details, match_food
from ayat_backend.app.food import FoodRequirement


TODAY = dt.date(2026, 10, 19)


def proof(**extra):
    return {"status": "accepted", "conflict_status": "none", "branch_scope": "exact",
            "branch_confirmation": {"source_name": "Cafe", "source_address": "Astana, Main 1"},
            "source": {"url": "https://merchant.example/menu/1", "checked_at": TODAY.isoformat(),
                       "excerpt": "Котлета с пюре 1800 KZT; к указанной цене добавляется обслуживание 10%."},
            "valid_from": None, "valid_to": None, **extra}


def meal_poi(cost=True):
    menu = {**proof(), "id": "meal", "name": "Котлета с пюре", "components": ["котлета", "пюре"],
            "aliases": [], "role": "meal", "price": {"amount": 1800, "currency": "KZT",
            "unit": "portion", "channel": "dine_in", "kind": "item"}}
    if cost:
        menu["cost"] = {**proof(), "scope": "one_offering", "complete": True,
                        "service_percent": 10, "mandatory_fixed_amount": 0, "minimum_payable_amount": 0}
    return {"place_details": {"facts": [], "menu_items": [menu], "prices": []}}


def wishes(limit):
    return [FoodRequirement(kind="menu", text="котлета"), FoodRequirement(kind="menu", text="пюре"),
            FoodRequirement(kind="price", text=f"до {limit} тенге")]


def test_complete_cost_includes_service_without_mutating_raw_menu():
    poi = meal_poi()
    before = deepcopy(poi)
    item = accepted_details(poi, TODAY)["menu_items"][0]
    assert item.get("total_price") == {"amount": 1980.0, "currency": "KZT", "unit": "portion",
                                       "channel": "dine_in", "kind": "item"}
    assert item["price"]["amount"] == 1800
    assert item.get("cost_status") == "complete"
    assert poi == before


def test_budget_uses_payable_total_and_not_base_price():
    assert not match_food(meal_poi(), wishes(1900), TODAY).matched
    assert match_food(meal_poi(), wishes(1980), TODAY).matched


def test_pizza_brand_english_word_and_russian_menu_are_same_food():
    poi = meal_poi(cost=False)
    poi["place_details"]["menu_items"][0].update(name="Пицца Маргарита", components=[])
    assert match_food(poi, [FoodRequirement(kind="menu", text="Пицца"),
                            FoodRequirement(kind="menu", text="Pizza")], TODAY).matched


def test_missing_fee_statement_does_not_prove_an_affordable_total():
    poi = meal_poi(cost=False)
    item = accepted_details(poi, TODAY)["menu_items"][0]
    assert item.get("cost_status") == "unknown"
    assert item.get("total_price") is None
    assert not match_food(poi, wishes(2000), TODAY).matched
    assert match_food(poi, wishes(2000)[:2], TODAY).matched


@pytest.mark.parametrize("change", [
    {"complete": "true"}, {"scope": "per_group"},
    {"service_percent": True}, {"service_percent": float("nan")}, {"service_percent": -1},
    {"service_percent": 101}, {"mandatory_fixed_amount": float("inf")},
    {"mandatory_fixed_amount": -1}, {"minimum_payable_amount": True},
    {"branch_confirmation": {"source_name": "Cafe", "source_address": "Astana, Main 2"}},
    {"source": {"url": "https://merchant.example/menu", "checked_at": "2026-08-01", "excerpt": "Old fees"}},
    {"conflict_status": "conflicting"}, {"valid_to": "2026-10-18"},
])
def test_invalid_or_unattributed_cost_stays_unknown(change):
    poi = meal_poi()
    poi["place_details"]["menu_items"][0]["cost"].update(change)
    item = accepted_details(poi, TODAY)["menu_items"][0]
    assert item.get("total_price") is None
    assert "cost" not in item
    assert not match_food(poi, wishes(2000), TODAY).matched


def test_minimum_and_mandatory_fixed_charge_are_payable():
    poi = meal_poi()
    poi["place_details"]["menu_items"][0]["cost"].update(
        mandatory_fixed_amount=200, minimum_payable_amount=2500)
    assert not match_food(poi, wishes(2499), TODAY).matched
    assert accepted_details(poi, TODAY)["menu_items"][0].get("total_price", {}).get("amount") == 2500


@pytest.mark.parametrize("field,value", [("channel", "delivery"), ("unit", "100 g")])
def test_delivery_or_weight_price_does_not_prove_one_dine_in_meal(field, value):
    poi = meal_poi()
    poi["place_details"]["menu_items"][0]["price"][field] = value
    assert not match_food(poi, wishes(2000), TODAY).matched


def test_kitchen_hours_are_independent_of_open_venue_and_checked_at_arrival():
    poi = meal_poi()
    poi["opening_hours"] = "Mo-Su 08:00-23:00"
    poi["place_details"]["facts"] = [proof(field="kitchen_hours", value="Mo-Su 10:00-21:00")]
    assert match_food(poi, wishes(2000), TODAY, arrive_at=dt.datetime(2026, 10, 19, 20, 59)).matched
    assert not match_food(poi, wishes(2000), TODAY, arrive_at=dt.datetime(2026, 10, 19, 21, 0)).matched


def test_closed_serving_window_does_not_become_available_from_open_kitchen():
    poi = meal_poi()
    poi["place_details"]["facts"] = [proof(field="kitchen_hours", value="Mo-Su 10:00-23:00")]
    poi["place_details"]["menu_items"][0]["serving_hours"] = "Mo-Fr 12:00-15:00"
    assert match_food(poi, wishes(2000), TODAY, arrive_at=dt.datetime(2026, 10, 19, 14, 59)).matched
    assert not match_food(poi, wishes(2000), TODAY, arrive_at=dt.datetime(2026, 10, 19, 15, 0)).matched


def test_overnight_kitchen_window():
    poi = meal_poi()
    poi["place_details"]["facts"] = [proof(field="kitchen_hours", value="Mo-Su 18:00-02:00")]
    assert match_food(poi, wishes(2000), TODAY, arrive_at=dt.datetime(2026, 10, 20, 1, 30)).matched
    assert not match_food(poi, wishes(2000), TODAY, arrive_at=dt.datetime(2026, 10, 20, 2, 0)).matched


def test_partial_known_service_charge_never_proves_a_complete_budget():
    from data.meal_cost import valid_cost_terms
    poi = meal_poi()
    cost = poi["place_details"]["menu_items"][0]["cost"]
    cost.update(complete=False, mandatory_fixed_amount=None, minimum_payable_amount=None)
    assert valid_cost_terms(cost, require_complete=False)
    assert not match_food(poi, wishes(2000), TODAY).matched


def test_kitchen_closing_only_does_not_invent_an_opening_time():
    poi = meal_poi()
    poi["place_details"]["facts"] = [proof(field="kitchen_closes_at", value="21:00")]
    assert match_food(poi, wishes(2000), TODAY, arrive_at=dt.datetime(2026, 10, 19, 20, 0)).matched
    assert not match_food(poi, wishes(2000), TODAY, arrive_at=dt.datetime(2026, 10, 19, 21, 0)).matched


@pytest.mark.parametrize("qualitative", [False, True])
def test_route_rechecks_kitchen_at_each_stop_after_prior_visit(qualitative):
    from types import SimpleNamespace
    from ayat_backend.app.planner import plan_route
    from ayat_backend.app.retrieval import Plan, Cand
    now = dt.datetime(2026, 10, 19, 12, 0) if qualitative else dt.datetime(2026, 10, 19, 20, 55)
    ctx = SimpleNamespace(now=now, local_naive=now, max_outdoor_min=60, snowing=False, holiday=None)
    plan = Plan(origin=(51.09, 71.42), mode="walk", m_per_min=75, budget=60, t_max=20, radius_m=1000)
    plan.check_kitchen = True
    plan.food_requirements = [FoodRequirement(kind="price", text="дёшево")] if qualitative else []
    plan.food_benchmarks = {"cafe": {"q25": 1500, "median": 2000, "n": 8}}
    cands = []
    for i in range(2):
        poi = meal_poi()
        poi.update(id=f"cafe:{i}", name=f"Cafe {i}", category="cafe", lat=51.0901+i*.0001,
                   lon=71.42, opening_hours="24/7")
        poi["place_details"]["facts"] = [proof(field="kitchen_hours", value="Mo-Su 10:00-21:00")]
        poi["place_details"]["prices"] = [{**proof(), "kind":"average_check", "amount":1000,
            "currency":"KZT", "unit":"person", "channel":"dine_in"}]
        cands.append(Cand(i, poi, 20, 1, 10, (10, 10), {"ok":True}, score=1.0))
    route = plan_route(cands, plan, ctx, None, [], "ru", returns=False)
    if qualitative:
        assert route is not None
    else:
        assert route is None

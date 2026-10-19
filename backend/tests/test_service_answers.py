"""A tour is a source-bound service, not a POI at the operator's office."""
from .test_food_requirements import runtime, request
from data.city_services import load_city_services


import pytest as _pytest


@_pytest.fixture(scope="module", autouse=True)
def canonical_snapshot_mode():
    """These tests cover the team catalogue runtime (opt-in in production)."""
    with _pytest.MonkeyPatch.context() as mp:
        mp.setenv("DATA_SNAPSHOT_MODE", "canonical")
        yield


def rt():
    value = runtime()
    value.store.services = [s.model_dump(mode="json") for s in load_city_services().services]
    return value


def test_redbus_boarding_uses_provider_stop_and_never_operator_office():
    out = request(rt(), "Где сесть на Ред Бас?")
    assert out["recommendations"] == []
    result = out["service_results"][0]
    assert result["id"] == "service:redbus-astana"
    assert "байтерек" in out["summary"].lower()
    assert "республики 34" not in out["summary"].lower()
    stops = [stop for route in result["routes"] for stop in route["stops"] if stop["role"] == "boarding"]
    assert stops and stops[0]["map_url"] == "https://2gis.kz/astana/firm/70000001089193403"


def test_yearless_old_departures_are_not_announced_as_last_bus_today():
    out = request(rt(), "Последний рейс RedBus сегодня во сколько?")
    result = out["service_results"][0]
    assert result["departures_today"] == []
    assert "не подтверждено" in out["summary"].lower()
    assert "18:00" not in out["summary"] and "20:00" not in out["summary"]


def test_standard_and_combo_fares_are_not_collapsed_and_conflicting_free_offer_is_withheld():
    out = request(rt(), "Сколько стоит RedBus?")
    result = out["service_results"][0]
    assert {offer["amount"] for offer in result["ticket_offers"]} == {6000,3000}
    assert "6000" in out["summary"].replace(" ", "")
    assert not any(offer["amount"] == 0 for offer in result["ticket_offers"])
    assert result["notes"]


def test_service_context_is_used_for_followup_but_not_new_food_topic():
    followup = request(rt(), "А где посадка?", service_id="service:redbus-astana")
    assert followup["service_results"][0]["id"] == "service:redbus-astana"
    changed = request(rt(), "Хочу пюре с котлетой рядом с экспо", service_id="service:redbus-astana")
    assert changed.get("service_results",[]) == []
    assert changed["recommendations"] == []


def test_expired_boarding_points_are_not_stated_as_current():
    out = request(rt(),"Где сесть на RedBus?",now="2027-10-19T11:00:00+05:00")
    assert "Посадка:" not in out["summary"]
    assert not [stop for route in out["service_results"][0]["routes"] for stop in route["stops"] if stop["role"] == "boarding"]


def test_yearless_booking_policy_is_not_confirmed_for_today():
    out = request(rt(),"Этно-дегустация Тамыр")
    assert not any(rule["field"] == "advance_booking" for rule in out["service_results"][0]["booking_rules"])


def test_route_answer_distinguishes_pass_by_from_boarding():
    out = request(rt(),"Какой маршрут у RedBus?")
    assert "Левый берег" in out["summary"] and "Правый берег" in out["summary"]
    assert "проезд мимо" in out["summary"] and "посадка" in out["summary"]


def test_new_cinema_or_museum_topic_drops_redbus_context():
    for query in ("Сколько стоит билет в кино рядом?","Какой музей посоветуешь с ребенком?"):
        out=request(rt(),query,service_id="service:redbus-astana")
        assert out.get("service_results",[]) == []


def test_generic_places_do_not_select_paid_tours_without_tour_intent():
    for query in ("Хочу погулять по Нуржолу полчаса","Прогулка вдоль Ишима","Хочу посетить Национальный музей"):
        assert request(rt(),query).get("service_results",[]) == []

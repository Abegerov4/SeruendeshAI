"""Service facts must not turn undated schedules or landmarks into departures."""
from copy import deepcopy
from datetime import date
import importlib
import importlib.util
import json

import pytest
from pydantic import ValidationError


def api():
    assert importlib.util.find_spec("data.city_services"), "typed city-service catalog is missing"
    return importlib.import_module("data.city_services")


def evidence():
    return {"source_url": "https://operator.example/routes", "checked_at": "2026-10-18T23:00:00Z",
            "excerpt": "18 October 2026: departure at 17:00.",
            "validity": {"precision": "exact", "valid_from": "2026-10-18", "valid_to": "2026-10-18"}}


def catalog_payload():
    return {"schema_version": 1, "as_of": "2026-10-19", "collected_at": "2026-10-18T23:00:00Z",
            "operators": [{"id": "operator:test", "name": "Operator", "evidence": [evidence()]}],
            "services": [{"id": "service:test", "name": "City tour", "kind": "bus_tour",
                          "operator_id": "operator:test", "evidence": [evidence()],
                          "routes": [{"id": "route:test", "name": "Route", "evidence": [evidence()],
                                      "stops": [{"id": "stop:test", "name": "Main entrance", "role": "boarding",
                                                 "evidence": [evidence()]}]}],
                          "dated_departures": [{"date": "2026-10-18", "time": "17:00", "boarding_stop_id": "stop:test",
                                                "evidence": [evidence()]}]}]}


def test_dated_departures_never_roll_forward_to_today():
    # Catches reuse of yesterday's last run as today's departure.
    mod = api()
    service = mod.CityServicesCatalog.model_validate(catalog_payload()).services[0]
    assert [str(d.time) for d in mod.departures_on(service, date(2026, 10, 18))] == ["17:00:00"]
    assert mod.departures_on(service, date(2026, 10, 19)) == []


@pytest.mark.parametrize("change", ["missing_source", "naive_timestamp", "reversed_validity", "unknown_operator",
                                   "unknown_boarding_stop", "pass_by_boarding", "year_unspecified_departure",
                                   "wrong_validity_date", "offset_local_departure_time", "duplicate_ticket_id"])
def test_invalid_or_unverified_service_facts_are_rejected(change):
    # Catches unsupported publication at the source, identity and date boundaries.
    payload = deepcopy(catalog_payload())
    service = payload["services"][0]
    if change == "missing_source":
        service["evidence"] = []
    elif change == "naive_timestamp":
        service["evidence"][0]["checked_at"] = "2026-10-18T23:00:00"
    elif change == "reversed_validity":
        service["evidence"][0]["validity"]["valid_from"] = "2026-10-20"
    elif change == "unknown_operator":
        service["operator_id"] = "operator:absent"
    elif change == "unknown_boarding_stop":
        service["dated_departures"][0]["boarding_stop_id"] = "stop:absent"
    elif change == "pass_by_boarding":
        service["routes"][0]["stops"][0]["role"] = "pass_by"
    elif change == "year_unspecified_departure":
        service["dated_departures"][0]["evidence"][0]["validity"]["precision"] = "year_unspecified"
    elif change == "wrong_validity_date":
        service["dated_departures"][0]["date"] = "2026-10-19"
    elif change == "offset_local_departure_time":
        service["dated_departures"][0]["time"] = "17:00+03:00"
    else:
        offer = {"id": "offer:same", "name": "Ticket", "audience": "Adult", "amount": 3000,
                 "currency": "KZT", "evidence": [evidence()]}
        service["ticket_offers"] = [offer, deepcopy(offer)]
    with pytest.raises(ValidationError):
        api().CityServicesCatalog.model_validate(payload)


def test_loader_preserves_provenance_without_filling_unknown_coordinates(tmp_path):
    # Catches inventing an office/landmark location during ingestion.
    path = tmp_path / "services.json"
    path.write_text(json.dumps(catalog_payload()))
    catalog = api().load_city_services(path)
    stop = catalog.services[0].routes[0].stops[0]
    assert stop.canonical_poi_id is None
    assert stop.map_url is None
    assert catalog.services[0].evidence[0].source_url == "https://operator.example/routes"


def test_actual_redbus_data_keeps_schedule_and_child_fare_conflicts_visible():
    # Catches silent conflict resolution or treating pass-by attractions as boarding points.
    catalog = api().load_city_services()
    redbus = next(s for s in catalog.services if s.id == "service:redbus-astana")
    assert api().departures_on(redbus, date(2026, 10, 19)) == []
    assert redbus.schedule_status == "date_unverified"
    assert any(f.field == "duration_minutes" and f.status == "conflicting" for f in redbus.facts)
    assert any(f.field == "child_age_policy" and f.status == "conflicting" for f in redbus.facts)
    assert {offer.amount for offer in redbus.ticket_offers if offer.currency == "KZT"} >= {3000, 6000}
    stops = [stop for route in redbus.routes for stop in route.stops]
    assert any(stop.role == "boarding" and "Байтерек" in stop.name for stop in stops)
    assert any(stop.role == "pass_by" and "Опера" in stop.name for stop in stops)
    assert all(stop.canonical_poi_id is None for stop in stops if stop.role == "boarding")
    assert len(catalog.services) >= 5


def test_citypass_offers_are_distinct_products_without_transferred_operators_or_fares():
    # Catches generic venue/boat offers being merged with independently priced products.
    services = {service.id: service for service in api().load_city_services().services}
    assert "service:citypass-astana-opera-tour" in services
    assert "service:citypass-ishim-river-cruise" in services
    opera = services["service:citypass-astana-opera-tour"]
    boat = services["service:citypass-ishim-river-cruise"]
    lesson = services["service:astana-opera-theatre-lesson"]
    assert next(f.value for f in opera.facts if f.field == "group_minimum") == 5
    assert next(f.value for f in lesson.facts if f.field == "group_minimum") == 10
    assert next(f.value for f in boat.facts if f.field == "duration_minutes") == 45
    for offer in [opera, boat]:
        assert offer.operator_id is None
        assert offer.ticket_offers == []
        assert offer.dated_departures == []
        assert api().departures_on(offer, date(2026, 10, 19)) == []
        assert all(e.source_url.startswith("https://astana.citypass.kz/ru/attractions/") for e in offer.evidence)
    assert {"service:redbus-astana", "service:dual-parks-river", "service:blue-necklace-river",
            "service:national-museum-gold", "service:astana-opera-theatre-lesson", "service:tamyr-tea-ceremony",
            "service:tamyr-ethno-tasting", "service:nurzhol-interest-love"} <= services.keys()

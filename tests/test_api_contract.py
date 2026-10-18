"""Actual backend checks: opting in means missing/unreachable components fail."""

import json
from pathlib import Path

import pytest

from eval.validators import validate_response

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.live_api


def test_health_describes_actual_readiness(api_client):
    response = api_client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body.get("status") == "ok"
    assert type(body.get("pois")) is int and body["pois"] > 0
    assert body.get("llm") == "ok", "Do not report a healthy model when its integration is absent"


def test_reference_walk_returns_supported_pois(api_client, real_pois):
    request = {"query": "Я возле Mega Silk Way, хочу погулять 30–60 минут", "location": {"lat": 51.089, "lon": 71.416}, "time_budget_min": 60, "mode": "walk", "lang": "ru", "now": "2026-10-18T17:00:00+05:00"}
    response = api_client.post("/api/recommend", json=request)
    assert response.status_code == 200
    errors = validate_response(response.json(), request, real_pois, {"outcome": "recommendations", "count_between": [1, 3]})
    assert not errors, "\n".join(errors)


def test_missing_location_requests_clarification(api_client, real_pois):
    request = {"query": "Хочу погулять рядом", "location": None, "lang": "ru"}
    response = api_client.post("/api/recommend", json=request)
    assert response.status_code == 200
    errors = validate_response(response.json(), request, real_pois, {"outcome": "clarification", "count_between": [0, 0]})
    assert not errors, "\n".join(errors)


@pytest.mark.parametrize("input_payload", [
    {}, {"query": []}, {"query": "test", "location": {"lat": 91, "lon": 71}},
    {"query": "test", "mode": "teleport"}, {"query": "test", "time_budget_min": -1},
    {"query": "test", "lang": "invalid"},
])
def test_invalid_request_returns_422(api_client, input_payload):
    response = api_client.post("/api/recommend", json=input_payload)
    assert response.status_code == 422
    assert response.json().get("detail"), "Validation errors need actionable detail"


def test_map_endpoint_returns_nearby_dataset_ids(api_client, real_pois):
    from eval.validators import haversine_m

    response = api_client.get("/api/pois", params={"lat": 51.128, "lon": 71.43, "radius_m": 1500})
    assert response.status_code == 200
    pois = response.json()
    assert isinstance(pois, list), "The map contract returns a POI list"
    known = {poi["id"]: poi for poi in real_pois}
    ids = []
    for poi in pois:
        assert all(field in poi for field in ("id", "name", "category", "lat", "lon"))
        assert poi["id"] in known
        assert poi["name"] == known[poi["id"]]["name"]
        assert poi["lat"] == pytest.approx(known[poi["id"]]["lat"], abs=0.00001)
        assert poi["lon"] == pytest.approx(known[poi["id"]]["lon"], abs=0.00001)
        assert haversine_m(51.128, 71.43, poi["lat"], poi["lon"]) <= 1501
        ids.append(poi["id"])
    assert len(ids) == len(set(ids)), "Map markers must not duplicate one POI"

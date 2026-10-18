"""Contract tests against the real data snapshot, in template mode (no API key needed)."""
import os

import pytest

os.environ["LLM_ENABLED"] = "false"
os.environ.setdefault("EMBED_MODEL", "off")
os.environ["WEATHER_ENABLED"] = "false"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.schemas import RecommendResponse  # noqa: E402

W = {"temperature_c": 9, "feels_like_c": 6, "wind_ms": 4}


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def post(c, **body):
    body.setdefault("now", "2026-10-18T15:00:00+05:00")
    body.setdefault("weather", W)
    r = c.post("/api/recommend", json=body)
    assert r.status_code == 200, r.text
    RecommendResponse.model_validate(r.json())
    return r.json()


def test_health_and_meta(client):
    h = client.get("/api/health").json()
    assert h["status"] == "ok" and h["pois"] > 1000 and h["llm"] in ("ok", "off")
    m = client.get("/api/meta").json()
    keys = {x["key"] for x in m["landmarks"]}
    assert {"baiterek", "khan_shatyr", "mega_silk_way", "airport"} <= keys


def test_recommend_contract(client):
    d = post(client, query="Я возле Байтерека, хочу погулять час")
    poi = [i for i in d["recommendations"] if i["source"] == "poi_data"]
    assert 1 <= len(poi) <= 3
    for i in poi:
        assert i["distance_m"] >= 0 and i["travel_min"] <= d["used_context"]["time_budget_min"]
        assert i["open_status"] in ("open", "unknown") and i["open_confidence"] in ("high", "low", "none")
        assert len(i["visit_min"]) == 2 and i["visit_min"][0] <= i["visit_min"][1]
        assert i["source_label"] and i["poi_id"]
    u = d["used_context"]
    assert {"location_source", "location_label", "radius_m", "time_budget_min", "mode", "filters", "now"} <= set(u)
    assert d["ai_generated"] is True and d["disclaimer"]


def test_location_is_rounded_and_not_echoed_precisely(client):
    d = post(client, query="кофе рядом", location={"lat": 51.1283456, "lon": 71.4304567})
    loc = d["used_context"]["location"]
    assert d["used_context"]["location_source"] == "gps_rounded" and loc["lat"] == 51.128 and loc["lon"] == 71.43
    assert "51.1283456" not in str(d)


def test_kids_never_get_bars(client):
    d = post(client, query="с ребёнком куда сходить вечером", location={"lat": 51.128, "lon": 71.43},
             now="2026-10-18T19:00:00+05:00")
    assert not any(i["category_detail"] in ("bar", "nightclub", "hookah") for i in d["recommendations"])


def test_extreme_cold_switches_to_taxi_and_indoor(client):
    d = post(client, query="погулять час", landmark="baiterek",
             weather={"temperature_c": -25, "feels_like_c": -33, "wind_ms": 10})
    assert d["used_context"]["mode"] == "car"
    assert not any("outdoor" in i["badges"] for i in d["recommendations"] if i["source"] == "poi_data")


def test_bad_input_422(client):
    assert client.post("/api/recommend", json={"time_budget_min": 5}).status_code == 422


def test_team_contract_request_and_no_location(client):
    d = post(client, query="Где выпить кофе?", mode="walk",
             profile={"with_kids": False, "tourist": False, "accessibility": False, "group_size": 1})
    assert d["recommendations"] == [] and d["used_context"]["location_source"] == "none"
    assert any("локацию" in n for n in d["notes"])


def test_pois_endpoint(client):
    r = client.get("/api/pois", params={"lat": 51.128, "lon": 71.43, "radius_m": 500}).json()
    assert r and all({"id", "name", "category", "lat", "lon"} <= set(x) for x in r)


def test_events_attach_to_venues(client):
    d = post(client, query="Хочу вечером на спектакль или концерт", location={"lat": 51.164, "lon": 71.418},
             now="2026-10-20T18:20:00+05:00", time_budget_min=180)
    evs = [r["event"] for r in d["recommendations"] if r["event"]]
    if evs:  # depends on the collected snapshot; when present it must be well-formed
        assert all(e["title"] and e["starts_at"] and e["source"] in ("ticketon", "sxodim") for e in evs)

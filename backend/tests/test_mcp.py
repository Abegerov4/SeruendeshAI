"""MCP connector: tools are listed and called through the MCP layer, in-process (no network, no LLM)."""
import datetime as dt
import json

import pytest
from fastapi.testclient import TestClient
from mcp import Client

from app import mcp_connector, service
from app.context import TZ
from app.main import app

FIXED_NOW = dt.datetime(2026, 10, 18, 15, 0, tzinfo=TZ)  # Sunday afternoon: deterministic opening hours


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def fixed_time(monkeypatch):
    real = service.parse_now
    monkeypatch.setattr(service, "parse_now", lambda s=None: real(s) if s else FIXED_NOW)


def call(client, fn):
    """Run an async MCP client session inside the app's event loop (the one TestClient started)."""
    async def run():
        async with Client(mcp_connector.server) as c:
            return await fn(c)
    return client.portal.call(run)


def payload(res) -> dict:
    assert not res.is_error, res.content
    return res.structured_content if res.structured_content else json.loads(res.content[0].text)


def test_tools_are_listed(client):
    tools = call(client, lambda c: c.list_tools()).tools
    names = {t.name for t in tools}
    assert names == {"recommend_places", "check_open_status", "get_poi", "list_landmarks"}
    rp = next(t for t in tools if t.name == "recommend_places")
    assert set(rp.input_schema["properties"]) == {"query", "landmark", "lat", "lon", "time_budget_min", "lang"}
    assert rp.input_schema["required"] == ["query"] and "ctx" not in rp.input_schema["properties"]


def test_recommend_places_through_mcp(client):
    d = payload(call(client, lambda c: c.call_tool("recommend_places", {"query": "Хочу кофе и погулять", "landmark": "baiterek"})))
    assert d["places"] and len(d["places"]) <= 3 and d["disclaimer"] and d["origin"].startswith("Байтерек")
    for p in d["places"]:
        assert p["name"] and p["why"] and p["what_to_do"] and p["opening"] and p["travel_min"] >= 1
        assert p["lat"] == round(p["lat"], 3) and p["lon"] == round(p["lon"], 3)
    pid = d["places"][0]["poi_id"]
    st = payload(call(client, lambda c: c.call_tool("check_open_status", {"poi_id": pid, "at": "2026-10-18T15:00"})))
    assert st["poi_id"] == pid and st["status"] in ("open", "closing_soon", "closed", "always", "unknown") and st["label"]
    poi = payload(call(client, lambda c: c.call_tool("get_poi", {"poi_id": pid})))
    assert poi["poi_id"] == pid and poi["name"] and "phone" not in poi


def test_gps_is_rounded_and_pii_masked(client):
    d = payload(call(client, lambda c: c.call_tool("recommend_places", {
        "query": "кофе рядом, мой номер +7 701 123 45 67", "lat": 51.1283456, "lon": 71.4304567, "lang": "en"})))
    assert d["lang"] == "en" and any("Personal data" in n for n in d["notes"])
    assert "51.1283456" not in json.dumps(d) and "701 123" not in json.dumps(d)


def test_landmarks_and_errors(client):
    lms = payload(call(client, lambda c: c.call_tool("list_landmarks", {})))["landmarks"]
    assert {"baiterek", "khan_shatyr"} <= {x["key"] for x in lms}
    res = call(client, lambda c: c.call_tool("get_poi", {"poi_id": "osm:nope"}))
    assert res.is_error and "unknown poi_id" in res.content[0].text
    res = call(client, lambda c: c.call_tool("check_open_status", {"poi_id": "osm:w230401645", "at": "tomorrow"}))
    assert res.is_error


def test_off_topic_through_mcp(client):
    d = payload(call(client, lambda c: c.call_tool("recommend_places", {"query": "кто президент США?", "landmark": "baiterek"})))
    assert d["off_topic"] is True and d["places"] == [] and any("Астан" in n for n in d["notes"])


def test_rate_limit(client, monkeypatch):
    monkeypatch.setattr(mcp_connector, "limiter", mcp_connector.RateLimiter(2))
    results = call(client, lambda c: _three_calls(c))
    assert [r.is_error for r in results] == [False, False, True] and "rate_limited" in results[2].content[0].text


async def _three_calls(c):
    return [await c.call_tool("list_landmarks", {}) for _ in range(3)]


def test_streamable_http_endpoint(client):
    """The connector is mounted in the FastAPI app at /connector/mcp (stateless JSON-RPC over HTTP)."""
    h = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
    init = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}}}
    r = client.post("/connector/mcp", json=init, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["result"]["serverInfo"]["name"] == "seruendesh"
    h["MCP-Protocol-Version"] = r.json()["result"]["protocolVersion"]
    r = client.post("/connector/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}, headers=h)
    assert r.status_code == 200 and {t["name"] for t in r.json()["result"]["tools"]} >= {"recommend_places", "get_poi"}
    r = client.post("/connector/mcp", headers=h, json={"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
        "name": "recommend_places", "arguments": {"query": "музей", "landmark": "khan_shatyr"}}})
    res = r.json()["result"]
    assert r.status_code == 200 and not res.get("isError") and res["structuredContent"]["origin"].startswith("Хан Шатыр")
    g = client.get("/connector/mcp")  # stateless: no SSE stream; and not swallowed by the SPA fallback
    assert g.status_code == 405 and g.json()["error"] == "method_not_allowed"

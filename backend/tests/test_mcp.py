import pytest
from mcp import Client

from backend.mcp_server.server import mcp

EXPECTED_TOOLS = {"search_pois", "recommend_places", "check_open_status", "plan_route", "get_poi"}


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def client():
    async with Client(mcp, raise_exceptions=True) as c:
        yield c


@pytest.mark.anyio
async def test_tools_listed_and_read_only(client):
    tools = {t.name: t for t in (await client.list_tools()).tools}
    assert set(tools) == EXPECTED_TOOLS
    assert all(t.annotations and t.annotations.read_only_hint for t in tools.values())
    assert all(t.description for t in tools.values())


@pytest.mark.anyio
async def test_search_pois_near_landmark(client):
    r = await client.call_tool("search_pois", {"query": "кофе розетки", "landmark": "Байтерек", "radius_m": 1500})
    data = r.structured_content
    assert data["location_label"] == "~ Байтерек"
    assert data["results"] and all(x["distance_m"] <= 1500 for x in data["results"])


@pytest.mark.anyio
async def test_check_open_status_monday_museum_closed(client):
    r = await client.call_tool("check_open_status", {"poi_id": "fixture:nur_alem", "at": "2026-10-19T12:00"})
    assert r.structured_content["status"] == "closed"
    r = await client.call_tool("check_open_status", {"poi_id": "fixture:botanical_garden"})
    assert r.structured_content["status"] == "unknown"


@pytest.mark.anyio
async def test_plan_route_orders_by_proximity(client):
    r = await client.call_tool("plan_route", {
        "poi_ids": ["fixture:botanical_garden", "fixture:nur_alem", "fixture:playground_expo"],
        "landmark": "Mega Silk Way", "time_budget_min": 300,
    })
    stops = [s["poi_id"] for s in r.structured_content["stops"]]
    assert stops[-1] == "fixture:botanical_garden"  # самая дальняя точка — последней
    assert r.structured_content["fits_budget"]


@pytest.mark.anyio
async def test_recommend_places_returns_contract(client):
    r = await client.call_tool("recommend_places", {"query": "куда сходить с ребёнком на час", "landmark": "Mega Silk Way"})
    data = r.structured_content
    assert 1 <= len(data["recommendations"]) <= 3
    assert data["used_context"]["location_source"] == "landmark"


@pytest.mark.anyio
async def test_get_poi_by_name_and_unknown_id_is_error(client):
    r = await client.call_tool("get_poi", {"poi_id": "Байтерек"})
    assert r.structured_content["id"] == "fixture:bayterek"
    async with Client(mcp) as c:  # без raise_exceptions ошибка tool приходит как результат
        r = await c.call_tool("get_poi", {"poi_id": "nope"})
        assert r.is_error

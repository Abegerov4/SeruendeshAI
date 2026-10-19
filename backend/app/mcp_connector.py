"""MCP connector: the same recommendation service as tools for any MCP client (Claude Desktop, Claude Code, ...).

Streamable HTTP at /connector/mcp (stateless, JSON responses), mounted in the FastAPI app. Same guards as the
HTTP API: PII masking and injection stripping of free text, coordinates rounded to ~100 m, per-client rate limit.
"""
from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from contextlib import asynccontextmanager
from typing import Any, Literal

from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp_types import ToolAnnotations
from starlette.responses import JSONResponse

from app.categories import CONTRACT_CATEGORY, label
from app.config import get_settings
from app.context import TZ, build_context
from app.features import feature_labels
from app.guards import RateLimiter, mask_pii, strip_injection, strip_links
from app.hours import opening_status
from app.schemas import LatLon, RecommendRequest
from app.service import recommend

Lang = Literal["ru", "kk", "en"]
INSTRUCTIONS = """Seruendesh: grounded recommendations of real places in Astana, Kazakhstan (open data: OSM, Wikidata,
Wikipedia). Give recommend_places a landmark (see list_landmarks) or approximate coordinates; distances, travel times
and opening hours are computed by code. Answers are AI-assisted: verify hours before visiting."""
server = MCPServer("seruendesh", title="Seruendesh — прогулки по Астане", instructions=INSTRUCTIONS, version="1.0",
                   website_url="https://seruendesh.site")
RO = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
limiter = RateLimiter(get_settings().mcp_rate_limit_per_min)
_runtime: Callable[[], Any] = lambda: None  # noqa: E731  (set by app.main.attach)
_state: dict[str, Any] = {}


def attach(get_runtime: Callable[[], Any]) -> None:
    global _runtime
    _runtime = get_runtime


def _client_key(ctx: Context | None) -> str:
    """Client IP for the limiter; in-process clients share 'local'."""
    req = headers = None
    try:
        req = ctx.request_context.request if ctx else None
        headers = getattr(req, "headers", None) or ctx.headers
    except (ValueError, AttributeError):
        pass
    # only the ASGI peer is trusted (uvicorn --proxy-headers resolves Railway's proxy); a raw
    # X-Forwarded-For from the client must not pick its own rate-limit bucket (audit B01)
    ip = req.client.host if getattr(req, "client", None) else None
    return ip or "local"


def _guard(ctx: Context | None):
    if limiter.limited(_client_key(ctx)):
        raise ToolError("rate_limited: too many calls, try again in a minute")
    rt = _runtime()
    if rt is None:
        raise ToolError("service is starting, try again shortly")
    return rt


def _clean(text: str | None, n: int = 300) -> str | None:
    """Open-data text goes to another LLM: drop links and instruction-like sentences."""
    if not text:
        return None
    return strip_injection(strip_links(text))[0][:n] or None


def _poi(rt, poi_id: str) -> dict:
    i = rt.store.by_id.get((poi_id or "").strip()[:80])
    if i is None:
        raise ToolError("unknown poi_id (use ids returned by recommend_places)")
    return rt.store.pois[i]


@server.tool(annotations=RO)
async def recommend_places(query: str, landmark: str | None = None, lat: float | None = None, lon: float | None = None,
                           time_budget_min: int | None = None, lang: Lang = "ru",
                           ctx: Context | None = None) -> dict[str, Any]:
    """Recommend 1-3 real places in Astana for a free-text request (Russian, Kazakh or English), e.g.
    "кофе и прогулка на час", "museum with kids". Give the start as a landmark key/name from list_landmarks
    (e.g. "baiterek") or as approximate lat/lon (rounded to ~100 m). time_budget_min: 10-480 (default 60).
    Returns places with why / what_to_do, travel minutes, opening-hours label and source link, plus notes."""
    rt = _guard(ctx)
    loc = None
    if lat is not None and lon is not None:
        loc = LatLon(lat=round(float(lat), 3), lon=round(float(lon), 3))
    lm = None
    if landmark:
        lm = strip_injection(mask_pii(landmark)[0])[0].strip()[:80] or None
    budget = max(10, min(int(time_budget_min), 480)) if time_budget_min else None
    req = RecommendRequest(query=(query or "")[:1000], landmark=lm, location=loc, time_budget_min=budget, lang=lang)
    r = await recommend(rt, req)  # masks PII / strips injections in the query itself
    return {
        "summary": r["summary"], "lang": r["lang"], "origin": r["used_context"]["location_label"],
        "places": [{"poi_id": x["poi_id"], "name": x["name"], "category": x["category_label"], "why": x["why"],
                    "what_to_do": x["what_to_do"], "travel_min": x["travel_min"], "travel_mode": x["travel_mode"],
                    "opening": x["opening"]["label"], "open_status": x["open_status"], "source_url": x["source_url"],
                    "lat": round(x["lat"], 3), "lon": round(x["lon"], 3)} for x in r["recommendations"]],
        "route": r["route"]["summary"] if r.get("route") else None,
        "notes": r["notes"], "disclaimer": r["disclaimer"], "off_topic": r.get("off_topic", False),
    }


@server.tool(annotations=RO)
async def check_open_status(poi_id: str, at: str | None = None, lang: Lang = "ru",
                            ctx: Context | None = None) -> dict[str, Any]:
    """Opening-hours status of a place (poi_id from recommend_places) now or at `at` (ISO 8601, Astana time if no
    offset, e.g. "2026-10-20T19:30"). Never claims "open" without listed hours: status may be unknown."""
    rt = _guard(ctx)
    p = _poi(rt, poi_id)
    when = dt.datetime.now(TZ)
    if at:
        try:
            d = dt.datetime.fromisoformat(at.strip().replace("Z", "+00:00"))
        except ValueError:
            raise ToolError("`at` must be ISO 8601, e.g. 2026-10-20T19:30") from None
        when = d.astimezone(TZ) if d.tzinfo else d.replace(tzinfo=TZ)
    c = build_context(when, None, False)
    op = opening_status(p, c.local_naive, 30, lang, c.holiday)
    return {"poi_id": p["id"], "name": p.get("names", {}).get(lang) or p["name"], "at": when.isoformat(timespec="minutes"),
            "status": op["status"], "confidence": op["confidence"], "label": op["label"], "raw": op["raw"],
            "next_change": op["next_change"], "holiday": c.holiday}


@server.tool(annotations=RO)
async def get_poi(poi_id: str, lang: Lang = "ru", ctx: Context | None = None) -> dict[str, Any]:
    """Public facts about one place (poi_id from recommend_places): name, category, address, coordinates,
    listed opening hours, website / source link, confirmed features, step-free access, short description."""
    rt = _guard(ctx)
    p = _poi(rt, poi_id)
    w = p.get("features", {}).get("wheelchair")
    return {"poi_id": p["id"], "name": p.get("names", {}).get(lang) or p["name"], "names": p.get("names", {}),
            "category": CONTRACT_CATEGORY.get(p["category"], "other"), "category_detail": p["category"],
            "category_label": label(p["category"], lang), "lat": round(p["lat"], 5), "lon": round(p["lon"], 5),
            "address": p.get("address"), "opening_hours": p.get("opening_hours"),
            "website": p.get("website") if (p.get("website") or "").startswith("http") else None,
            "source_url": p.get("source_url") if (p.get("source_url") or "").startswith("http") else None,
            "features": feature_labels(p.get("features", {}), lang),
            "accessibility": w if w in ("yes", "limited", "no") else "unknown",
            "description": _clean(p.get("description")), "description_source": p.get("description_source"),
            "data_sources": p.get("sources", [])}


@server.tool(annotations=RO)
async def list_landmarks(ctx: Context | None = None) -> dict[str, Any]:
    """Curated Astana landmarks usable as `landmark` in recommend_places (key, name, coordinates)."""
    rt = _guard(ctx)
    return {"landmarks": [{"key": g["landmark_key"], "name": g["name"], "lat": round(g["lat"], 5), "lon": round(g["lon"], 5)}
                          for g in rt.store.gazetteer if g["kind"] == "landmark" and g.get("landmark_key")]}


# --- transport ------------------------------------------------------------------------------------

@asynccontextmanager
async def serve():
    """Run a fresh streamable-HTTP session manager for one app lifespan (a manager can only run once)."""
    server.streamable_http_app(stateless_http=True, json_response=True, max_request_body_size=256 * 1024,
                               transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False))
    sm = server.session_manager
    async with sm.run():
        _state["sm"] = sm
        try:
            yield
        finally:
            _state.pop("sm", None)


class _Endpoint:
    """Raw ASGI endpoint for /connector/mcp (a class instance, so Starlette routes every HTTP method to it)."""

    async def __call__(self, scope, receive, send):
        sm = _state.get("sm")
        if sm is None:
            await JSONResponse({"error": "mcp_unavailable"}, status_code=503)(scope, receive, send)
            return
        if scope.get("method") == "GET":  # stateless server: no server-initiated SSE stream to keep open
            await JSONResponse({"error": "method_not_allowed", "hint": "MCP streamable HTTP: POST JSON-RPC to this URL"},
                               status_code=405, headers={"Allow": "POST, OPTIONS"})(scope, receive, send)
            return
        await sm.handle_request(scope, receive, send)


asgi = _Endpoint()

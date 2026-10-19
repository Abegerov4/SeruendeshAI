"""Ready-made themed walks from where the user is: icons of the capital, a green walk, museums, coffee and
sights, an evening walk, a walk with a child. Each one is a normal answer of the same pipeline (reachability on
the street graph, opening hours on arrival, the time budget) built from a fixed request, so the route, the stops
and the explanations are as honest as any other answer. Computed in parallel and cached briefly per area."""
from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app.context import build_context, parse_now
from app.geo import round_coord
from app.limiting import api_client_key, limiter
from app.schemas import HomePlace, Lang, LatLon, RecommendRequest

router = APIRouter()
RT: dict = {}
_cache: dict[str, tuple[float, list]] = {}
TTL_S = 20 * 60

ICONS = ("baiterek", "khan_shatyr", "ak_orda", "pyramid", "kazakh_eli", "hazret_sultan", "astana_opera", "national_museum", "nurzhol")
THEMES = [
    {"key": "symbols", "emoji": "🏛", "budget": 120, "targets": ICONS, "query": "Покажи главные достопримечательности и символы города рядом, маршрут на 2 часа",
     "title": {"ru": "Символы столицы", "kk": "Елорда символдары", "en": "Icons of the capital"}},
    {"key": "green", "emoji": "🌳", "budget": 90, "day": True, "query": "Маршрут по паркам, скверам и бульварам на полтора часа, погулять на свежем воздухе",
     "title": {"ru": "Зелёная прогулка", "kk": "Жасыл серуен", "en": "Green walk"}},
    {"key": "culture", "emoji": "🎨", "budget": 150, "query": "Маршрут по музеям и галереям на 2-3 часа",
     "title": {"ru": "Музеи и галереи", "kk": "Мұражайлар мен галереялар", "en": "Museums and galleries"}},
    {"key": "coffee", "emoji": "☕", "budget": 75, "query": "Маршрут: кофейня и красивые места рядом, погулять час с кофе",
     "title": {"ru": "Кофе и красивые места", "kk": "Кофе және әдемі жерлер", "en": "Coffee and sights"}},
    {"key": "evening", "emoji": "🌙", "budget": 90, "evening": True, "targets": ("baiterek", "khan_shatyr", "nurzhol", "pyramid", "ak_orda", "kazakh_eli"), "query": "Вечерний маршрут: красивые места с подсветкой и видом на город",
     "title": {"ru": "Вечерняя Астана", "kk": "Кешкі Астана", "en": "Astana at night"}},
    {"key": "kids", "emoji": "👶", "budget": 120, "day": True, "query": "Маршрут с ребёнком: детские площадки и интерактивные места на 2 часа",
     "title": {"ru": "С ребёнком", "kk": "Баламен", "en": "With a child"}},
]


class IdeasRequest(BaseModel):
    model_config = ConfigDict(strict=True)
    lang: Lang | None = None
    location: LatLon | None = None
    landmark: str | None = Field(None, max_length=80)
    home: HomePlace | None = None
    use_home: bool | None = None
    now: str | None = None


def _area_key(req: IdeasRequest, lang: str, hour: int) -> str:
    if req.use_home and req.home:
        where = f"h{round_coord(req.home.lat, 2)},{round_coord(req.home.lon, 2)}"
    elif req.location:
        where = f"g{round_coord(req.location.lat, 2)},{round_coord(req.location.lon, 2)}"
    else:
        where = f"l{req.landmark}"
    return f"{where}|{lang}|{req.now or hour}"


async def build_ideas(rt, req: IdeasRequest) -> list[dict]:
    from app.service import recommend

    lang = req.lang or "ru"
    now = parse_now(req.now)
    dark = build_context(now, None, False).is_dark  # the real sunset, not a fixed hour
    themes = [th for th in THEMES if (not th.get("evening") or dark or now.hour >= 18) and (not th.get("day") or not dark)]

    async def one(th: dict) -> dict | None:
        r = RecommendRequest(query=th["query"], lang=lang, want_route=True, time_budget_min=th["budget"], location=req.location,
                             landmark=req.landmark if not req.location else None, home=req.home, use_home=req.use_home,
                             now=req.now, channel=None)
        try:
            resp = await recommend(rt, r, llm_parse_enabled=False, extra_targets=th.get("targets", ()))
        except Exception:
            return None
        route = resp.get("route")
        if not route or len(route.get("order") or []) < 2:
            return None
        names = {x["poi_id"]: x["name"] for x in resp["recommendations"]}
        stops = [names[p] for p in route["order"] if p in names]
        return {"key": th["key"], "emoji": th["emoji"], "title": th["title"].get(lang, th["title"]["ru"]),
                "total_min": route.get("total_min"), "stops": stops, "query": th["query"], "response": resp}

    found = [x for x in await asyncio.gather(*(one(th) for th in themes)) if x]
    seen, out = set(), []
    for x in found:  # two themes that end up with the same stops are one idea
        key = tuple(sorted(x["stops"]))
        if key not in seen:
            seen.add(key)
            out.append(x)
    return out


@router.post("/api/routes/ideas", tags=["recommend"], summary="Themed walks from the user's place: 3–6 ready mini-routes")
async def api_route_ideas(req: IdeasRequest, request: Request):
    if not limiter.allow("ideas", api_client_key(request), 6, 60):
        raise HTTPException(status_code=429, detail="Too many requests, try again in a minute")
    rt = RT.get("rt")
    if rt is None:
        raise HTTPException(status_code=503, detail="starting")
    lang = req.lang or "ru"
    if not (req.location or req.landmark or (req.home and req.use_home)):
        return {"ideas": []}  # no start: walks are built from the user, never from a guessed landmark (and not cached)
    key = _area_key(req, lang, parse_now(req.now).hour)
    if (hit := _cache.get(key)) and time.time() - hit[0] < TTL_S:
        return {"ideas": hit[1]}
    ideas = await build_ideas(rt, req)
    if ideas:  # an empty answer (a slow model, a closed hour) is not kept for 20 minutes
        _cache[key] = (time.time(), ideas)
    if len(_cache) > 300:
        _cache.pop(next(iter(_cache)))
    return {"ideas": ideas}

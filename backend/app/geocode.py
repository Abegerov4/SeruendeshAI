"""Address search for the user's home («Кенесары 40»): our gazetteer first, then OpenStreetMap Nominatim inside
Astana. Results are rounded to ~100 m; the typed address is not logged or stored by us (Nominatim sees the
query, as its usage policy describes). Light use only: rate-limited and cached in memory."""
from __future__ import annotations

import logging
from collections import OrderedDict

import httpx
from fastapi import APIRouter, HTTPException, Request

from app.geo import in_astana, round_coord
from app.limiting import api_client_key, limiter
from app.query import resolve_landmark
from app.textnorm import fold

log = logging.getLogger("seru.geocode")
router = APIRouter()
NOMINATIM = "https://nominatim.openstreetmap.org/search"
VIEWBOX = "71.20,51.30,71.75,50.95"  # Astana, lon/lat corners
_cache: OrderedDict[str, list[dict]] = OrderedDict()
RT: dict = {}  # set by main: the runtime with the gazetteer


async def geocode(q: str, http: httpx.AsyncClient) -> list[dict]:
    key = fold(q)
    if key in _cache:
        _cache.move_to_end(key)
        return _cache[key]
    out: list[dict] = []
    rt = RT.get("rt")
    if rt is not None and (g := resolve_landmark(q, rt.store.gazetteer)) and key in g.get("keys", []):
        out.append({"label": g["name"], "lat": round_coord(g["lat"]), "lon": round_coord(g["lon"]), "source": "gazetteer"})
    try:
        r = await http.get(NOMINATIM, timeout=6, params={
            "q": q if "астан" in key or "astana" in key else f"{q}, Астана", "format": "jsonv2", "limit": 5,
            "countrycodes": "kz", "viewbox": VIEWBOX, "bounded": 1, "accept-language": "ru"},
            headers={"User-Agent": "SeruendeshAI/0.1 (hackathon walking assistant; https://seruendesh.site)"})
        r.raise_for_status()
        for x in r.json():
            lat, lon = round_coord(float(x["lat"])), round_coord(float(x["lon"]))
            if in_astana(lat, lon):
                label = ", ".join(p.strip() for p in x.get("display_name", "").split(",")[:3])
                out.append({"label": label, "lat": lat, "lon": lon, "source": "openstreetmap"})
    except Exception as exc:  # the gazetteer answer (if any) still helps
        log.info("nominatim unavailable: %s", type(exc).__name__)
    seen, uniq = set(), []
    for x in out:
        if (x["lat"], x["lon"]) not in seen:
            seen.add((x["lat"], x["lon"]))
            uniq.append(x)
    _cache[key] = uniq[:5]
    if len(_cache) > 500:
        _cache.popitem(last=False)
    return uniq[:5]


@router.get("/api/geocode", tags=["meta"], summary="Find an address or place in Astana (for the saved home), rounded to ~100 m")
async def api_geocode(q: str, request: Request):
    q = q.strip()[:120]
    if len(q) < 3:
        return {"results": []}
    if not limiter.allow("geocode", api_client_key(request), 20, 60):
        raise HTTPException(status_code=429, detail="Too many requests, try again in a minute")
    rt = RT.get("rt")
    return {"results": await geocode(q, rt.http if rt else httpx.AsyncClient())}

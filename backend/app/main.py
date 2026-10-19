"""SeruendeshAI API — FastAPI app.

    uv run --project backend uvicorn app.main:app --port 8000
"""
from __future__ import annotations

import asyncio
import math
import logging
import os
import time
from pathlib import Path
from collections import defaultdict
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.datastructures import UploadFile

from app.paths import ROOT_DIR, GRAPH_FILE

from app import insights, mcp_connector, photo, telegram
from app.auth import router as auth_router
from app.categories import CATEGORIES
from app.config import get_settings
from app.db import db_kind, init_db
from app.limiting import api_client_key, limiter
from app.embedder import get_embedder
from app.geo import load_graph
from app.i18n import t
from app.llm import client as llm_client, provider_status
from app.llm import usage_begin, usage_summary
from app.categories import CONTRACT_CATEGORY
from app.geo import car_minutes, fallback_walk_m, hav_m, in_astana, round_coord
from app.query import detect_lang, resolve_landmark
from app.schemas import (RouteRequest, RouteToPlace, CategoryOut, FeedbackRequest, FeedbackResponse, HealthResponse, LandmarkOut, MetaFeatures,
                         MetaResponse, PhotoRecommendResponse, PoiBrief, RecommendRequest, RecommendResponse)
from app.context import parse_now
from app.service import Runtime, recommend, snap_pois
from app.store import load_store

settings = get_settings()
logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("app")
RT: dict[str, Runtime] = {}
_PHOTO_SLOTS = asyncio.Semaphore(2)
FEEDBACK: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))  # aggregated counts only, no user data
mcp_connector.attach(lambda: RT.get("rt"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    t0 = time.perf_counter()
    init_db()
    store = load_store(settings.embed_model)
    snapshot_path = store.manifest.get("snapshot_path")
    graph = load_graph(Path(snapshot_path) / GRAPH_FILE.name if snapshot_path else None)
    nodes, snap = snap_pois(store, graph)
    embedder = None
    if store.emb is not None:
        embedder = await asyncio.get_running_loop().run_in_executor(None, get_embedder, settings.embed_model)
        if embedder is None:
            store.emb = None
    http = httpx.AsyncClient(headers={"User-Agent": "SeruendeshAI/0.1"})
    RT["rt"] = Runtime(store=store, graph=graph, poi_nodes=nodes, poi_snap=snap, embedder=embedder, http=http, cache={})
    if settings.llm_warmup_enabled and llm_client() is not None:
        asyncio.create_task(_warmup())  # first call with a new strict schema is slow; pay it at startup
    log.info("ready in %.1fs: %d POIs, graph=%s, dense=%s, llm=%s, db=%s", time.perf_counter() - t0, store.size,
             graph is not None, embedder is not None, llm_client() is not None, db_kind())
    bot_task = asyncio.create_task(telegram.start(int(os.getenv("PORT", "8000"))))  # Telegram webhook, if configured
    async with mcp_connector.serve():  # MCP session manager lives as long as the app
        yield
    bot_task.cancel()
    await telegram.stop()
    await http.aclose()


async def _warmup():
    from app.generate import SYSTEM, GenOut
    from app.llm import parse
    from app.query import PARSE_SYSTEM, LLMParsed
    try:
        await asyncio.gather(
            parse(LLMParsed, PARSE_SYSTEM, "Хочу кофе рядом", models=[settings.llm_parse_model], timeout_s=20, max_output_tokens=300),
            parse(GenOut, SYSTEM, 'TARGET LANGUAGE: Russian\nQUERY: кофе\nCANDIDATES:\n{"id":"c1","name":"Кофейня","category":"Кофейня"}',
                  models=settings.llm_chain[:1], timeout_s=20, max_output_tokens=300),
            parse(photo.PhotoGuessLLM, photo.PHOTO_SYSTEM, "TARGET LANGUAGE: Russian\nPLACES:\nbaiterek — Байтерек\n(no photo)",
                  models=settings.llm_chain[:1], timeout_s=20, max_output_tokens=100))
        log.info("LLM schemas warmed up")
    except Exception as e:  # warm-up is best effort
        log.warning("warm-up failed: %s", type(e).__name__)


app = FastAPI(
    title="SeruendeshAI API",
    version="1.0",
    description="RAG walking assistant for Astana: 1–3 grounded recommendations with why / what to do, "
                "opening-hours confidence, honest source labels and an optional mini-route.",
    lifespan=lifespan,
)
app.include_router(auth_router)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_origin_regex=settings.cors_origin_regex or None,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_credentials=True,
    allow_headers=["*"],
)
# MCP connector (streamable HTTP, stateless): registered before the SPA catch-all below
app.add_route("/connector/mcp", mcp_connector.asgi, include_in_schema=False)
app.include_router(telegram.router)

def _rate_limited(request: Request) -> bool:
    return not limiter.allow("recommend", api_client_key(request), settings.rate_limit_per_min, 60)


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    log.exception("unhandled error on %s", request.url.path)
    return JSONResponse(status_code=500, content={"error": {"code": "internal", "message": "Internal error, please retry"}})


@app.post("/api/recommend", response_model=RecommendResponse, tags=["recommend"],
          summary="Get 1–3 nearby recommendations (+ optional mini-route)")
async def api_recommend(req: RecommendRequest, request: Request):
    if await asyncio.to_thread(_rate_limited, request):
        raise HTTPException(status_code=429, detail="Too many requests, try again in a minute")
    resp = await recommend(RT["rt"], req)
    await asyncio.to_thread(insights.record, resp)  # anonymous counters only (see app/insights.py)
    return resp


@app.get("/api/insights", tags=["meta"], summary="City Insights: k-anonymous demand by ~1 km cell, intent and time")
async def api_insights(days: int = 30, lang: str = "ru"):
    return await asyncio.to_thread(insights.summary, max(1, min(days, 90)), lang if lang in ("ru", "kk", "en") else "ru")


@app.get("/api/meta", response_model=MetaResponse, tags=["meta"], summary="Landmarks, categories, data version")
async def api_meta():
    st = RT["rt"].store
    lms = [LandmarkOut(key=g["landmark_key"], name=g["name"], lat=round(g["lat"], 5), lon=round(g["lon"], 5))
           for g in st.gazetteer if g["kind"] == "landmark"]
    cats = [CategoryOut(key=c.key, group=c.group, icon=c.icon, labels={"ru": c.labels[0], "kk": c.labels[1], "en": c.labels[2]})
            for c in CATEGORIES.values()]
    feats = MetaFeatures(password_reset_email=bool(settings.smtp_host and settings.smtp_from),
                         photo=llm_client() is not None, mcp=True)
    return MetaResponse(landmarks=lms, categories=cats, data_built_at=st.manifest.get("built_at"),
                        poi_count=st.size, sources=st.manifest.get("sources", {}), features=feats)


def _photo_err(status: int, code: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": code})


_PHOTO_FORM = {"type": "object", "required": ["image"], "properties": {
    "image": {"type": "string", "format": "binary", "description": "JPEG / PNG / WebP, up to 8 MB"},
    "query": {"type": "string", "description": "Optional request text, e.g. «кофе рядом»"},
    "landmark": {"type": "string", "description": "Optional fallback landmark key if the photo is not recognised"},
    "lang": {"type": "string", "enum": ["ru", "kk", "en"]}}}


@app.post("/api/recommend/photo", response_model=PhotoRecommendResponse, tags=["recommend"],
          summary="Recommendations around a known place recognised in a photo (multipart form)",
          openapi_extra={"requestBody": {"required": True, "content": {"multipart/form-data": {"schema": _PHOTO_FORM}}}},
          responses={413: {"description": '{"error": "photo_too_large"}'},
                     415: {"description": '{"error": "unsupported_media_type" | "unsupported_format"}'},
                     422: {"description": '{"error": "image_required" | "invalid_image" | "invalid_form" | "invalid_lang"}'},
                     503: {"description": '{"error": "photo_unavailable"} (no LLM configured)'}})
async def api_recommend_photo(request: Request):
    """The photo is decoded with a pixel cap, stripped of EXIF (GPS is never read), downscaled to 1024 px and
    re-encoded before the LLM picks a place from a closed list; nothing is stored."""
    key = api_client_key(request)
    if not limiter.allow("recommend", key, settings.rate_limit_per_min, 60) or \
            not limiter.allow("photo", key, settings.photo_rate_limit_per_min, 60):
        raise HTTPException(status_code=429, detail="Too many requests, try again in a minute")
    size = request.headers.get("content-length", "")
    if size.isdigit() and int(size) > photo.MAX_BYTES + 256 * 1024:
        return _photo_err(413, "photo_too_large")
    if "multipart/form-data" not in request.headers.get("content-type", ""):
        return _photo_err(415, "unsupported_media_type")
    try:
        form = await request.form(max_files=1, max_fields=10)
    except Exception:  # malformed multipart / too many parts
        return _photo_err(422, "invalid_form")
    try:
        image = form.get("image") or form.get("file")
        if not isinstance(image, UploadFile):
            return _photo_err(422, "image_required")
        if (image.content_type or "").split(";")[0].strip().lower() not in photo.ALLOWED_TYPES:
            return _photo_err(415, "unsupported_media_type")
        data = await image.read(photo.MAX_BYTES + 1)
    finally:
        await form.close()
    if len(data) > photo.MAX_BYTES:
        return _photo_err(413, "photo_too_large")
    if not data:
        return _photo_err(422, "image_required")
    query = form.get("query") if isinstance(form.get("query"), str) else ""
    landmark = (form.get("landmark") if isinstance(form.get("landmark"), str) else "").strip()[:80] or None
    lang = form.get("lang") or None
    if lang not in (None, "ru", "kk", "en"):
        return _photo_err(422, "invalid_lang")
    channel = form.get("channel") if form.get("channel") in ("web", "telegram") else None
    if llm_client() is None:
        return _photo_err(503, "photo_unavailable")
    try:
        async with _PHOTO_SLOTS:  # at most 2 decodes at a time (audit B11)
            jpeg = await asyncio.get_running_loop().run_in_executor(None, photo.prepare_image, data)
    except photo.PhotoError as e:
        return _photo_err(415 if str(e) == "unsupported_format" else 422, str(e))
    del data

    rt = RT["rt"]
    meter, mark = usage_begin()
    ui_lang = lang or (detect_lang(query) if sum(ch.isalpha() for ch in query) >= 3 else "ru")
    places = photo.closed_set(rt.store)
    guess, _ = await photo.guess_place(jpeg, places, ui_lang)
    hit = places.get(guess.place_id) if guess and guess.place_id else None
    recognized = bool(hit and guess.confidence in ("medium", "high"))
    start = hit["id"] if recognized else landmark
    resp = await recommend(rt, RecommendRequest(query=query[:1000] if start else "", landmark=start, lang=lang or ui_lang,
                                                channel=channel))
    lang_out = resp["lang"]
    if recognized:
        resp["notes"] = [t("photo_recognized", lang_out, name=hit["name"])] + resp["notes"]
    elif start:
        resp["notes"] = [t("photo_fallback", lang_out)] + resp["notes"]
    else:  # not recognised and no fallback: ask for a landmark (no recommendations)
        resp["summary"] = t("photo_unrecognized", lang_out)
        resp["notes"] = [t("photo_unrecognized", lang_out)]
    resp["notes"].append(t("photo_privacy", lang_out))
    resp["photo_guess"] = {"recognized": recognized, "place_id": hit["id"] if hit else None,
                           "kind": hit["kind"] if hit else None, "name": hit["name"] if hit else None,
                           "confidence": guess.confidence if guess else "low", "description": guess.description if guess else ""}
    resp["llm"]["usage"] = u = usage_summary(meter[mark:])  # vision + recommendation calls
    log.info("photo id=%s recognized=%s kind=%s items=%d tokens_in=%d tokens_out=%d cost_usd=%s", resp["request_id"],
             recognized, hit["kind"] if hit else None, len(resp["recommendations"]), u["input_tokens"], u["output_tokens"],
             u["cost_usd"])
    return resp


@app.get("/api/health", response_model=HealthResponse, tags=["meta"])
async def api_health():
    rt = RT.get("rt")
    if not rt:
        return HealthResponse(status="degraded", pois=0, llm="off", poi_count=0, events=0, dense_retrieval=False,
                              walk_graph=False, llm_configured=False, data_built_at=None)
    ok = rt.store.size > 0
    provider = provider_status()
    ready = ok and (settings.readiness_profile == "template" or provider["status"] == "ok")
    return HealthResponse(status="ok" if ready else "degraded", pois=rt.store.size, llm=provider["status"],
                          poi_count=rt.store.size, events=len(rt.store.events),
                          dense_retrieval=rt.store.emb is not None, walk_graph=rt.graph is not None,
                          llm_configured=llm_client() is not None, data_built_at=rt.store.manifest.get("built_at"),
                          runtime_id="ayat", readiness_profile=settings.readiness_profile, ready=ready,
                          snapshot_version=rt.store.manifest.get("snapshot_version") or rt.store.manifest.get("canonical_sha256")
                          or (("pipeline-" + rt.store.manifest["pois_sha"]) if rt.store.manifest.get("pois_sha") else None),
                          provider_verified_at=provider["verified_at"])


@app.post("/api/route", response_model=RouteToPlace, tags=["recommend"],
          summary="Route from the user (rounded GPS or a landmark) to one recommended place",
          responses={404: {"description": "unknown poi_id"}, 422: {"description": "no usable start (GPS outside Astana and no landmark)"}})
async def route_to_place(req: RouteRequest, request: Request):
    if not await asyncio.to_thread(limiter.allow, "route", api_client_key(request), settings.rate_limit_per_min * 2, 60):
        return JSONResponse({"detail": "Too many requests"}, status_code=429)
    rt = RT["rt"]
    st = rt.store
    i = st.by_id.get(req.poi_id)
    if i is None:
        return JSONResponse({"error": "unknown_poi"}, status_code=404)
    p = st.pois[i]
    if req.location and in_astana(req.location.lat, req.location.lon):
        origin, source = (round_coord(req.location.lat), round_coord(req.location.lon)), "gps_rounded"
    else:
        g = resolve_landmark(req.landmark or "", st.gazetteer) if req.landmark else None
        if not g:
            return JSONResponse({"error": "location_required"}, status_code=422)
        origin, source = (g["lat"], g["lon"]), "landmark"
    dest = (p["lat"], p["lon"])
    straight = float(hav_m(origin[0], origin[1], dest[0], dest[1]))
    poly, geometry, dist = [origin, dest], "straight", None
    graph = rt.graph
    if graph is not None and graph.covers(*origin) and graph.covers(*dest) and straight < 15000:
        D, P, src = await asyncio.to_thread(graph.from_source, origin[0], origin[1], 20000)
        d_dst, i_dst = graph.snap(dest[0], dest[1])
        reach = float(D[int(i_dst[0])])
        if reach < float("inf") and float(d_dst[0]) < 400:
            dist = reach + float(d_dst[0])
            poly, geometry = [origin, *graph.path_polyline(P, src, int(i_dst[0])), dest], "network"
    if dist is None:
        dist = fallback_walk_m(st.river, origin[0], origin[1], dest[0], dest[1])
    if req.mode == "car":
        dist, minutes = car_minutes(straight, parse_now(None).hour)
    else:
        minutes = int(math.ceil(dist / 75.0))  # 4.5 km/h, rounded up like the recommendation cards
    o_lat, o_lon = origin
    return {"poi_id": p["id"], "name": p["name"], "mode": req.mode, "distance_m": int(round(dist / 10) * 10),
            "travel_min": max(1, minutes), "geometry": geometry,
            "polyline": [(round(a, 6), round(b, 6)) for a, b in poly],
            "origin": {"lat": round_coord(o_lat), "lon": round_coord(o_lon)}, "origin_source": source,
            "links": {"2gis": f"https://2gis.kz/astana/directions/points/{o_lon}%2C{o_lat}%7C{dest[1]}%2C{dest[0]}",
                      "osm": f"https://www.openstreetmap.org/directions?engine=fossgis_osrm_foot&route={o_lat}%2C{o_lon}%3B{dest[0]}%2C{dest[1]}"}}


@app.get("/api/pois", response_model=list[PoiBrief], tags=["meta"], summary="POIs around a point for the map (brief)")
async def api_pois(lat: float, lon: float, radius_m: int = 1500, limit: int = 300):
    st = RT["rt"].store
    radius_m = max(50, min(radius_m, 10000))
    d = hav_m(round(lat, 3), round(lon, 3), st.lat, st.lon)
    idx = [int(i) for i in d.argsort() if d[i] <= radius_m][: max(1, min(limit, 1000))]
    return [PoiBrief(id=st.pois[i]["id"], name=st.pois[i]["name"], category=CONTRACT_CATEGORY.get(st.pois[i]["category"], "other"),
                     category_detail=st.pois[i]["category"], lat=st.pois[i]["lat"], lon=st.pois[i]["lon"]) for i in idx]


@app.post("/api/feedback", response_model=FeedbackResponse, tags=["feedback"],
          summary="Report outdated info (closed, wrong hours). Stores only aggregated counters.")
async def api_feedback(fb: FeedbackRequest):
    if fb.poi_id not in RT["rt"].store.by_id:
        raise HTTPException(status_code=404, detail="Unknown poi_id")
    FEEDBACK[fb.poi_id][fb.kind] += 1
    log.info("feedback poi=%s kind=%s", fb.poi_id, fb.kind)
    return FeedbackResponse(ok=True, message="Спасибо! Учтём при следующем обновлении данных.")


# --- the built frontend (React/Vite) is served by the same service: one domain, no CORS -------------
DIST = os.environ.get("FRONTEND_DIST") or str(ROOT_DIR / "frontend" / "dist")
if os.path.isdir(os.path.join(DIST, "assets")):
    from pathlib import Path

    _dist = Path(DIST).resolve()
    app.mount("/assets", StaticFiles(directory=_dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str):
        if path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not found")
        f = (_dist / path).resolve()
        if path and f.is_file() and _dist in f.parents:
            return FileResponse(f)
        return FileResponse(_dist / "index.html", headers={"Cache-Control": "no-cache"})

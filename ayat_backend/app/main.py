"""SeruendeshAI API — FastAPI app.

    uv run --project ayat_backend uvicorn ayat_backend.app.main:app --port 8000
"""
from __future__ import annotations

import asyncio
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

from ayat_backend.app.paths import ROOT_DIR, GRAPH_FILE

from ayat_backend.app.auth import router as auth_router
from ayat_backend.app.categories import CATEGORIES
from ayat_backend.app.config import get_settings
from ayat_backend.app.db import db_kind, init_db
from ayat_backend.app.limiting import client_key, limiter
from ayat_backend.app.embedder import get_embedder
from ayat_backend.app.geo import load_graph
from ayat_backend.app.llm import client as llm_client, provider_status
from ayat_backend.app.categories import CONTRACT_CATEGORY
from ayat_backend.app.geo import hav_m
from ayat_backend.app.schemas import (CategoryOut, FeedbackRequest, FeedbackResponse, HealthResponse, LandmarkOut, MetaResponse,
                         PoiBrief, RecommendRequest, RecommendResponse)
from ayat_backend.app.service import Runtime, recommend, snap_pois
from ayat_backend.app.store import load_store

settings = get_settings()
logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("app")
RT: dict[str, Runtime] = {}
FEEDBACK: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))  # aggregated counts only, no user data


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
    yield
    await http.aclose()


async def _warmup():
    from ayat_backend.app.generate import SYSTEM, GenOut
    from ayat_backend.app.llm import parse
    from ayat_backend.app.query import PARSE_SYSTEM, LLMParsed
    try:
        await asyncio.gather(
            parse(LLMParsed, PARSE_SYSTEM, "Хочу кофе рядом", models=[settings.llm_parse_model], timeout_s=20, max_output_tokens=300),
            parse(GenOut, SYSTEM, 'TARGET LANGUAGE: Russian\nQUERY: кофе\nCANDIDATES:\n{"id":"c1","name":"Кофейня","category":"Кофейня"}',
                  models=settings.llm_chain[:1], timeout_s=20, max_output_tokens=300))
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

def _rate_limited(request: Request) -> bool:
    return not limiter.allow("recommend", client_key(request), settings.rate_limit_per_min, 60)


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    log.exception("unhandled error on %s", request.url.path)
    return JSONResponse(status_code=500, content={"error": {"code": "internal", "message": "Internal error, please retry"}})


@app.post("/api/recommend", response_model=RecommendResponse, tags=["recommend"],
          summary="Get 1–3 nearby recommendations (+ optional mini-route)")
async def api_recommend(req: RecommendRequest, request: Request):
    if await asyncio.to_thread(_rate_limited, request):
        raise HTTPException(status_code=429, detail="Too many requests, try again in a minute")
    return await recommend(RT["rt"], req)


@app.get("/api/meta", response_model=MetaResponse, tags=["meta"], summary="Landmarks, categories, data version")
async def api_meta():
    st = RT["rt"].store
    lms = [LandmarkOut(key=g["landmark_key"], name=g["name"], lat=round(g["lat"], 5), lon=round(g["lon"], 5))
           for g in st.gazetteer if g["kind"] == "landmark"]
    cats = [CategoryOut(key=c.key, group=c.group, icon=c.icon, labels={"ru": c.labels[0], "kk": c.labels[1], "en": c.labels[2]})
            for c in CATEGORIES.values()]
    return MetaResponse(landmarks=lms, categories=cats, data_built_at=st.manifest.get("built_at"),
                        poi_count=st.size, sources=st.manifest.get("sources", {}))


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
                          snapshot_version=rt.store.manifest.get("snapshot_version") or rt.store.manifest.get("canonical_sha256"),
                          provider_verified_at=provider["verified_at"])


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

"""SeruendeshAI API — FastAPI app.

    uv run uvicorn app.main:app --port 8000
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.categories import CATEGORIES
from app.config import get_settings
from app.embedder import get_embedder
from app.geo import load_graph
from app.llm import client as llm_client
from app.categories import CONTRACT_CATEGORY
from app.geo import hav_m
from app.schemas import (CategoryOut, FeedbackRequest, FeedbackResponse, HealthResponse, LandmarkOut, MetaResponse,
                         PoiBrief, RecommendRequest, RecommendResponse)
from app.service import Runtime, recommend, snap_pois
from app.store import load_store

settings = get_settings()
logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("app")
RT: dict[str, Runtime] = {}
FEEDBACK: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))  # aggregated counts only, no user data


@asynccontextmanager
async def lifespan(app: FastAPI):
    t0 = time.perf_counter()
    store = load_store(settings.embed_model)
    graph = load_graph()
    nodes, snap = snap_pois(store, graph)
    embedder = None
    if store.emb is not None:
        embedder = await asyncio.get_running_loop().run_in_executor(None, get_embedder, settings.embed_model)
        if embedder is None:
            store.emb = None
    http = httpx.AsyncClient(headers={"User-Agent": "SeruendeshAI/0.1"})
    RT["rt"] = Runtime(store=store, graph=graph, poi_nodes=nodes, poi_snap=snap, embedder=embedder, http=http, cache={})
    if llm_client() is not None:
        asyncio.create_task(_warmup())  # first call with a new strict schema is slow; pay it at startup
    log.info("ready in %.1fs: %d POIs, graph=%s, dense=%s, llm=%s", time.perf_counter() - t0, store.size,
             graph is not None, embedder is not None, llm_client() is not None)
    yield
    await http.aclose()


async def _warmup():
    from app.generate import SYSTEM, GenOut
    from app.llm import parse
    from app.query import PARSE_SYSTEM, LLMParsed
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
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_origin_regex=settings.cors_origin_regex or None,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

_hits: dict[str, deque] = defaultdict(deque)


def _rate_limited(request: Request) -> bool:
    """Tiny in-memory per-client limiter (IP kept in RAM for 60 s only, never logged)."""
    key = request.headers.get("x-forwarded-for", request.client.host if request.client else "?").split(",")[0]
    q, now = _hits[key], time.time()
    while q and now - q[0] > 60:
        q.popleft()
    if len(q) >= settings.rate_limit_per_min:
        return True
    q.append(now)
    return False


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    log.exception("unhandled error on %s", request.url.path)
    return JSONResponse(status_code=500, content={"error": {"code": "internal", "message": "Internal error, please retry"}})


@app.post("/api/recommend", response_model=RecommendResponse, tags=["recommend"],
          summary="Get 1–3 nearby recommendations (+ optional mini-route)")
async def api_recommend(req: RecommendRequest, request: Request):
    if _rate_limited(request):
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
    return HealthResponse(status="ok" if ok else "degraded", pois=rt.store.size, llm="ok" if llm_client() else "off",
                          poi_count=rt.store.size, events=len(rt.store.events),
                          dense_retrieval=rt.store.emb is not None, walk_graph=rt.graph is not None,
                          llm_configured=llm_client() is not None, data_built_at=rt.store.manifest.get("built_at"))


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

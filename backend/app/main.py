"""FastAPI-приложение. Запуск из корня репозитория:  uvicorn backend.app.main:app --reload"""
import logging
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError

from . import cache, llm, tracing, vision
from . import rag_adapter as rag
from .config import get_settings
from .guards import mask_pii
from .pipeline import photo_not_recognized, recommend, recommend_with_stats
from .schemas import Lang, Mode, PoiBrief, Profile, RecommendRequest, RecommendResponse

# В логах только request_id / счётчики / latency — никаких координат и текста запроса
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)

@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    tracing.flush()  # дослать трейсы при остановке


app = FastAPI(title="Seruendesh AI — Astana walk assistant", version="0.2.0", lifespan=lifespan)
app.add_middleware(vision.PhotoUploadLimitMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict:
    provider = llm.provider_status()
    return {
        "status": "ok",
        "pois": len(rag.all_pois()),
        "rag": rag.backend_name(),
        "search": rag.search_mode(),
        "llm": provider["status"] if llm.is_enabled() else "disabled",
        "provider_verified_at": provider["verified_at"],
        "runtime_id": "secondary",
        "models": llm.models() if llm.is_enabled() else None,
        "tracing": "langfuse" if tracing.is_enabled() else "disabled",
        "cache": cache.responses.stats(),
    }


@app.post("/api/recommend", response_model=RecommendResponse)
def api_recommend(req: RecommendRequest) -> RecommendResponse:
    return recommend(req)


@app.post("/api/recommend/photo", response_model=RecommendResponse)
async def api_recommend_photo(
    image: UploadFile = File(..., description="Фото того, что вокруг (JPEG/PNG/WEBP, ≤ 8 МБ)"),
    query: str = Form("Что интересного рядом?", max_length=1000),
    time_budget_min: int | None = Form(None, ge=10, le=720),
    mode: Mode | None = Form(None),
    lang: Lang | None = Form(None),
    now: datetime | None = Form(None),
    with_kids: bool = Form(False),
    tourist: bool = Form(False),
    accessibility: bool = Form(False),
    group_size: int = Form(1, ge=1, le=50),
) -> RecommendResponse:
    """Мультимодальный режим: узнаём место по фото и советуем, куда пойти дальше. Фото не сохраняется."""
    try:
        req = RecommendRequest(
            query=query, time_budget_min=time_budget_min, mode=mode, lang=lang, now=now,
            profile=Profile(with_kids=with_kids, tourist=tourist, accessibility=accessibility, group_size=group_size),
        )
    except ValidationError as e:
        raise HTTPException(422, detail=e.errors(include_url=False, include_context=False)) from e
    try:
        data = await image.read(vision.MAX_BYTES + 1)
        data_url = await run_in_threadpool(vision.prepare_image, data, image.content_type)
    except vision.PhotoError as e:
        raise HTTPException(422, detail=str(e)) from e

    with tracing.span("recommend-photo", input={"query": mask_pii(query)}) as root:
        guess = await run_in_threadpool(vision.identify_landmark, data_url, mask_pii(query))
        place = vision.resolve(guess)
        root.update(output={"landmark": guess.landmark, "confidence": guess.confidence, "resolved": bool(place)})
        if not place:
            return photo_not_recognized(req, guess.seen)
        resp, _ = await run_in_threadpool(recommend_with_stats, req, True, place)
    conf = {"high": "уверенно", "medium": "предположительно"}.get(guess.confidence, "")
    resp.notes.insert(0, f"По фото {conf} определили: {place['label']}. Если это не так, укажите место текстом.")
    return resp


@app.get("/api/pois", response_model=list[PoiBrief])
def api_pois(
    lat: float | None = None,
    lon: float | None = None,
    radius_m: int = Query(default=3000, ge=100, le=20000),
    limit: int = Query(default=500, ge=1, le=5000),
) -> list[dict]:
    pois = rag.all_pois()
    if lat is not None and lon is not None:
        pois = [p for p in pois if rag.haversine_m(lat, lon, p["lat"], p["lon"]) <= radius_m]
    return [{k: p[k] for k in ("id", "name", "category", "lat", "lon")} for p in pois[:limit]]

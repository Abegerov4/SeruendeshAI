"""FastAPI-приложение. Запуск из корня репозитория:  uvicorn backend.app.main:app --reload"""
import logging

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

from . import llm
from . import rag_adapter as rag
from .config import get_settings
from .pipeline import recommend
from .schemas import PoiBrief, RecommendRequest, RecommendResponse

# В логах только request_id / счётчики / latency — никаких координат и текста запроса
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)

app = FastAPI(title="Seruendesh AI — Astana walk assistant", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict:
    return {
        "status": "ok",
        "pois": len(rag.all_pois()),
        "rag": rag.backend_name(),
        "llm": "ok" if llm.is_enabled() else "disabled",
        "models": llm.models() if llm.is_enabled() else None,
    }


@app.post("/api/recommend", response_model=RecommendResponse)
def api_recommend(req: RecommendRequest) -> RecommendResponse:
    return recommend(req)


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

"""Единая точка входа в RAG-слой.

Реальная реализация живёт в пакете `rag/` (ветка feature/data-rag). Пока его нет в репозитории
или включён MOCK_RAG=1 — используем mock_rag поверх фикстуры с той же сигнатурой.
"""
import logging
from datetime import datetime

from .config import get_settings

log = logging.getLogger("backend.rag")

_backend = "mock"
if not get_settings().mock_rag:
    try:
        from rag import geo as _geo, hours as _hours, retriever as _retriever  # type: ignore

        _backend = "real"
    except ImportError:
        log.warning("package rag/ not found — falling back to mock RAG")

if _backend == "mock":
    from . import mock_rag as _mock

    _geo = _hours = _retriever = _mock


def backend_name() -> str:
    return _backend


def search(query: str, lat: float | None, lon: float | None, radius_m: int = 2000,
           categories: list[str] | None = None, top_k: int = 15) -> list[dict]:
    return _retriever.search(query, lat, lon, radius_m=radius_m, categories=categories, top_k=top_k)


def resolve_landmark(text: str) -> dict | None:
    return _geo.resolve_landmark(text)


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> int:
    return _geo.haversine_m(lat1, lon1, lat2, lon2)


def open_status(opening_hours: str | None, dt: datetime) -> tuple[str, str]:
    return _hours.open_status(opening_hours, dt)


def all_pois() -> list[dict]:
    """Полный список POI (для /api/pois и проверки poi_id)."""
    if _backend == "mock":
        return _mock.load_pois()
    loader = getattr(_retriever, "all_pois", None)
    if loader:
        return loader()
    import json

    from .config import REPO_ROOT

    path = REPO_ROOT / "data" / "processed" / "pois.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []

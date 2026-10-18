"""Единая точка входа в RAG-слой.

Реальная реализация — пакет `rag/` (Data & RAG). Если его нет или включён MOCK_RAG=1 —
mock_rag поверх фикстуры с той же сигнатурой.

Что добавляет адаптер поверх rag/:
- деградация поиска: нет dense-индекса / устарел / недоступны эмбеддинги → BM25, а не 500-я ошибка;
- ориентиры: полный текст запроса ищем только локально (не отправляем фразы пользователей в Nominatim),
  в сеть уходит лишь короткое извлечённое название ориентира; плюс устойчивость к склонениям («у Байтерека»).
"""
import json
import logging
import os
from datetime import datetime
from functools import lru_cache

from .config import REPO_ROOT, get_settings

log = logging.getLogger("backend.rag")

_backend = "mock"
if not get_settings().mock_rag:
    try:
        from rag import geo as _geo, hours as _hours, retriever as _retriever  # type: ignore

        _backend = "real"
    except ImportError:
        log.warning("package rag/ not found — falling back to mock RAG")

from . import mock_rag as _mock

if _backend == "mock":
    _geo = _hours = _retriever = _mock

_search_mode = os.getenv("RAG_SEARCH_MODE", "hybrid") if _backend == "real" else "mock"
_degraded_reason: str | None = None


def backend_name() -> str:
    return _backend


def search_mode() -> dict:
    return {"mode": _search_mode, "degraded_reason": _degraded_reason}


def search(query: str, lat: float | None, lon: float | None, radius_m: int = 2000,
           categories: list[str] | None = None, top_k: int = 15) -> list[dict]:
    global _search_mode, _degraded_reason
    try:
        return _retriever.search(query, lat, lon, radius_m=radius_m, categories=categories, top_k=top_k)
    except Exception as e:  # RuntimeError (нет/устарел индекс), ошибки эмбеддингов и сети
        if _backend != "real" or _search_mode == "bm25":
            raise
        _search_mode, _degraded_reason = "bm25", f"{type(e).__name__}: {str(e)[:120]}"
        os.environ["RAG_SEARCH_MODE"] = "bm25"  # rag/ читает режим из окружения на каждый вызов
        log.warning("dense search unavailable, degraded to BM25: %s", _degraded_reason)
        return _retriever.search(query, lat, lon, radius_m=radius_m, categories=categories, top_k=top_k)


def resolve_landmark(text: str, allow_network: bool = True) -> dict | None:
    """allow_network=False — только локальный поиск (для полного текста запроса пользователя)."""
    if not text or not text.strip():
        return None
    if _backend == "real":
        hit = _local_landmark(text)
        if hit or not allow_network:
            return hit
        try:
            return _geo.resolve_landmark(text)  # rag/: имена POI → встроенные ориентиры → Nominatim
        except Exception as e:
            log.warning("landmark lookup failed: %s", type(e).__name__)
            return None
    return _mock.resolve_landmark(text)


def _local_landmark(text: str) -> dict | None:
    # 1) словарь ориентиров с подстроками — переживает склонения («возле Байтерека»)
    low = text.casefold().replace("ё", "е")
    for alias in sorted(_mock.LANDMARKS, key=len, reverse=True):
        if alias in low:
            lat, lon, label = _mock.LANDMARKS[alias]
            return {"lat": lat, "lon": lon, "label": label}
    # 2) точные/нечёткие совпадения по именам базы и встроенным ориентирам rag/ — без сети
    for key, label, lat, lon in _poi_names():
        if len(key) >= 5 and key[:-1] in low:  # [:-1] — допускаем смену окончания
            return {"lat": lat, "lon": lon, "label": label}
    return None


@lru_cache(maxsize=1)
def _poi_names() -> list[tuple[str, str, float, float]]:
    out = []
    for p in all_pois():
        if p.get("category") in {"monument", "attraction", "museum", "mall", "park", "theatre", "viewpoint", "gallery"}:
            for n in (p["name"], p.get("name_en"), p.get("name_kk")):
                if n:
                    out.append((n.casefold(), p["name"], p["lat"], p["lon"]))
    return sorted(out, key=lambda x: -len(x[0]))


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> int:
    return _geo.haversine_m(lat1, lon1, lat2, lon2)


def open_status(opening_hours: str | None, dt: datetime) -> tuple[str, str]:
    return _hours.open_status(opening_hours, dt)


@lru_cache(maxsize=1)
def _load_processed() -> list[dict]:
    path = REPO_ROOT / "data" / "processed" / "pois.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []


def all_pois() -> list[dict]:
    """Полный список POI (для /api/pois, проверки poi_id, фото-кандидатов)."""
    if _backend == "mock":
        return _mock.load_pois()
    return _load_processed()

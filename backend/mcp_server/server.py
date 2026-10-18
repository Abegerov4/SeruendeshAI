"""MCP-сервер Seruendesh AI: городской помощник по Астане как набор tools для любого MCP-хоста
(Claude Desktop / Claude Code / Cursor / свой агент).

Зачем MCP, а не только HTTP API: один и тот же набор инструментов подключается к любому ассистенту
без написания интеграции — ассистент сам решает, когда искать места, проверять часы или строить маршрут.

Все tools только читают данные (read_only_hint): ничего не создают, не отправляют и не удаляют.
Координаты округляются до ~100 м и не логируются — как в HTTP API.

Запуск:
  python -m backend.mcp_server.server            # stdio (для Claude Desktop / Claude Code)
  python -m backend.mcp_server.server --http     # streamable HTTP на :8001/mcp
"""
import argparse
import logging
import sys
from datetime import datetime
from typing import Literal

from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from backend.app import rag_adapter as rag
from backend.app.config import ASTANA_TZ
from backend.app.pipeline import recommend_with_stats
from backend.app.routing import build_route, default_visit, travel_min
from backend.app.schemas import Location, Profile, RecommendRequest, RecommendResponse

# stdio-транспорт занимает stdout — логи только в stderr
logging.basicConfig(level=logging.WARNING, stream=sys.stderr)

mcp = MCPServer(
    "seruendesh-astana",
    instructions=(
        "Помощник по прогулкам в Астане на открытых данных о местах (POI). "
        "Для готового совета вызывай recommend_places; для своего подбора — search_pois, "
        "затем check_open_status и plan_route. Не утверждай, что место открыто, если статус unknown."
    ),
)
READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)
Mode = Literal["walk", "car", "transit"]


class PoiHit(BaseModel):
    poi_id: str
    name: str
    category: str
    distance_m: int | None
    travel_min: int | None
    open_status: Literal["open", "closed", "unknown"]
    description: str | None
    tags: list[str]
    rating: float | None
    source_url: str | None


class SearchResult(BaseModel):
    location_label: str | None = Field(description="Откуда считались расстояния (округлено)")
    radius_m: int
    results: list[PoiHit]


class PoiCard(BaseModel):
    id: str
    name: str
    name_en: str | None = None
    name_kk: str | None = None
    category: str
    tags: list[str] = []
    description: str | None = None
    description_source: str | None = Field(None, description="osm | wikipedia | website | llm_generated")
    address: str | None = None
    opening_hours: str | None = None
    phone: str | None = None
    website: str | None = None
    wheelchair: str | None = None
    kid_friendly: bool | None = None
    rating: float | None = None
    source: str | None = None
    source_url: str | None = None


class OpenStatus(BaseModel):
    poi_id: str
    name: str
    status: Literal["open", "closed", "unknown"]
    confidence: Literal["high", "low", "none"]
    opening_hours: str | None
    checked_at: str


class RouteStop(BaseModel):
    poi_id: str
    name: str
    leg_min: int = Field(description="Дорога до этой точки от предыдущей")
    visit_min: list[int]


class RoutePlan(BaseModel):
    total_min: int
    fits_budget: bool
    stops: list[RouteStop]
    note: str


def _now(at: str | None) -> datetime:
    dt = datetime.fromisoformat(at) if at else datetime.now(ASTANA_TZ)
    return dt.replace(tzinfo=ASTANA_TZ) if dt.tzinfo is None else dt.astimezone(ASTANA_TZ)


def _origin(landmark: str | None, lat: float | None, lon: float | None) -> tuple[float | None, float | None, str | None]:
    if lat is not None and lon is not None:
        return round(lat, 3), round(lon, 3), "~ указанная точка (±100 м)"
    if landmark and (lm := rag.resolve_landmark(landmark)):
        return lm["lat"], lm["lon"], f"~ {lm['label']}"
    return None, None, None


def _poi(poi_id: str) -> dict:
    by_id = {p["id"]: p for p in rag.all_pois()}
    if poi_id in by_id:
        return by_id[poi_id]
    # допускаем название вместо id
    for p in by_id.values():
        if p["name"].lower() == poi_id.lower():
            return p
    raise ValueError(f"Место «{poi_id}» не найдено. Используй poi_id из search_pois.")


@mcp.tool(title="Найти места рядом", annotations=READ_ONLY)
def search_pois(
    query: str,
    landmark: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
    radius_m: int = 1500,
    categories: list[str] | None = None,
    mode: Mode = "walk",
    top_k: int = 5,
) -> SearchResult:
    """Поиск мест (POI) в Астане по смыслу запроса с учётом расстояния.

    Когда вызывать: нужно подобрать места самому (кафе, парк, музей…) рядом с ориентиром или точкой.
    query — что ищем своими словами («тихое кафе с розетками»).
    landmark — ориентир («Байтерек», «Mega Silk Way»), либо lat/lon.
    categories — фильтр из: cafe, restaurant, bar, nightlife, museum, gallery, theatre, cinema, park,
    viewpoint, monument, attraction, playground, mall, library, coworking, sport.
    Возвращает до top_k мест с расстоянием, временем в пути и статусом «открыто сейчас».
    """
    olat, olon, label = _origin(landmark, lat, lon)
    radius_m = max(200, min(radius_m, 10_000))
    hits = rag.search(query, olat, olon, radius_m=radius_m, categories=categories or None, top_k=max(1, min(top_k, 15)))
    now = _now(None)
    results = [PoiHit(
        poi_id=h["id"], name=h["name"], category=h["category"], distance_m=h.get("distance_m"),
        travel_min=travel_min(h.get("distance_m"), mode), open_status=rag.open_status(h.get("opening_hours"), now)[0],
        description=(h.get("description") or "")[:300] or None, tags=h.get("tags", []),
        rating=h.get("rating"), source_url=h.get("source_url"),
    ) for h in hits]
    return SearchResult(location_label=label, radius_m=radius_m, results=results)


@mcp.tool(title="Готовые рекомендации", annotations=ToolAnnotations(read_only_hint=True, open_world_hint=True))
def recommend_places(
    query: str,
    landmark: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
    time_budget_min: int | None = None,
    mode: Mode | None = None,
    with_kids: bool = False,
    accessibility: bool = False,
    lang: Literal["ru", "kk", "en"] | None = None,
) -> RecommendResponse:
    """Полный ответ помощника: 1–3 места с «почему», временем на визит, «что делать» и мини-маршрутом.

    Когда вызывать: пользователь спрашивает «куда сходить / что посоветуешь» и нужен готовый совет.
    Ориентир можно передать в landmark или прямо в тексте query («я возле Хан Шатыра»).
    Ответ уже проверен: места только из базы, расстояния посчитаны кодом, неизвестные часы помечены.
    """
    if landmark and landmark.lower() not in query.lower():
        query = f"{query} (я возле {landmark})"
    req = RecommendRequest(
        query=query,
        location=Location(lat=lat, lon=lon) if lat is not None and lon is not None else None,
        time_budget_min=time_budget_min, mode=mode, lang=lang,
        profile=Profile(with_kids=with_kids, accessibility=accessibility),
    )
    resp, _ = recommend_with_stats(req)
    return resp


@mcp.tool(title="Проверить часы работы", annotations=READ_ONLY)
def check_open_status(poi_id: str, at: str | None = None) -> OpenStatus:
    """Открыто ли место в заданный момент (по умолчанию — сейчас, время Астаны UTC+5).

    poi_id — id из search_pois (или точное название). at — ISO-время, например «2026-10-18T23:30».
    Если часов в данных нет, статус unknown — не выдавай это за «открыто».
    """
    p = _poi(poi_id)
    dt = _now(at)
    status, conf = rag.open_status(p.get("opening_hours"), dt)
    return OpenStatus(poi_id=p["id"], name=p["name"], status=status, confidence=conf,
                      opening_hours=p.get("opening_hours"), checked_at=dt.isoformat())


@mcp.tool(title="Построить мини-маршрут", annotations=READ_ONLY)
def plan_route(
    poi_ids: list[str],
    landmark: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
    time_budget_min: int = 90,
    mode: Mode = "walk",
) -> RoutePlan:
    """Порядок обхода 2–5 мест от стартовой точки (ближайший следующий) с временем в пути и на месте.

    Когда вызывать: выбраны несколько мест и нужно понять, в каком порядке идти и влезает ли в бюджет.
    """
    if not 2 <= len(poi_ids) <= 5:
        raise ValueError("Нужно от 2 до 5 мест")
    olat, olon, label = _origin(landmark, lat, lon)
    pois = [_poi(i) for i in poi_ids]
    start = (olat, olon) if olat is not None else (pois[0]["lat"], pois[0]["lon"])
    recs = [{"poi_id": p["id"], "lat": p["lat"], "lon": p["lon"],
             "visit_min": default_visit(p["category"], time_budget_min)} for p in pois]
    route = build_route(start, recs, time_budget_min=10_000, mode=mode)  # порядок без обрезки
    order = route["order"] if route else [r["poi_id"] for r in recs]
    by_id = {p["id"]: p for p in pois}
    stops, pos, total = [], start, 0
    for pid in order:
        p = by_id[pid]
        leg = travel_min(rag.haversine_m(pos[0], pos[1], p["lat"], p["lon"]), mode) or 0
        visit = default_visit(p["category"], time_budget_min)
        stops.append(RouteStop(poi_id=pid, name=p["name"], leg_min=leg, visit_min=visit))
        total += leg + sum(visit) // 2
        pos = (p["lat"], p["lon"])
    return RoutePlan(
        total_min=total, fits_budget=total <= time_budget_min, stops=stops,
        note=f"Старт: {label or by_id[order[0]]['name']}. Время в пути оценочное (по прямой с поправкой на улицы).",
    )


@mcp.tool(title="Карточка места", annotations=READ_ONLY)
def get_poi(poi_id: str) -> PoiCard:
    """Все известные данные о месте: описание и его источник, адрес, часы, контакты, доступность, рейтинг."""
    p = _poi(poi_id)
    return PoiCard.model_validate({k: p.get(k) for k in PoiCard.model_fields if k in p})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--http", action="store_true", help="streamable HTTP вместо stdio")
    ap.add_argument("--port", type=int, default=8001)
    args = ap.parse_args()
    if args.http:
        mcp.run(transport="streamable-http", host="0.0.0.0", port=args.port, json_response=True, stateless_http=True)
    else:
        mcp.run()


if __name__ == "__main__":
    main()

"""Детерминированная математика: радиус поиска, время в пути, длительность визита, мини-маршрут."""
from .rag_adapter import haversine_m

# метров в минуту; DETOUR — поправка на то, что по улицам дольше, чем по прямой
SPEED = {"walk": 80, "car": 400, "transit": 250}
DETOUR = {"walk": 1.3, "car": 1.4, "transit": 1.3}
OVERHEAD_MIN = {"walk": 0, "car": 5, "transit": 8}  # парковка / ожидание

MIN_RADIUS, MAX_RADIUS = 300, 10_000

VISIT_MIN = {
    "cafe": (30, 60), "restaurant": (60, 90), "bar": (60, 120), "nightlife": (60, 120),
    "museum": (60, 90), "gallery": (40, 60), "theatre": (120, 180), "cinema": (120, 150),
    "park": (30, 60), "viewpoint": (20, 40), "monument": (10, 20), "attraction": (30, 60),
    "playground": (30, 60), "mall": (60, 120), "library": (60, 120), "coworking": (60, 120),
    "sport": (60, 90), "other": (20, 40),
}


def search_radius_m(time_budget_min: int, mode: str) -> int:
    # примерно треть бюджета уходит на дорогу в одну сторону
    r = SPEED[mode] * time_budget_min * 0.3
    return int(min(MAX_RADIUS, max(MIN_RADIUS, r)))


def travel_min(distance_m: int | None, mode: str) -> int | None:
    if distance_m is None:
        return None
    return max(1, round(distance_m * DETOUR[mode] / SPEED[mode] + OVERHEAD_MIN[mode]))


def default_visit(category: str, time_budget_min: int) -> list[int]:
    lo, hi = VISIT_MIN.get(category, VISIT_MIN["other"])
    hi = min(hi, max(10, time_budget_min))
    return [min(lo, hi), hi]


def build_route(start: tuple[float, float] | None, recs: list[dict], time_budget_min: int, mode: str) -> dict | None:
    """Nearest neighbour от пользователя. Маршрут возвращаем, только если в нём ≥ 2 точки и он влезает в бюджет."""
    if start is None or len(recs) < 2:
        return None
    left = list(recs)
    pos, order, total = start, [], 0.0
    while left:
        nxt = min(left, key=lambda r: haversine_m(pos[0], pos[1], r["lat"], r["lon"]))
        leg = travel_min(haversine_m(pos[0], pos[1], nxt["lat"], nxt["lon"]), mode) or 0
        visit = sum(nxt["visit_min"]) / 2
        if order and total + leg + visit > time_budget_min * 1.1:
            break
        order.append(nxt["poi_id"])
        total += leg + visit
        pos = (nxt["lat"], nxt["lon"])
        left.remove(nxt)
    if len(order) < 2:
        return None
    return {"order": order, "total_min": round(total)}

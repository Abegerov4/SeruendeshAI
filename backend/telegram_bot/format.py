"""Форматирование ответа пайплайна в HTML-сообщение Telegram. Чистые функции — легко тестировать."""
from html import escape

from backend.app.schemas import RecommendResponse

OPEN_BADGE = {"open": "🟢 открыто", "closed": "🔴 закрыто", "unknown": "⚪ часы неизвестны"}
SOURCE_BADGE = {"poi_data": "📍 данные POI", "generated": "✨ идея ИИ"}
MODE_WORD = {"walk": "пешком", "car": "на машине", "transit": "на транспорте"}

# Быстрые сценарии после отправки геолокации: callback_data -> текст запроса
SCENARIOS = {
    "walk": ("🚶 Прогулка на час", "Хочу прогуляться около часа"),
    "coffee": ("☕ Кофе", "Хочу тихое место с кофе рядом"),
    "kids": ("👶 С ребёнком", "Я с ребёнком, где рядом площадка или интерактивный музей?"),
    "night": ("🌙 Ночью", "Ищу необычную ночную активность рядом"),
    "sights": ("🏛 Что посмотреть", "Я турист, что интересного посмотреть рядом за пару часов?"),
}


def map_link(lat: float, lon: float) -> str:
    return f"https://www.openstreetmap.org/?mlat={lat}&mlon={lon}#map=17/{lat}/{lon}"


def format_response(resp: RecommendResponse) -> str:
    ctx = resp.used_context
    lines: list[str] = []
    if resp.recommendations:
        mode = MODE_WORD.get(ctx.mode, ctx.mode)
        for i, r in enumerate(resp.recommendations, 1):
            dist = f"{r.distance_m} м, {r.travel_min} мин {mode}" if r.distance_m is not None else ""
            lines += [
                f"<b>{i}. {escape(r.name)}</b>" + (f" ({dist})" if dist else ""),
                f"<i>Почему:</i> {escape(r.why)}",
                f"<i>Что делать:</i> {escape(r.what_to_do)} (~{r.visit_min[0]}–{r.visit_min[1]} мин)",
                f"{OPEN_BADGE[r.open_status]} · {SOURCE_BADGE[r.source]} · "
                f'<a href="{map_link(r.lat, r.lon)}">на карте</a>',
                "",
            ]
        if resp.route:
            names = {r.poi_id: r.name for r in resp.recommendations}
            order = " → ".join(escape(names[p]) for p in resp.route.order if p in names)
            lines += [f"🗺 <b>Мини-маршрут:</b> {order} (≈{resp.route.total_min} мин)", ""]
    for n in resp.notes:
        lines.append(f"ℹ️ {escape(n)}")
    # прозрачность: какие данные использованы
    used = [escape(ctx.location_label or "локация не указана")]
    if ctx.radius_m:
        used.append(f"радиус {ctx.radius_m / 1000:.1f} км")
    used.append(f"{ctx.time_budget_min} мин")
    if ctx.filters:
        used.append("фильтры: " + escape(", ".join(ctx.filters[:5])))
    lines += ["", "<i>Учёл: " + " · ".join(used) + "</i>", f"<i>{escape(resp.disclaimer)}</i>"]
    return "\n".join(lines).strip()

"""Format an /api/recommend JSON answer as a Telegram HTML message. Pure functions, easy to test.
Ported from Abegerov4's backend/telegram_bot/format.py to the shared API response."""
from html import escape

OPEN_BADGE = {"open": "🟢 открыто", "closed": "🔴 закрыто", "unknown": "⚪ часы неизвестны"}
SOURCE_BADGE = {"poi_data": "📍 данные POI", "generated": "✨ идея ИИ"}
MODE_WORD = {"walk": "пешком", "car": "на машине", "transit": "на транспорте"}

# quick scenarios after a location is shared: callback_data -> request text
SCENARIOS = {
    "walk": ("🚶 Прогулка на час", "Хочу прогуляться около часа"),
    "coffee": ("☕ Кофе", "Хочу тихое место с кофе рядом"),
    "kids": ("👶 С ребёнком", "Я с ребёнком, где рядом площадка или интерактивный музей?"),
    "night": ("🌙 Ночью", "Ищу необычную вечернюю активность рядом"),
    "sights": ("🏛 Что посмотреть", "Я турист, что интересного посмотреть рядом за пару часов?"),
}


def map_link(lat: float, lon: float) -> str:
    return f"https://2gis.kz/astana/geo/{lon}%2C{lat}"


def format_response(resp: dict) -> str:
    ctx = resp.get("used_context") or {}
    lines: list[str] = []
    if g := resp.get("photo_guess"):
        if g.get("recognized") and g.get("name"):
            lines += [f"📷 Похоже, это <b>{escape(g['name'])}</b>.", ""]
    recs = resp.get("recommendations") or []
    if recs and (summary := (resp.get("summary") or "").strip()):
        lines += [escape(summary), ""]
    mode = MODE_WORD.get(ctx.get("mode"), ctx.get("mode") or "")
    for i, r in enumerate(recs, 1):
        dist = f"{r['distance_m']} м, {r['travel_min']} мин {mode}" if r.get("distance_m") is not None else ""
        visit = r.get("visit_min") or [r.get("visit_suggested_min"), r.get("visit_suggested_min")]
        opening = (r.get("opening") or {}).get("label") or OPEN_BADGE.get(r.get("open_status"), "")
        lines += [
            f"<b>{i}. {escape(r['name'])}</b>" + (f" ({dist})" if dist else ""),
            f"<i>Почему:</i> {escape(r.get('why') or '')}",
            f"<i>Что делать:</i> {escape(r.get('what_to_do') or '')} (~{visit[0]}–{visit[1]} мин)",
            f"{escape(opening)} · {SOURCE_BADGE.get(r.get('source'), '')} · <a href=\"{map_link(r['lat'], r['lon'])}\">маршрут</a>",
            "",
        ]
    if (route := resp.get("route")) and recs:
        names = {r["poi_id"]: r["name"] for r in recs}
        order = " → ".join(escape(names[p]) for p in route.get("order", []) if p in names)
        if order:
            lines += [f"🗺 <b>Мини-маршрут:</b> {order} (≈{route.get('total_min')} мин)", ""]
    for n in resp.get("notes") or []:
        lines.append(f"ℹ️ {escape(n)}")
    used = [escape(ctx.get("location_label") or "локация не указана")]
    if ctx.get("radius_m"):
        used.append(f"радиус {ctx['radius_m'] / 1000:.1f} км")
    if ctx.get("time_budget_min"):
        used.append(f"{ctx['time_budget_min']} мин")
    lines += ["", "<i>Учёл: " + " · ".join(used) + "</i>"]
    if resp.get("disclaimer"):
        lines.append(f"<i>{escape(resp['disclaimer'])}</i>")
    return "\n".join(lines).strip()

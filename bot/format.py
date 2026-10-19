"""Format an /api/recommend JSON answer as a Telegram HTML message. Pure functions, easy to test.
Ported from Abegerov4's backend/telegram_bot/format.py to the shared API response; labels follow the answer
language (ru / kk / en), each place gets a 2GIS route from the start and a map pin."""
from html import escape

TEXT = {
    "ru": {"why": "Почему", "todo": "Что делать", "min": "мин", "route": "маршрут", "mini": "Мини-маршрут", "used": "Учёл",
           "no_loc": "локация не указана", "radius": "радиус {r} км", "walk": "пешком", "car": "на машине",
           "transit": "на транспорте", "open": "🟢 открыто", "closed": "🔴 закрыто", "unknown": "⚪ часы уточняйте",
           "poi": "📍 данные POI", "idea": "✨ идея ИИ", "photo": "📷 Похоже, это <b>{name}</b>.",
           "btn_route": "🗺 {i}. Маршрут", "btn_pin": "📍 {i}. На карте", "from": "от", "km": "км", "m": "м"},
    "kk": {"why": "Неге", "todo": "Не істеу", "min": "мин", "route": "бағыт", "mini": "Шағын бағыт", "used": "Ескердім",
           "no_loc": "орын көрсетілмеген", "radius": "радиус {r} км", "walk": "жаяу", "car": "көлікпен",
           "transit": "қоғамдық көлікпен", "open": "🟢 ашық", "closed": "🔴 жабық", "unknown": "⚪ уақытын нақтылаңыз",
           "poi": "📍 POI деректері", "idea": "✨ ЖИ идеясы", "photo": "📷 Бұл <b>{name}</b> сияқты.",
           "btn_route": "🗺 {i}. Бағыт", "btn_pin": "📍 {i}. Картада", "from": "бастап", "km": "км", "m": "м"},
    "en": {"why": "Why", "todo": "What to do", "min": "min", "route": "route", "mini": "Mini-route", "used": "Took into account",
           "no_loc": "no location", "radius": "radius {r} km", "walk": "on foot", "car": "by car",
           "transit": "by transit", "open": "🟢 open", "closed": "🔴 closed", "unknown": "⚪ check the hours",
           "poi": "📍 POI data", "idea": "✨ AI idea", "photo": "📷 Looks like <b>{name}</b>.",
           "btn_route": "🗺 {i}. Route", "btn_pin": "📍 {i}. On the map", "from": "from", "km": "km", "m": "m"},
}

# quick scenarios after a location is shared: callback_data -> (button, request) per language
SCENARIOS_I18N = {
    "ru": {"walk": ("🚶 Прогулка на час", "Хочу прогуляться около часа"),
           "coffee": ("☕ Кофе", "Хочу тихое место с кофе рядом"),
           "kids": ("👶 С ребёнком", "Я с ребёнком, где рядом площадка или интерактивный музей?"),
           "night": ("🌙 Вечером", "Ищу необычную вечернюю активность рядом"),
           "sights": ("🏛 Что посмотреть", "Я турист, что интересного посмотреть рядом за пару часов?"),
           "food": ("🍽 Поесть", "Где рядом можно поесть?")},
    "kk": {"walk": ("🚶 Бір сағат серуен", "Бір сағатқа серуендегім келеді"),
           "coffee": ("☕ Кофе", "Жақын жерде тыныш кофехана бар ма?"),
           "kids": ("👶 Баламен", "Баламен бірге жақын жерде қайда баруға болады?"),
           "night": ("🌙 Кешке", "Кешке жақын жерде ерекше не істеуге болады?"),
           "sights": ("🏛 Не көруге болады", "Мен туриспін, жақын жерде екі сағатта не көруге болады?"),
           "food": ("🍽 Тамақтану", "Жақын жерде қайда тамақтануға болады?")},
    "en": {"walk": ("🚶 One-hour walk", "I want a walk for about an hour"),
           "coffee": ("☕ Coffee", "A quiet place with coffee nearby"),
           "kids": ("👶 With a child", "I'm with a child, is there a playground or an interactive museum nearby?"),
           "night": ("🌙 Evening", "Something unusual to do this evening nearby"),
           "sights": ("🏛 What to see", "I'm a tourist, what is worth seeing nearby in a couple of hours?"),
           "food": ("🍽 Eat", "Where can I eat nearby?")},
}
SCENARIOS = SCENARIOS_I18N["ru"]  # backwards compatible name


def _t(lang: str) -> dict:
    return TEXT.get(lang, TEXT["ru"])


def map_link(lat: float, lon: float) -> str:
    return f"https://2gis.kz/astana/geo/{lon}%2C{lat}"


def route_link(lat: float, lon: float, start: dict | None) -> str:
    """2GIS directions from the answer's start (rounded GPS or the landmark) to the place; a pin without a start."""
    if not start or start.get("lat") is None:
        return map_link(lat, lon)
    return f"https://2gis.kz/astana/directions/points/{start['lon']}%2C{start['lat']}%7C{lon}%2C{lat}"


def _distance(m: int, t: dict) -> str:
    return f"{m / 1000:.1f} {t['km']}".replace(".", ",") if m >= 1000 else f"{m} {t['m']}"


def _header(resp: dict, t: dict) -> list[str]:
    lines: list[str] = []
    if g := resp.get("photo_guess"):
        if g.get("recognized") and g.get("name"):
            lines += [t["photo"].format(name=escape(g["name"])), ""]
    if resp.get("recommendations") and (summary := (resp.get("summary") or "").strip()):
        lines += [escape(summary), ""]
    return lines


def _card(i: int, r: dict, t: dict, mode: str, start: dict) -> list[str]:
    meters = r.get("walk_distance_m") or r.get("distance_m")  # along the streets when the walk graph knows it
    dist = f"{_distance(meters, t)}, {r['travel_min']} {t['min']} {mode}" if meters is not None else ""
    visit = r.get("visit_min") or [r.get("visit_suggested_min"), r.get("visit_suggested_min")]
    opening = (r.get("opening") or {}).get("label") or t.get(r.get("open_status") or "unknown", "")
    source = t["idea"] if r.get("source") == "generated" else t["poi"]
    visit_txt = f" (~{visit[0]}–{visit[1]} {t['min']})" if visit and visit[0] else ""
    return [
        f"<b>{i}. {escape(r['name'])}</b>" + (f" ({dist})" if dist else ""),
        f"<i>{t['why']}:</i> {escape(r.get('why') or '')}",
        f"<i>{t['todo']}:</i> {escape(r.get('what_to_do') or '')}{visit_txt}",
        f"{escape(opening)} · {source} · <a href=\"{route_link(r['lat'], r['lon'], start)}\">{t['route']}</a>",
    ]


def _footer(resp: dict, t: dict) -> list[str]:
    ctx, recs, lines = resp.get("used_context") or {}, resp.get("recommendations") or [], []
    if (route := resp.get("route")) and recs:
        names = {r["poi_id"]: r["name"] for r in recs}
        order = " → ".join(escape(names[p]) for p in route.get("order", []) if p in names)
        if order:
            lines += [f"🗺 <b>{t['mini']}:</b> {order} (≈{route.get('total_min')} {t['min']})", ""]
    for n in resp.get("notes") or []:
        lines.append(f"ℹ️ {escape(n)}")
    used = [escape(ctx.get("location_label") or t["no_loc"])]
    if ctx.get("radius_m"):
        used.append(t["radius"].format(r=f"{ctx['radius_m'] / 1000:.1f}"))
    if ctx.get("time_budget_min"):
        used.append(f"{ctx['time_budget_min']} {t['min']}")
    if (w := ctx.get("weather")) and w.get("temperature_c") is not None:
        used.append(f"{round(w['temperature_c'])}°C" + (f", AQI {round(w['us_aqi'])}" if (w.get("us_aqi") or 0) >= 101 else ""))
    lines += ["", f"<i>{t['used']}: " + " · ".join(used) + "</i>"]
    if resp.get("disclaimer"):
        lines.append(f"<i>{escape(resp['disclaimer'])}</i>")
    return lines


def format_response(resp: dict) -> str:
    """The whole answer as one message (fallback and tests)."""
    ctx = resp.get("used_context") or {}
    t = _t(resp.get("lang") or "ru")
    start, mode = ctx.get("location") or {}, t.get(ctx.get("mode") or "walk", ctx.get("mode") or "")
    lines = _header(resp, t)
    for i, r in enumerate(resp.get("recommendations") or [], 1):
        lines += _card(i, r, t, mode, start) + [""]
    return "\n".join(lines + _footer(resp, t)).strip()


def answer_parts(resp: dict) -> dict:
    """The answer as Telegram cards: a header, one card per place (photo + caption + buttons), a footer."""
    ctx = resp.get("used_context") or {}
    t = _t(resp.get("lang") or "ru")
    start, mode = ctx.get("location") or {}, t.get(ctx.get("mode") or "walk", ctx.get("mode") or "")
    buttons = {row[0]["url"]: row for row in place_buttons(resp)}
    cards = []
    for i, r in enumerate(resp.get("recommendations") or [], 1):
        photo = (r.get("photo") or {}).get("url")
        caption = "\n".join(_card(i, r, t, mode, start))
        if photo and (r.get("photo") or {}).get("author"):
            credit = r["photo"]["author"] if r["photo"].get("source") == "website" else f"{r['photo']['author']}, {r['photo'].get('license', '')}"
            caption += f"\n<i>📷 {escape(credit[:80])}</i>"
        cards.append({"photo": photo, "caption": caption[:1024],
                      "buttons": buttons.get(route_link(r["lat"], r["lon"], start), []) if r.get("lat") is not None else []})
    return {"header": "\n".join(_header(resp, t)).strip(), "cards": cards, "footer": "\n".join(_footer(resp, t)).strip()}


def place_buttons(resp: dict) -> list[list[dict]]:
    """Rows of buttons under the answer: a 2GIS route from the start and a pin in Telegram for every place.
    Plain dicts (text + url | callback) so the formatting stays testable without the Telegram library."""
    t = _t(resp.get("lang") or "ru")
    start = (resp.get("used_context") or {}).get("location") or {}
    rows = []
    for i, r in enumerate(resp.get("recommendations") or [], 1):
        if r.get("lat") is None or r.get("source") == "generated":
            continue
        rows.append([{"text": t["btn_route"].format(i=i), "url": route_link(r["lat"], r["lon"], start)},
                     {"text": t["btn_pin"].format(i=i), "callback": f"pin:{i - 1}"}])
    return rows


def pins(resp: dict) -> list[dict]:
    """What a pin button sends back as a Telegram venue (kept in chat memory, no coordinates of the user)."""
    return [{"name": r["name"], "lat": r["lat"], "lon": r["lon"], "address": r.get("address") or r.get("category_label") or ""}
            for r in resp.get("recommendations") or [] if r.get("lat") is not None and r.get("source") != "generated"]

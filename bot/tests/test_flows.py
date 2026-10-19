"""Bot flows without Telegram or the network: routes need a start, /home saves an address, a route idea comes back
as place cards."""
import asyncio
import time
from types import SimpleNamespace

import bot.telegram_bot as tb


class Msg:
    def __init__(self, text=""):
        self.text, self.sent = text, []

    async def reply_text(self, text, **kw):
        self.sent.append(("text", text, kw.get("reply_markup")))

    async def reply_photo(self, photo, caption, **kw):
        self.sent.append(("photo", caption, kw.get("reply_markup")))


class Resp:
    def __init__(self, status, data):
        self.status_code, self._data = status, data

    def json(self):
        return self._data

    def raise_for_status(self):
        assert self.status_code < 400


class FakeHttp:
    def __init__(self, routes):
        self.routes, self.calls = routes, []

    async def _do(self, method, url, **kw):
        self.calls.append((method, url.split("/api/")[1], kw.get("json") or kw.get("params")))
        return self.routes[(method, url.split("/api/")[1])]

    async def get(self, url, **kw):
        return await self._do("GET", url, **kw)

    async def put(self, url, **kw):
        return await self._do("PUT", url, **kw)

    async def post(self, url, **kw):
        return await self._do("POST", url, **kw)

    async def delete(self, url, **kw):
        return await self._do("DELETE", url, **kw)


def update(text=""):
    msg = Msg(text)

    async def action(*_):
        return None
    return SimpleNamespace(message=msg, effective_message=msg, callback_query=None,
                           effective_user=SimpleNamespace(id=1, language_code="ru"), effective_chat=SimpleNamespace(send_action=action))


def ctx(**data):
    return SimpleNamespace(chat_data=dict(data))


IDEA = {"key": "green", "emoji": "🌳", "title": "Зелёная прогулка", "total_min": 80, "stops": ["Сквер", "Бульвар"], "query": "q",
        "response": {"lang": "ru", "summary": "Мини-маршрут", "recommendations": [
            {"poi_id": "a", "name": "Сквер", "lat": 51.1, "lon": 71.4, "travel_min": 5, "distance_m": 300, "why": "w", "what_to_do": "d",
             "visit_min": [10, 20], "source": "poi_data", "photo": {"url": "https://x/y.jpg", "author": "A", "license": "CC BY"}}],
            "route": {"order": ["a"], "total_min": 80}, "used_context": {"location": {"lat": 51.1, "lon": 71.4}}, "notes": []}}


def test_routes_without_a_start_ask_for_a_location_or_home(monkeypatch):
    monkeypatch.setattr(tb, "_http", FakeHttp({("GET", "bot/home"): Resp(200, {"home": None})}))
    u = update("🗺 Маршруты")
    asyncio.run(tb.on_text(u, ctx()))
    assert "геолокацию" in u.message.sent[0][1]


def test_routes_list_then_a_chosen_route_comes_as_cards(monkeypatch):
    http = FakeHttp({("POST", "routes/ideas"): Resp(200, {"ideas": [IDEA]})})
    monkeypatch.setattr(tb, "_http", http)
    c = ctx(loc={"lat": 51.1, "lon": 71.4, "ts": time.monotonic()})
    u = update("🗺 Маршруты")
    asyncio.run(tb.on_text(u, c))
    assert "Зелёная прогулка" in u.message.sent[0][1] and http.calls[0][2]["location"] == {"lat": 51.1, "lon": 71.4}
    answered = []

    async def ans(*_):
        answered.append(1)
    q = SimpleNamespace(data="route:0", answer=ans, message=u.message)
    u2 = update()
    u2.callback_query = q
    asyncio.run(tb.on_route(u2, c))
    kinds = [k for k, *_ in u2.effective_message.sent]
    assert answered and "photo" in kinds  # the place card with its photo


def test_home_is_saved_from_an_address(monkeypatch):
    http = FakeHttp({("GET", "geocode"): Resp(200, {"results": [{"lat": 51.16, "lon": 71.47, "label": "Кенесары 40"}]}),
                     ("PUT", "bot/home"): Resp(200, {"home": {"lat": 51.16, "lon": 71.47, "label": "Кенесары 40"}})})
    monkeypatch.setattr(tb, "_http", http)
    c = ctx(await_home=True)
    u = update("Кенесары 40")
    asyncio.run(tb.on_text(u, c))
    assert c.chat_data["home"]["lat"] == 51.16 and "Дом сохранён" in u.message.sent[0][1] and "await_home" not in c.chat_data

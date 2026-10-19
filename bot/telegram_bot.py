"""Telegram bot for SeruendeshAI: location / text / photo -> 1–3 places nearby.

A thin client of the public API (same answers as the website and the MCP connector), so it needs
no data, model or database of its own. Ported from Abegerov4's backend/telegram_bot.
Privacy: the location is rounded to ~100 m, kept only in this process for 30 minutes, /forget wipes it;
photos are forwarded to /api/recommend/photo, which strips EXIF and stores nothing. Logs carry no chat ids,
coordinates or message text.

Run:  TELEGRAM_BOT_TOKEN=... SERU_API=https://seruendesh.site python -m bot.telegram_bot
"""
import asyncio
import hashlib
import logging
import os
import re
import time

import httpx
from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup, Update
from telegram.constants import ChatAction, ParseMode
from telegram.error import TelegramError
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

from bot.format import SCENARIOS_I18N, answer_parts, format_response, pins, place_buttons

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("seru.telegram")

API = os.getenv("SERU_API", "https://seruendesh.site").rstrip("/")
BOT_KEY = os.getenv("SERU_BOT_KEY", "").strip()  # = BOT_API_KEY of the backend: per-user rate limits
LOCATION_TTL_S = 30 * 60
UI = {
    "ru": {"home_btn": "🏠 От дома", "routes_btn": "🗺 Маршруты",
           "home_ask": "Где ваш дом? Отправьте геолокацию (📎 → Геопозиция) или напишите адрес, например «Кенесары 40».",
           "home_saved": "🏠 Дом сохранён: {label} (округлил до ~100 м). Теперь можно писать «что интересного рядом с домом» или нажать «🏠 От дома».",
           "home_not_found": "Не нашёл такой адрес в Астане. Напишите «улица, дом» или отправьте геолокацию.",
           "home_none": "Дом ещё не сохранён — отправьте /home.", "home_off": "Сохранение дома сейчас недоступно.",
           "from_home": "Строю от дома 🏠. Что хочется?", "need_place": "Сначала отправьте геолокацию или сохраните дом (/home) — маршруты строю от вас.",
           "routes_title": "🗺 Готовые маршруты от вас — выберите:", "routes_none": "Рядом не получилось собрать маршрут из 2–3 мест. Попробуйте другую точку.",
           "location_button": "📍 Отправить геолокацию",
           "welcome": "Привет! Я Серу и подскажу, куда сходить в Астане рядом с вами.\n\n"
                      "• Отправьте <b>геолокацию</b> и выберите, что хочется;\n"
                      "• или напишите, например: <i>«я возле Байтерека, хочу кофе и посидеть с ноутбуком»</i> или "
                      "<i>«маршрут от Хан Шатыра до Байтерека»</i>;\n"
                      "• или пришлите <b>фото</b> того, что видите, и я узнаю место.\n\n"
                      "💻 На компьютере кнопка геолокации не работает — просто напишите, где вы.\n\n"
                      "🔒 Локацию округляю до ~100 м, держу в памяти 30 минут и никуда не сохраняю. /forget стирает её сразу.",
           "busy": "Сейчас слишком много запросов. Попробуйте через минуту.",
           "got_location": "Локацию получил (округлил до ~100 м). Что хочется? Нажмите кнопку или напишите своими словами.",
           "stale": "Локация устарела. Отправьте её ещё раз 👇", "forgot": "Готово, локацию забыл.",
           "photo_off": "Распознавание по фото сейчас недоступно. Напишите, где вы.",
           "voice": "Не разобрал голосовое 🙏 Напишите текстом или отправьте геолокацию.",
           "error": "Что-то пошло не так, попробуйте ещё раз через минуту.", "pin_gone": "Это старый ответ — спросите ещё раз."},
    "kk": {"home_btn": "🏠 Үйден", "routes_btn": "🗺 Бағыттар",
           "home_ask": "Үйіңіз қайда? Геолокацияны жіберіңіз (📎 → Геопозиция) немесе мекенжайды жазыңыз, мысалы «Кенесары 40».",
           "home_saved": "🏠 Үй сақталды: {label} (~100 м-ге дөңгелектедім). Енді «үйдің жанында не бар» деп жазуға немесе «🏠 Үйден» басуға болады.",
           "home_not_found": "Астанада мұндай мекенжай табылмады. «көше, үй» деп жазыңыз немесе геолокация жіберіңіз.",
           "home_none": "Үй әлі сақталмаған — /home жіберіңіз.", "home_off": "Үйді сақтау қазір қолжетімсіз.",
           "from_home": "Үйден бастаймын 🏠. Не қалайсыз?", "need_place": "Алдымен геолокация жіберіңіз немесе үйді сақтаңыз (/home).",
           "routes_title": "🗺 Сізден басталатын дайын бағыттар — таңдаңыз:", "routes_none": "Жақын жерде 2–3 орыннан бағыт құрастыру мүмкін болмады.",
           "location_button": "📍 Геолокацияны жіберу",
           "welcome": "Сәлем! Мен Серумін — Астанада жақын жерде қайда баруға болатынын айтамын.\n\n"
                      "• <b>Геолокацияны</b> жіберіп, не қалайтыныңызды таңдаңыз;\n"
                      "• немесе жазыңыз: <i>«Бәйтеректің жанындамын, кофе ішкім келеді»</i>;\n"
                      "• немесе көріп тұрған жеріңіздің <b>фотосын</b> жіберіңіз.\n\n"
                      "💻 Компьютерде геолокация батырмасы жұмыс істемейді — қайда екеніңізді жазыңыз.\n\n"
                      "🔒 Орынды ~100 м-ге дейін дөңгелектеп, 30 минут жадта сақтаймын. /forget бірден өшіреді.",
           "busy": "Қазір сұрау көп. Бір минуттан кейін қайталаңыз.",
           "got_location": "Орынды алдым (~100 м-ге дөңгелектедім). Не қалайсыз? Батырманы басыңыз немесе өз сөзіңізбен жазыңыз.",
           "stale": "Орын ескірді. Қайта жіберіңіз 👇", "forgot": "Дайын, орынды ұмыттым.",
           "photo_off": "Фото бойынша тану қазір қолжетімсіз. Қайда екеніңізді жазыңыз.",
           "voice": "Дауыстық хабарламаны түсінбедім 🙏 Мәтінмен жазыңыз немесе геолокация жіберіңіз.",
           "error": "Бірдеңе дұрыс болмады, бір минуттан кейін қайталаңыз.", "pin_gone": "Бұл ескі жауап — қайта сұраңыз."},
    "en": {"home_btn": "🏠 From home", "routes_btn": "🗺 Routes",
           "home_ask": "Where is your home? Send its location (📎 → Location) or write the address, e.g. “Kenesary 40”.",
           "home_saved": "🏠 Home saved: {label} (rounded to ~100 m). Now ask “what's interesting near home” or tap “🏠 From home”.",
           "home_not_found": "Couldn't find that address in Astana. Write “street, number” or send the location.",
           "home_none": "No home saved yet — send /home.", "home_off": "Saving a home is unavailable right now.",
           "from_home": "Starting from home 🏠. What do you feel like?", "need_place": "First send your location or save your home (/home) — routes start from you.",
           "routes_title": "🗺 Ready-made walks from you — pick one:", "routes_none": "Couldn't build a 2–3 stop route nearby. Try another place.",
           "location_button": "📍 Send my location",
           "welcome": "Hi! I'm Seru and I'll suggest where to go in Astana near you.\n\n"
                      "• Send your <b>location</b> and pick what you feel like;\n"
                      "• or write, e.g. <i>“I'm near Baiterek, I want coffee and a quiet table”</i> or "
                      "<i>“route from Khan Shatyr to Baiterek”</i>;\n"
                      "• or send a <b>photo</b> of what you see and I'll recognise the place.\n\n"
                      "💻 The location button does not work on desktop — just write where you are.\n\n"
                      "🔒 Your location is rounded to ~100 m, kept in memory for 30 minutes and never stored. /forget wipes it.",
           "busy": "Too many requests right now. Please try again in a minute.",
           "got_location": "Got your location (rounded to ~100 m). What do you feel like? Tap a button or write in your own words.",
           "stale": "Your location is out of date. Please send it again 👇", "forgot": "Done, I forgot your location.",
           "photo_off": "Photo recognition is unavailable right now. Please write where you are.",
           "voice": "I couldn't make out that voice message 🙏 Please write or send your location.",
           "error": "Something went wrong, please try again in a minute.", "pin_gone": "That answer is old — please ask again."},
}
LOCATION_BUTTON = UI["ru"]["location_button"]
WELCOME = UI["ru"]["welcome"]
BUSY = UI["ru"]["busy"]
COMMANDS = [BotCommand("start", "Начать и отправить геолокацию"), BotCommand("routes", "Интересные маршруты рядом"),
            BotCommand("home", "Сохранить адрес дома"), BotCommand("help", "Что я умею"),
            BotCommand("forget", "Забыть мою локацию и дом")]
HOME_WORDS = re.compile(r"(?:\bот|\bиз|\bу|\bоколо|\bвозле|рядом с|недалеко от)\s+(?:моего\s+|своего\s+)?дом(?:а|ом)(?![а-я])|у меня дома|"
                        r"(?:near|from|around)\s+(?:my\s+)?home|үйден|үйдің жанында", re.I)
_http = httpx.AsyncClient(timeout=40)


def _ui(lang: str) -> dict:
    return UI.get(lang, UI["ru"])


def _keyboard(lang: str = "ru") -> ReplyKeyboardMarkup:
    ui = _ui(lang)
    return ReplyKeyboardMarkup([[KeyboardButton(ui["location_button"], request_location=True)],
                                [KeyboardButton(ui["home_btn"]), KeyboardButton(ui["routes_btn"])]], resize_keyboard=True)


async def _home(update: Update, context: ContextTypes.DEFAULT_TYPE) -> dict | None:
    """The saved home: chat memory first, then the API (it survives restarts)."""
    if "home" in context.chat_data:
        return context.chat_data["home"]
    r = await _http.get(f"{API}/api/bot/home", headers=_headers(update))
    home = r.json().get("home") if r.status_code == 200 else None
    context.chat_data["home"] = home
    return home


async def _save_home(update: Update, context: ContextTypes.DEFAULT_TYPE, lat: float, lon: float, label: str) -> None:
    lang = _ui_lang(update)
    r = await _http.put(f"{API}/api/bot/home", json={"lat": lat, "lon": lon, "label": label[:120]}, headers=_headers(update))
    context.chat_data.pop("await_home", None)
    if r.status_code != 200:
        await update.effective_message.reply_text(_ui(lang)["home_off" if r.status_code == 403 else "home_not_found"])
        return
    context.chat_data["home"] = r.json()["home"]
    await update.effective_message.reply_text(_ui(lang)["home_saved"].format(label=label), reply_markup=_keyboard(lang))


def _start_point(context: ContextTypes.DEFAULT_TYPE) -> dict | None:
    return _saved_location(context) or (context.chat_data.get("home") and {k: context.chat_data["home"][k] for k in ("lat", "lon")})


def _scenario_buttons(lang: str = "ru") -> InlineKeyboardMarkup:
    items = list(SCENARIOS_I18N.get(lang, SCENARIOS_I18N["ru"]).items())
    return InlineKeyboardMarkup([[InlineKeyboardButton(label, callback_data=f"sc:{lang}:{key}") for key, (label, _) in items[i:i + 2]]
                                 for i in range(0, len(items), 2)])


def _answer_buttons(resp: dict) -> InlineKeyboardMarkup | None:
    rows = [[InlineKeyboardButton(b["text"], url=b["url"]) if "url" in b else InlineKeyboardButton(b["text"], callback_data=b["callback"])
             for b in row] for row in place_buttons(resp)]
    return InlineKeyboardMarkup(rows) if rows else None


def _ui_lang(update: Update) -> str:
    code = (update.effective_user.language_code or "") if update.effective_user else ""
    return code if code in ("kk", "en") else "ru"


def detect_lang(text: str, ui_code: str = "") -> str:
    """Answer in the language of the message; the Telegram UI language is only a fallback (an English phone
    UI must not turn a Russian question into an English answer)."""
    if re.search(r"[әғқңөұүһі]", text, re.IGNORECASE):
        return "kk"
    if re.search(r"[а-яё]", text, re.IGNORECASE):
        return "ru"
    return ui_code if ui_code in {"kk", "en"} and text.strip() else "ru"


def _lang(update: Update, text: str = "") -> str:
    code = (update.effective_user.language_code or "") if update.effective_user else ""
    return detect_lang(text, code)


def api_headers(user_id: int | None, bot_key: str = BOT_KEY) -> dict[str, str]:
    """With the shared key the API limits every Telegram user separately; the id leaves only as a salted hash."""
    if not bot_key or user_id is None:
        return {}
    return {"X-Seru-Bot-Key": bot_key, "X-Seru-User": hashlib.sha256(f"{bot_key}:{user_id}".encode()).hexdigest()[:32]}


def _headers(update: Update) -> dict[str, str]:
    return api_headers(update.effective_user.id if update.effective_user else None)


def _saved_location(context: ContextTypes.DEFAULT_TYPE) -> dict | None:
    saved = context.chat_data.get("loc")
    if not saved or time.monotonic() - saved["ts"] > LOCATION_TTL_S:
        context.chat_data.pop("loc", None)
        return None
    return {"lat": saved["lat"], "lon": saved["lon"]}


async def _reply(update: Update, text: str, markup: InlineKeyboardMarkup | None = None) -> None:
    chunks = [text[i:i + 4000] for i in range(0, len(text), 4000)] or [""]
    for n, chunk in enumerate(chunks):
        await update.effective_message.reply_text(chunk, parse_mode=ParseMode.HTML, disable_web_page_preview=True,
                                                  reply_markup=markup if n == len(chunks) - 1 else None)


def _markup(row: list[dict]) -> InlineKeyboardMarkup | None:
    if not row:
        return None
    return InlineKeyboardMarkup([[InlineKeyboardButton(b["text"], url=b["url"]) if "url" in b
                                  else InlineKeyboardButton(b["text"], callback_data=b["callback"]) for b in row]])


async def _answer(update: Update, context: ContextTypes.DEFAULT_TYPE, resp: dict) -> None:
    """Every place as its own card: the place's photo (when we have one) with a caption and its own buttons."""
    context.chat_data["pins"] = pins(resp)  # what the «📍 On the map» buttons send back
    parts = answer_parts(resp)
    if not parts["cards"]:
        await _reply(update, format_response(resp))
        return
    msg = update.effective_message
    if parts["header"]:
        await msg.reply_text(parts["header"], parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    for card in parts["cards"]:
        markup = _markup(card["buttons"])
        if card["photo"]:
            try:
                await msg.reply_photo(photo=card["photo"], caption=card["caption"], parse_mode=ParseMode.HTML, reply_markup=markup)
                continue
            except TelegramError as exc:  # the image host refused Telegram: the same card as text
                log.info("photo card fell back to text: %s", type(exc).__name__)
        await msg.reply_text(card["caption"], parse_mode=ParseMode.HTML, disable_web_page_preview=True, reply_markup=markup)
    if parts["footer"]:
        await _reply(update, parts["footer"])


async def _run(update: Update, context: ContextTypes.DEFAULT_TYPE, query: str) -> None:
    await update.effective_chat.send_action(ChatAction.TYPING)
    lang = _lang(update, query)
    body = {"query": query[:1000], "lang": lang, "channel": "telegram"}
    if loc := _saved_location(context):
        body["location"] = loc
    if HOME_WORDS.search(query) and (home := await _home(update, context)):
        body["home"] = home  # «от дома»: the API starts from it
    r = await _http.post(f"{API}/api/recommend", json=body, headers=_headers(update))
    if r.status_code == 429:
        await update.effective_message.reply_text(_ui(lang)["busy"])
        return
    r.raise_for_status()
    resp = r.json()
    log.info("telegram recs=%d mode=%s", len(resp.get("recommendations", [])), (resp.get("llm") or {}).get("mode"))
    await _answer(update, context, resp)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = _ui_lang(update)
    await update.message.reply_text(_ui(lang)["welcome"], parse_mode=ParseMode.HTML, reply_markup=_keyboard(lang))


async def forget(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.chat_data.clear()
    await _http.delete(f"{API}/api/bot/home", headers=_headers(update))
    await update.message.reply_text(_ui(_ui_lang(update))["forgot"])


async def home_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.chat_data["await_home"] = True
    await update.message.reply_text(_ui(_ui_lang(update))["home_ask"])


async def from_home(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = _ui_lang(update)
    home = await _home(update, context)
    if not home:
        context.chat_data["await_home"] = True
        await update.message.reply_text(_ui(lang)["home_ask"])
        return
    ts = time.monotonic()  # the home becomes the start for the next 30 minutes, like a shared location
    context.chat_data["loc"] = {"lat": home["lat"], "lon": home["lon"], "ts": ts}
    await update.message.reply_text(_ui(lang)["from_home"], reply_markup=_scenario_buttons(lang))


async def routes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Themed walks from the user's place, each a real route; the chosen one comes back as cards."""
    lang = _ui_lang(update)
    start = _start_point(context) or ((h := await _home(update, context)) and {"lat": h["lat"], "lon": h["lon"]})
    if not start:
        await update.effective_message.reply_text(_ui(lang)["need_place"], reply_markup=_keyboard(lang))
        return
    await update.effective_chat.send_action(ChatAction.TYPING)
    r = await _http.post(f"{API}/api/routes/ideas", json={"lang": lang, "location": start}, headers=_headers(update))
    if r.status_code == 429:
        await update.effective_message.reply_text(_ui(lang)["busy"])
        return
    r.raise_for_status()
    ideas = r.json().get("ideas") or []
    context.chat_data["ideas"] = ideas
    if not ideas:
        await update.effective_message.reply_text(_ui(lang)["routes_none"])
        return
    lines = [_ui(lang)["routes_title"], ""]
    for n, i in enumerate(ideas, 1):
        lines.append(f"{n}. {i['emoji']} <b>{i['title']}</b> · ≈{i['total_min']} мин\n   {' → '.join(i['stops'])}")
    buttons = [[InlineKeyboardButton(f"{n}. {i['emoji']} {i['title']}", callback_data=f"route:{n - 1}")] for n, i in enumerate(ideas, 1)]
    await update.effective_message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(buttons))


async def on_route(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    try:
        idea = (context.chat_data.get("ideas") or [])[int((q.data or "").removeprefix("route:"))]
    except (ValueError, IndexError):
        await q.message.reply_text(_ui(_ui_lang(update))["pin_gone"])
        return
    await _answer(update, context, idea["response"])


async def on_location(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    loc = update.message.location
    if context.chat_data.get("await_home"):
        label = {"kk": "геолокация бойынша", "en": "from location"}.get(_ui_lang(update), "по геолокации")
        await _save_home(update, context, round(loc.latitude, 3), round(loc.longitude, 3), label)
        return
    ts = time.monotonic()
    context.chat_data["loc"] = {"lat": round(loc.latitude, 3), "lon": round(loc.longitude, 3), "ts": ts}

    async def expire(chat_data=context.chat_data):  # wipe on time even if the user never writes again
        await asyncio.sleep(LOCATION_TTL_S)
        if (chat_data.get("loc") or {}).get("ts") == ts:
            chat_data.pop("loc", None)
    context.application.create_task(expire())
    lang = _ui_lang(update)
    await update.message.reply_text(_ui(lang)["got_location"], reply_markup=_scenario_buttons(lang))


async def on_scenario(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    parts = (q.data or "").split(":")  # sc:<lang>:<key> (older buttons: sc:<key>)
    lang, key = (parts[1], parts[2]) if len(parts) == 3 else ("ru", parts[-1])
    scenarios = SCENARIOS_I18N.get(lang, SCENARIOS_I18N["ru"])
    if key not in scenarios:
        return
    if _saved_location(context) is None:
        await q.message.reply_text(_ui(lang)["stale"], reply_markup=_keyboard(lang))
        return
    await _run(update, context, scenarios[key][1])


async def on_pin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """«📍 On the map»: the place as a Telegram venue — opens in the phone's maps app."""
    q = update.callback_query
    await q.answer()
    saved = context.chat_data.get("pins") or []
    try:
        place = saved[int((q.data or "").removeprefix("pin:"))]
    except (ValueError, IndexError):
        await q.message.reply_text(_ui(_ui_lang(update))["pin_gone"])
        return
    await q.message.reply_venue(latitude=place["lat"], longitude=place["lon"], title=place["name"][:64],
                                address=(place["address"] or place["name"])[:128])


async def on_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """A voice message, audio or round video: the API turns it into text, then it is answered like a typed message."""
    msg, lang = update.message, _ui_lang(update)
    media = msg.voice or msg.audio or msg.video_note
    if media is None or (media.file_size or 0) > 4_000_000:
        await msg.reply_text(_ui(lang)["voice"])
        return
    await update.effective_chat.send_action(ChatAction.TYPING)
    data = bytes(await (await media.get_file()).download_as_bytearray())
    name, kind = (("voice.ogg", "audio/ogg") if msg.voice else ("note.mp4", "video/mp4") if msg.video_note
                  else (getattr(media, "file_name", None) or "audio.mp3", media.mime_type or "audio/mpeg"))
    r = await _http.post(f"{API}/api/bot/transcribe", files={"audio": (name, data, kind)}, headers=_headers(update))
    text = (r.json().get("text") or "").strip() if r.status_code == 200 else ""
    if r.status_code == 429:
        await msg.reply_text(_ui(lang)["busy"])
        return
    if not text:
        await msg.reply_text(_ui(lang)["voice"])
        return
    await msg.reply_text(f"🎙 «{text}»")
    await _run(update, context, text)


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (update.message.text or "").strip()
    if text in {ui["home_btn"] for ui in UI.values()}:
        await from_home(update, context)
        return
    if text in {ui["routes_btn"] for ui in UI.values()}:
        await routes(update, context)
        return
    if context.chat_data.get("await_home"):  # the address of the home, e.g. «Кенесары 40»
        r = await _http.get(f"{API}/api/geocode", params={"q": text[:120]}, headers=_headers(update))
        found = (r.json().get("results") or []) if r.status_code == 200 else []
        if not found:
            await update.message.reply_text(_ui(_ui_lang(update))["home_not_found"])
            return
        await _save_home(update, context, found[0]["lat"], found[0]["lon"], text[:120])
        return
    await _run(update, context, text)


async def on_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_chat.send_action(ChatAction.TYPING)
    data = bytes(await (await update.message.photo[-1].get_file()).download_as_bytearray())
    form = {"lang": _lang(update, update.message.caption or ""), "channel": "telegram"}
    if update.message.caption:
        form["query"] = update.message.caption[:1000]
    r = await _http.post(f"{API}/api/recommend/photo", data=form, files={"image": ("photo.jpg", data, "image/jpeg")},
                         headers=_headers(update))
    lang = form["lang"]
    if r.status_code == 429:
        await update.message.reply_text(_ui(lang)["busy"])
        return
    if r.status_code == 503:
        await update.message.reply_text(_ui(lang)["photo_off"])
        return
    r.raise_for_status()
    await _answer(update, context, r.json())


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.error("telegram handler failed: %s", type(context.error).__name__)
    if isinstance(update, Update) and update.effective_message:
        await update.effective_message.reply_text(_ui(_ui_lang(update))["error"])


async def _set_commands(app: Application) -> None:
    await app.bot.set_my_commands(COMMANDS)  # the "/" menu in every Telegram client


def build_app(token: str, webhook: bool = False) -> Application:
    """Polling for `make bot`; with webhook=True the web service feeds updates in (backend/app/telegram.py)."""
    builder = Application.builder().token(token).post_init(_set_commands)
    if webhook:
        builder = builder.updater(None)
    app = builder.build()
    app.add_handler(CommandHandler(["start", "help"], start))
    app.add_handler(CommandHandler("forget", forget))
    app.add_handler(CommandHandler("home", home_cmd))
    app.add_handler(CommandHandler("routes", routes))
    app.add_handler(CallbackQueryHandler(on_route, pattern=r"^route:"))
    app.add_handler(MessageHandler(filters.LOCATION, on_location))
    app.add_handler(MessageHandler(filters.PHOTO, on_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO | filters.VIDEO_NOTE, on_voice))
    app.add_handler(CallbackQueryHandler(on_scenario, pattern=r"^sc:"))
    app.add_handler(CallbackQueryHandler(on_pin, pattern=r"^pin:"))
    app.add_error_handler(on_error)
    return app


def main() -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise SystemExit("Нужен TELEGRAM_BOT_TOKEN")
    build_app(token.strip()).run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()

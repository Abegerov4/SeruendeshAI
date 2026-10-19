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
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

from bot.format import SCENARIOS_I18N, format_response, pins, place_buttons

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("seru.telegram")

API = os.getenv("SERU_API", "https://seruendesh.site").rstrip("/")
BOT_KEY = os.getenv("SERU_BOT_KEY", "").strip()  # = BOT_API_KEY of the backend: per-user rate limits
LOCATION_TTL_S = 30 * 60
UI = {
    "ru": {"location_button": "📍 Отправить геолокацию",
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
           "voice": "Голосовые пока не разбираю 🙏 Напишите текстом или отправьте геолокацию.",
           "error": "Что-то пошло не так, попробуйте ещё раз через минуту.", "pin_gone": "Это старый ответ — спросите ещё раз."},
    "kk": {"location_button": "📍 Геолокацияны жіберу",
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
           "voice": "Дауыстық хабарламаларды әзірге түсінбеймін 🙏 Мәтінмен жазыңыз немесе геолокация жіберіңіз.",
           "error": "Бірдеңе дұрыс болмады, бір минуттан кейін қайталаңыз.", "pin_gone": "Бұл ескі жауап — қайта сұраңыз."},
    "en": {"location_button": "📍 Send my location",
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
           "voice": "I can't read voice messages yet 🙏 Please write or send your location.",
           "error": "Something went wrong, please try again in a minute.", "pin_gone": "That answer is old — please ask again."},
}
LOCATION_BUTTON = UI["ru"]["location_button"]
WELCOME = UI["ru"]["welcome"]
BUSY = UI["ru"]["busy"]
COMMANDS = [BotCommand("start", "Начать и отправить геолокацию"), BotCommand("help", "Что я умею"),
            BotCommand("forget", "Забыть мою локацию")]
_http = httpx.AsyncClient(timeout=40)


def _ui(lang: str) -> dict:
    return UI.get(lang, UI["ru"])


def _keyboard(lang: str = "ru") -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup([[KeyboardButton(_ui(lang)["location_button"], request_location=True)]], resize_keyboard=True)


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


async def _answer(update: Update, context: ContextTypes.DEFAULT_TYPE, resp: dict) -> None:
    context.chat_data["pins"] = pins(resp)  # what the «📍 On the map» buttons send back
    await _reply(update, format_response(resp), _answer_buttons(resp))


async def _run(update: Update, context: ContextTypes.DEFAULT_TYPE, query: str) -> None:
    await update.effective_chat.send_action(ChatAction.TYPING)
    lang = _lang(update, query)
    body = {"query": query[:1000], "lang": lang, "channel": "telegram"}
    if loc := _saved_location(context):
        body["location"] = loc
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
    await update.message.reply_text(_ui(_ui_lang(update))["forgot"])


async def on_location(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    loc = update.message.location
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
    await update.message.reply_text(_ui(_ui_lang(update))["voice"])


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _run(update, context, update.message.text)


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

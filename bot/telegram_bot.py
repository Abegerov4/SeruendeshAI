"""Telegram bot for SeruendeshAI: location / text / photo -> 1–3 places nearby.

A thin client of the public API (same answers as the website and the MCP connector), so it needs
no data, model or database of its own. Ported from Abegerov4's backend/telegram_bot.
Privacy: the location is rounded to ~100 m, kept only in this process for 30 minutes, /forget wipes it;
photos are forwarded to /api/recommend/photo, which strips EXIF and stores nothing. Logs carry no chat ids,
coordinates or message text.

Run:  TELEGRAM_BOT_TOKEN=... SERU_API=https://seruendesh.site python -m bot.telegram_bot
"""
import asyncio
import logging
import os
import re
import time

import httpx
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup, Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

from bot.format import SCENARIOS, format_response

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("seru.telegram")

API = os.getenv("SERU_API", "https://seruendesh.site").rstrip("/")
LOCATION_TTL_S = 30 * 60
LOCATION_BUTTON = "📍 Отправить геолокацию"
WELCOME = (
    "Привет! Я Серу и подскажу, куда сходить в Астане рядом с вами.\n\n"
    "• Отправьте <b>геолокацию</b> и выберите, что хочется;\n"
    "• или напишите, например: <i>«я возле Байтерека, хочу кофе и посидеть с ноутбуком»</i>;\n"
    "• или пришлите <b>фото</b> того, что видите, и я узнаю место.\n\n"
    "🔒 Локацию округляю до ~100 м, держу в памяти 30 минут и никуда не сохраняю. /forget стирает её сразу."
)
_http = httpx.AsyncClient(timeout=40)


def _keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup([[KeyboardButton(LOCATION_BUTTON, request_location=True)]], resize_keyboard=True)


def _scenario_buttons() -> InlineKeyboardMarkup:
    items = list(SCENARIOS.items())
    return InlineKeyboardMarkup([[InlineKeyboardButton(label, callback_data=f"sc:{key}") for key, (label, _) in items[i:i + 2]]
                                 for i in range(0, len(items), 2)])


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


def _saved_location(context: ContextTypes.DEFAULT_TYPE) -> dict | None:
    saved = context.chat_data.get("loc")
    if not saved or time.monotonic() - saved["ts"] > LOCATION_TTL_S:
        context.chat_data.pop("loc", None)
        return None
    return {"lat": saved["lat"], "lon": saved["lon"]}


async def _reply(update: Update, text: str) -> None:
    for chunk in [text[i:i + 4000] for i in range(0, len(text), 4000)]:
        await update.effective_message.reply_text(chunk, parse_mode=ParseMode.HTML, disable_web_page_preview=True)


async def _run(update: Update, context: ContextTypes.DEFAULT_TYPE, query: str) -> None:
    await update.effective_chat.send_action(ChatAction.TYPING)
    body = {"query": query[:1000], "lang": _lang(update, query), "channel": "telegram"}
    if loc := _saved_location(context):
        body["location"] = loc
    r = await _http.post(f"{API}/api/recommend", json=body)
    r.raise_for_status()
    resp = r.json()
    log.info("telegram recs=%d mode=%s", len(resp.get("recommendations", [])), (resp.get("llm") or {}).get("mode"))
    await _reply(update, format_response(resp))


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(WELCOME, parse_mode=ParseMode.HTML, reply_markup=_keyboard())


async def forget(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.chat_data.clear()
    await update.message.reply_text("Готово, локацию забыл.")


async def on_location(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    loc = update.message.location
    ts = time.monotonic()
    context.chat_data["loc"] = {"lat": round(loc.latitude, 3), "lon": round(loc.longitude, 3), "ts": ts}

    async def expire(chat_data=context.chat_data):  # wipe on time even if the user never writes again
        await asyncio.sleep(LOCATION_TTL_S)
        if (chat_data.get("loc") or {}).get("ts") == ts:
            chat_data.pop("loc", None)
    context.application.create_task(expire())
    await update.message.reply_text("Локацию получил (округлил до ~100 м). Что хочется? Нажмите кнопку или напишите своими словами.",
                                    reply_markup=_scenario_buttons())


async def on_scenario(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    key = (q.data or "").removeprefix("sc:")
    if key not in SCENARIOS:
        return
    if _saved_location(context) is None:
        await q.message.reply_text("Локация устарела. Отправьте её ещё раз 👇", reply_markup=_keyboard())
        return
    await _run(update, context, SCENARIOS[key][1])


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _run(update, context, update.message.text)


async def on_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_chat.send_action(ChatAction.TYPING)
    data = bytes(await (await update.message.photo[-1].get_file()).download_as_bytearray())
    form = {"lang": _lang(update, update.message.caption or ""), "channel": "telegram"}
    if update.message.caption:
        form["query"] = update.message.caption[:1000]
    r = await _http.post(f"{API}/api/recommend/photo", data=form, files={"image": ("photo.jpg", data, "image/jpeg")})
    if r.status_code == 503:
        await update.message.reply_text("Распознавание по фото сейчас недоступно. Напишите, где вы.")
        return
    r.raise_for_status()
    await _reply(update, format_response(r.json()))


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.error("telegram handler failed: %s", type(context.error).__name__)
    if isinstance(update, Update) and update.effective_message:
        await update.effective_message.reply_text("Что-то пошло не так, попробуйте ещё раз через минуту.")


def build_app(token: str) -> Application:
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler(["start", "help"], start))
    app.add_handler(CommandHandler("forget", forget))
    app.add_handler(MessageHandler(filters.LOCATION, on_location))
    app.add_handler(MessageHandler(filters.PHOTO, on_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_handler(CallbackQueryHandler(on_scenario, pattern=r"^sc:"))
    app.add_error_handler(on_error)
    return app


def main() -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise SystemExit("Нужен TELEGRAM_BOT_TOKEN")
    build_app(token.strip()).run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()

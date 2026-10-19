"""Telegram-бот Seruendesh AI: геолокация / текст / фото → 1–3 места рядом.

Пайплайн вызывается напрямую (тот же, что у HTTP API и MCP).
Приватность: локация округляется до ~100 м, живёт только в памяти процесса 30 минут, /forget стирает сразу.
В логах нет chat_id, координат и текста сообщений.

Запуск из корня:  python -m backend.telegram_bot.bot   (нужен TELEGRAM_BOT_TOKEN в .env)
"""
import asyncio
import logging
import os
import time

from telegram import (InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup, Update)
from telegram.constants import ChatAction, ParseMode
from telegram.ext import (Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters)

from backend.app import vision
from backend.app.config import get_settings  # noqa: F401 — загружает .env до чтения токена
from backend.app.guards import mask_pii
from backend.app.pipeline import photo_not_recognized, recommend_with_stats
from backend.app.schemas import Location, RecommendRequest

from .format import SCENARIOS, format_response

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("backend.telegram")

LOCATION_TTL_S = 30 * 60
LOCATION_BUTTON = "📍 Отправить геолокацию"

WELCOME = (
    "Привет! Я подскажу, куда сходить в Астане рядом с вами.\n\n"
    "• Отправьте <b>геолокацию</b> и выберите, что хочется;\n"
    "• или напишите, например: <i>«я возле Байтерека, хочу кофе и посидеть с ноутбуком»</i>;\n"
    "• или пришлите <b>фото</b> того, что видите, и я узнаю место.\n\n"
    "🔒 Локацию округляю до ~100 м, держу в памяти 30 минут и никуда не сохраняю. /forget стирает её сразу."
)


def _keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup([[KeyboardButton(LOCATION_BUTTON, request_location=True)]], resize_keyboard=True)


def _scenario_buttons() -> InlineKeyboardMarkup:
    items = list(SCENARIOS.items())
    rows = [[InlineKeyboardButton(label, callback_data=f"sc:{key}") for key, (label, _) in items[i:i + 2]]
            for i in range(0, len(items), 2)]
    return InlineKeyboardMarkup(rows)


def _lang(update: Update) -> str | None:
    code = (update.effective_user.language_code or "") if update.effective_user else ""
    return code if code in {"kk", "en"} else None


def _saved_location(context: ContextTypes.DEFAULT_TYPE) -> Location | None:
    saved = context.chat_data.get("loc")
    if not saved or time.monotonic() - saved["ts"] > LOCATION_TTL_S:
        context.chat_data.pop("loc", None)
        return None
    return Location(lat=saved["lat"], lon=saved["lon"])


async def _reply(update: Update, text: str) -> None:
    msg = update.effective_message
    for chunk in [text[i:i + 4000] for i in range(0, len(text), 4000)]:
        await msg.reply_text(chunk, parse_mode=ParseMode.HTML, disable_web_page_preview=True)


async def _run(update: Update, context: ContextTypes.DEFAULT_TYPE, query: str) -> None:
    await update.effective_chat.send_action(ChatAction.TYPING)
    req = RecommendRequest(query=query[:1000], location=_saved_location(context), lang=_lang(update))
    resp, stats = await asyncio.to_thread(recommend_with_stats, req)
    log.info("telegram recs=%d cache=%s latency_ms=%s", len(resp.recommendations), stats.get("cache"), stats.get("latency_ms"))
    await _reply(update, format_response(resp))


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(WELCOME, parse_mode=ParseMode.HTML, reply_markup=_keyboard())


async def forget(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    timer = context.chat_data.pop("_loc_timer", None)
    if timer:
        timer.cancel()
    context.chat_data.clear()
    await update.message.reply_text("Готово, локацию забыл.")


async def on_location(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    loc = update.message.location
    saved = {"lat": round(loc.latitude, 3), "lon": round(loc.longitude, 3), "ts": time.monotonic()}
    timer = context.chat_data.pop("_loc_timer", None)
    if timer:
        timer.cancel()
    context.chat_data["loc"] = saved

    def expire():
        # Identity prevents a stale timer from deleting a newer location.
        if context.chat_data.get("loc") is saved:
            context.chat_data.pop("loc", None)
            context.chat_data.pop("_loc_timer", None)

    context.chat_data["_loc_timer"] = asyncio.get_running_loop().call_later(LOCATION_TTL_S, expire)
    await update.message.reply_text(
        "Локацию получил (округлил до ~100 м). Что хочется? Можно нажать кнопку или написать своими словами.",
        reply_markup=_scenario_buttons(),
    )


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
    photo = update.message.photo[-1]  # самый большой размер
    file = await photo.get_file()
    # Telegram supplies trusted file metadata; reject missing/oversized sizes
    # before asking its client to buffer the download.
    size = file.file_size or photo.file_size
    if not size or size > vision.MAX_BYTES:
        await update.message.reply_text("Фото больше 8 МБ или размер неизвестен")
        return
    data = bytes(await file.download_as_bytearray())
    caption = update.message.caption or "Что интересного рядом?"
    req = RecommendRequest(query=caption[:1000], lang=_lang(update))
    try:
        data_url = await asyncio.to_thread(vision.prepare_image, data, "image/jpeg")
    except vision.PhotoError as e:
        await update.message.reply_text(str(e))
        return
    guess = await asyncio.to_thread(vision.identify_landmark, data_url, mask_pii(caption))
    place = vision.resolve(guess)
    if not place:
        await _reply(update, format_response(photo_not_recognized(req, guess.seen)))
        return
    resp, _ = await asyncio.to_thread(recommend_with_stats, req, True, place)
    resp.notes.insert(0, f"По фото определил: {place['label']}. Если это не так, напишите, где вы.")
    await _reply(update, format_response(resp))


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
    token = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("telegram_bot_token")
    if not token:
        raise SystemExit("Нужен TELEGRAM_BOT_TOKEN в .env")
    build_app(token.strip()).run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()

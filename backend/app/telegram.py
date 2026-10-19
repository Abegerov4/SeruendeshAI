"""Telegram channel inside the web service: the bot (bot/telegram_bot.py, Abegerov4's client of the public API)
receives updates by webhook instead of long polling, so it runs wherever the site runs — no second process.

Enabled only when TELEGRAM_BOT_TOKEN and PUBLIC_URL are set. Telegram proves each call with a secret header
derived from the token; the bot reaches the API over localhost with the shared BOT_API_KEY, so every Telegram
user gets their own rate-limit budget. The token never leaves the environment and is never logged."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import os

from fastapi import APIRouter, HTTPException, Request, Response

from app.config import get_settings

log = logging.getLogger("seru.telegram")
router = APIRouter()
_STATE: dict = {"app": None, "secret": None, "watch": None}
WEBHOOK_PATH = "/telegram/webhook"
UPDATES = ["message", "callback_query"]
WATCH_S = 300


def _secret(token: str) -> str:
    key = (get_settings().secret_key or "seru-telegram").encode()
    return hmac.new(key, token.encode(), hashlib.sha256).hexdigest()[:48]  # Telegram allows [A-Za-z0-9_-], ≤256


async def start(port: int) -> None:
    s = get_settings()
    token = (s.telegram_bot_token or "").strip()
    if not token or not s.public_url:
        return
    try:
        # the bot module reads these at import: talk to this very process, prove the per-user budget key
        os.environ.setdefault("SERU_API", f"http://127.0.0.1:{port}")
        if s.bot_api_key:
            os.environ.setdefault("SERU_BOT_KEY", s.bot_api_key)
        from bot import telegram_bot as tb

        app = tb.build_app(token, webhook=True)
        await app.initialize()
        await app.start()
        secret = _secret(token)
        url = s.public_url.rstrip("/") + WEBHOOK_PATH
        await app.bot.set_webhook(url=url, secret_token=secret, allowed_updates=UPDATES)
        await app.bot.set_my_commands(tb.COMMANDS)
        _STATE.update(app=app, secret=secret, watch=asyncio.create_task(_watch(app, url, secret)))
        log.info("telegram bot @%s is listening by webhook", app.bot.username)
    except Exception as exc:  # the website must come up even if Telegram is unreachable
        log.warning("telegram bot not started: %s", type(exc).__name__)


async def _watch(app, url: str, secret: str) -> None:
    """Running the bot anywhere in polling mode with the same token (`make bot`) removes the webhook, and the
    production bot would stay silent until the next deploy. Every few minutes the webhook is checked and restored."""
    while True:
        await asyncio.sleep(WATCH_S)
        try:
            if (await app.bot.get_webhook_info()).url != url:
                await app.bot.set_webhook(url=url, secret_token=secret, allowed_updates=UPDATES)
                log.warning("telegram webhook was removed (a polling copy of the bot with this token?) — restored")
        except Exception as exc:  # Telegram unreachable: try again on the next round
            log.warning("telegram webhook check failed: %s", type(exc).__name__)


async def stop() -> None:
    app = _STATE.get("app")
    if (watch := _STATE.get("watch")) is not None:
        watch.cancel()
    if app is not None:
        await app.stop()
        await app.shutdown()  # the webhook stays registered: the next start re-registers it
        _STATE.update(app=None, secret=None, watch=None)


@router.post(WEBHOOK_PATH, include_in_schema=False)
async def webhook(request: Request) -> Response:
    app, secret = _STATE.get("app"), _STATE.get("secret")
    if app is None:
        raise HTTPException(status_code=404)
    if not hmac.compare_digest(request.headers.get("x-telegram-bot-api-secret-token", ""), secret):
        raise HTTPException(status_code=403)
    from telegram import Update

    await app.update_queue.put(Update.de_json(await request.json(), app.bot))  # answered by the bot's own workers
    return Response(status_code=200)

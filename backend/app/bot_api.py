"""Small API for the Telegram bot: the user's home (for «от дома») and voice messages as text. Only the bot can
call it — it proves the shared BOT_API_KEY and names the user by its salted hash (X-Seru-User), never by the
Telegram id."""
from __future__ import annotations

import asyncio
import hmac
import logging

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from pydantic import BaseModel, ConfigDict, Field

from app import db
from app.config import get_settings
from app.geo import in_astana, round_coord
from app.limiting import limiter
from app.llm import client as llm_client

log = logging.getLogger("seru.bot_api")
TRANSCRIBE_MODELS = ("gpt-4o-mini-transcribe", "whisper-1")
MAX_AUDIO = 4 * 1024 * 1024  # a few minutes of Telegram voice (Opus)
# the words people say here, so the model writes «Байтерек», not «Bay terek», and keeps Cyrillic for RU/KK speech
SPEECH_HINT = ("Голосовой запрос о прогулке по Астане: Байтерек, Хан Шатыр, EXPO, Mega Silk Way, Нуржол, набережная, кофе, "
               "парк, музей. Бәйтерек маңында серуендегім келеді, кофехана, саябақ.")

router = APIRouter()


class HomeIn(BaseModel):
    model_config = ConfigDict(strict=True)
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    label: str = Field(min_length=1, max_length=120)


def _user(request: Request) -> str:
    key = get_settings().bot_api_key
    user = request.headers.get("x-seru-user", "")[:64]
    if not key or not user or not hmac.compare_digest(request.headers.get("x-seru-bot-key", "").encode(), key.encode()):
        raise HTTPException(status_code=403, detail="bot only")
    if db.SessionLocal is None:
        db.init_db()
    return user


@router.get("/api/bot/home", include_in_schema=False)
def get_home(request: Request):
    user = _user(request)
    with db.SessionLocal() as s:
        h = s.get(db.BotHome, user)
        return {"home": {"lat": h.lat, "lon": h.lon, "label": h.label} if h else None}


@router.put("/api/bot/home", include_in_schema=False)
def put_home(body: HomeIn, request: Request):
    user = _user(request)
    lat, lon = round_coord(body.lat), round_coord(body.lon)
    if not in_astana(lat, lon):
        raise HTTPException(status_code=422, detail="outside_astana")
    with db.SessionLocal.begin() as s:
        h = s.get(db.BotHome, user)
        if h is None:
            s.add(db.BotHome(user_hash=user, lat=lat, lon=lon, label=body.label.strip()))
        else:
            h.lat, h.lon, h.label = lat, lon, body.label.strip()
    return {"home": {"lat": lat, "lon": lon, "label": body.label.strip()}}


@router.delete("/api/bot/home", include_in_schema=False)
def delete_home(request: Request):
    user = _user(request)
    with db.SessionLocal.begin() as s:
        if h := s.get(db.BotHome, user):
            s.delete(h)
    return {"home": None}


@router.post("/api/bot/transcribe", include_in_schema=False)
async def transcribe(request: Request, audio: UploadFile = File(...)):
    """A Telegram voice message as text (RU/KK/EN detected by the model). The audio goes to the speech model and is
    dropped: nothing is stored or logged."""
    user = _user(request)
    if not limiter.allow("transcribe", user, 10, 60):
        raise HTTPException(status_code=429, detail="Too many voice messages, try again in a minute")
    data = await audio.read(MAX_AUDIO + 1)
    if not data or len(data) > MAX_AUDIO:
        raise HTTPException(status_code=413, detail="too_long")
    c = llm_client()
    if c is None:
        raise HTTPException(status_code=503, detail="speech_off")
    name, kind = audio.filename or "voice.ogg", audio.content_type or "audio/ogg"
    for model in TRANSCRIBE_MODELS:
        try:
            r = await asyncio.wait_for(c.with_options(timeout=30).audio.transcriptions.create(
                model=model, file=(name, data, kind), prompt=SPEECH_HINT), timeout=35)
            return {"text": (r.text or "").strip()[:1000], "model": model}
        except Exception as exc:  # the next model, then an honest «не разобрал»
            log.warning("transcribe %s failed: %s", model, type(exc).__name__)
    raise HTTPException(status_code=502, detail="speech_unavailable")

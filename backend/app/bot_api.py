"""Small API for the Telegram bot's memory: the user's home (for «от дома»). Only the bot can call it — it proves
the shared BOT_API_KEY and names the user by its salted hash (X-Seru-User), never by the Telegram id."""
from __future__ import annotations

import hmac

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app import db
from app.config import get_settings
from app.geo import in_astana, round_coord

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

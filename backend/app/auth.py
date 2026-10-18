"""Accounts: registration, login (httpOnly signed session cookie), saved places, account deletion,
password reset by email (when SMTP is configured)."""
from __future__ import annotations

import datetime as dt
import hashlib
import logging
import secrets
import smtplib
import time
from collections import defaultdict, deque
from email.message import EmailMessage
from typing import Annotated

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import PasswordReset, SavedPlace, User, get_session

log = logging.getLogger("app.auth")
router = APIRouter(prefix="/api", tags=["auth"])
COOKIE = "seru_session"
MAX_AGE = 30 * 24 * 3600
_ph = PasswordHasher()
_fallback_secret = secrets.token_urlsafe(32)
DbSession = Annotated[Session, Depends(get_session)]


def _signer() -> URLSafeTimedSerializer:
    s = get_settings()
    return URLSafeTimedSerializer(s.secret_key or _fallback_secret, salt="seru-session")


# --- schemas ------------------------------------------------------------------------------------

class UserOut(BaseModel):
    id: str
    email: str
    name: str
    lang: str
    created_at: dt.datetime


class RegisterIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    lang: str = Field("ru", pattern="^(ru|kk|en)$")

    @field_validator("name")
    @classmethod
    def _clean_name(cls, v: str) -> str:
        v = " ".join(v.split())
        if len(v) < 2:
            raise ValueError("name too short")
        return v


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class ResetRequestIn(BaseModel):
    email: EmailStr


class ResetConfirmIn(BaseModel):
    token: str = Field(min_length=20, max_length=200)
    password: str = Field(min_length=8, max_length=128)


class SavedIn(BaseModel):
    data: dict = Field(default_factory=dict)


class SavedOut(BaseModel):
    poi_id: str
    data: dict
    created_at: dt.datetime


# --- helpers --------------------------------------------------------------------------------------

_attempts: dict[str, deque] = defaultdict(deque)


def _throttle(request: Request, bucket: str, limit: int) -> None:
    """Brute-force guard: per-IP sliding window (IP kept in memory 10 min, never logged)."""
    ip = request.headers.get("x-forwarded-for", request.client.host if request.client else "?").split(",")[0].strip()
    q, now = _attempts[bucket + ip], time.time()
    while q and now - q[0] > 600:
        q.popleft()
    if len(q) >= limit:
        raise HTTPException(status_code=429, detail="too_many_attempts")
    q.append(now)


def _set_session(response: Response, request: Request, user: User) -> None:
    token = _signer().dumps({"uid": user.id, "pv": user.password_hash[-12:]})
    secure = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    response.set_cookie(COOKIE, token, max_age=MAX_AGE, httponly=True, secure=secure, samesite="lax", path="/")


def _out(u: User) -> UserOut:
    return UserOut(id=u.id, email=u.email, name=u.name, lang=u.lang, created_at=u.created_at)


def current_user(request: Request, db: DbSession) -> User:
    raw = request.cookies.get(COOKIE)
    if not raw:
        raise HTTPException(status_code=401, detail="not_authenticated")
    try:
        data = _signer().loads(raw, max_age=MAX_AGE)
    except (BadSignature, SignatureExpired):
        raise HTTPException(status_code=401, detail="session_expired") from None
    user = db.get(User, data.get("uid"))
    # a password change invalidates older sessions
    if not user or not user.password_hash.endswith(data.get("pv", "-")):
        raise HTTPException(status_code=401, detail="not_authenticated")
    return user


CurrentUser = Annotated[User, Depends(current_user)]


# --- endpoints ------------------------------------------------------------------------------------

@router.post("/auth/register", response_model=UserOut, status_code=201, summary="Create an account (sets session cookie)")
def register(body: RegisterIn, request: Request, response: Response, db: DbSession):
    _throttle(request, "reg:", 10)
    email = body.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status_code=409, detail="email_taken")
    user = User(email=email, name=body.name, password_hash=_ph.hash(body.password), lang=body.lang,
                last_login_at=dt.datetime.now(dt.timezone.utc))
    db.add(user)
    db.commit()
    _set_session(response, request, user)
    log.info("account created")
    return _out(user)


@router.post("/auth/login", response_model=UserOut, summary="Log in (sets session cookie)")
def login(body: LoginIn, request: Request, response: Response, db: DbSession):
    _throttle(request, "login:", 12)
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    try:
        if not user:
            _ph.hash(body.password)  # same timing for unknown emails
            raise VerifyMismatchError
        _ph.verify(user.password_hash, body.password)
    except (VerifyMismatchError, InvalidHashError):
        raise HTTPException(status_code=401, detail="invalid_credentials") from None
    if _ph.check_needs_rehash(user.password_hash):
        user.password_hash = _ph.hash(body.password)
    user.last_login_at = dt.datetime.now(dt.timezone.utc)
    db.commit()
    _set_session(response, request, user)
    return _out(user)


@router.post("/auth/logout", status_code=204, summary="Log out")
def logout(response: Response):
    response.delete_cookie(COOKIE, path="/")


@router.get("/auth/me", response_model=UserOut, summary="Current user (401 if not logged in)")
def me(user: CurrentUser):
    return _out(user)


@router.delete("/me", status_code=204, summary="Delete my account and all my data")
def delete_me(user: CurrentUser, response: Response, db: DbSession):
    for s in db.scalars(select(SavedPlace).where(SavedPlace.user_id == user.id)):
        db.delete(s)
    db.delete(user)
    db.commit()
    response.delete_cookie(COOKIE, path="/")
    log.info("account deleted")


@router.get("/me/saved", response_model=list[SavedOut], summary="My saved places")
def saved_list(user: CurrentUser, db: DbSession):
    rows = db.scalars(select(SavedPlace).where(SavedPlace.user_id == user.id).order_by(SavedPlace.created_at))
    return [SavedOut(poi_id=r.poi_id, data=r.data or {}, created_at=r.created_at) for r in rows]


@router.put("/me/saved/{poi_id}", response_model=SavedOut, summary="Save a place")
def saved_put(poi_id: str, body: SavedIn, user: CurrentUser, db: DbSession):
    if len(poi_id) > 80:
        raise HTTPException(status_code=422, detail="poi_id too long")
    keep = ("name", "category", "categoryKey", "lat", "lon", "address", "why", "action", "url", "image", "status",
            "distance", "travel", "visit", "visitRange", "mode", "features", "badges", "source", "generated",
            "dataSources", "descriptionSource", "openConfidence", "accessibility")
    data = {k: body.data[k] for k in keep if k in body.data}  # bounded snapshot, never locations of the user
    row = db.scalar(select(SavedPlace).where(SavedPlace.user_id == user.id, SavedPlace.poi_id == poi_id))
    if row:
        row.data = data
    else:
        if db.query(SavedPlace).filter(SavedPlace.user_id == user.id).count() >= 300:
            raise HTTPException(status_code=422, detail="too_many_saved")
        row = SavedPlace(user_id=user.id, poi_id=poi_id, data=data)
        db.add(row)
    db.commit()
    return SavedOut(poi_id=row.poi_id, data=row.data, created_at=row.created_at)


@router.delete("/me/saved/{poi_id}", status_code=204, summary="Remove a saved place")
def saved_delete(poi_id: str, user: CurrentUser, db: DbSession):
    row = db.scalar(select(SavedPlace).where(SavedPlace.user_id == user.id, SavedPlace.poi_id == poi_id))
    if row:
        db.delete(row)
        db.commit()


@router.post("/auth/password-reset/request", status_code=202, summary="Email a password-reset link")
def reset_request(body: ResetRequestIn, request: Request, db: DbSession):
    s = get_settings()
    if not (s.smtp_host and s.smtp_from):
        raise HTTPException(status_code=503, detail="email_unavailable")
    _throttle(request, "reset:", 5)
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    if user:  # same response whether or not the account exists
        token = secrets.token_urlsafe(32)
        db.add(PasswordReset(token_hash=hashlib.sha256(token.encode()).hexdigest(), user_id=user.id,
                             expires_at=dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)))
        db.commit()
        base = s.public_url.rstrip("/") or str(request.base_url).rstrip("/")
        _send_mail(user.email, "Seruendesh — восстановление пароля",
                   f"Сәлем, {user.name}!\n\nЧтобы задать новый пароль, откройте ссылку (действует 1 час):\n"
                   f"{base}/reset-password?token={token}\n\nЕсли вы не запрашивали сброс, просто проигнорируйте письмо.")
    return {"ok": True}


@router.post("/auth/password-reset/confirm", response_model=UserOut, summary="Set a new password with a reset token")
def reset_confirm(body: ResetConfirmIn, request: Request, response: Response, db: DbSession):
    _throttle(request, "resetc:", 10)
    row = db.get(PasswordReset, hashlib.sha256(body.token.encode()).hexdigest())
    now = dt.datetime.now(dt.timezone.utc)
    exp = row.expires_at if row and row.expires_at.tzinfo else (row.expires_at.replace(tzinfo=dt.timezone.utc) if row else None)
    if not row or row.used or exp < now:
        raise HTTPException(status_code=400, detail="invalid_or_expired_token")
    user = db.get(User, row.user_id)
    user.password_hash = _ph.hash(body.password)
    row.used = True
    db.commit()
    _set_session(response, request, user)
    return _out(user)


def _send_mail(to: str, subject: str, text: str) -> None:
    s = get_settings()
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = s.smtp_from, to, subject
    msg.set_content(text)
    try:
        with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=15) as smtp:
            smtp.starttls()
            if s.smtp_user:
                smtp.login(s.smtp_user, s.smtp_password)
            smtp.send_message(msg)
    except Exception as e:  # do not leak whether the account exists; just log the failure type
        log.warning("reset email failed: %s", type(e).__name__)

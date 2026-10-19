"""Accounts: registration, login (httpOnly opaque session cookie), saved places, account deletion,
password reset by email (when SMTP is configured)."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import secrets
import smtplib
from email.message import EmailMessage
from typing import Annotated
from urllib.parse import urlsplit

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator
from sqlalchemy import delete, select, text, update
from sqlalchemy.orm import Session

from ayat_backend.app.config import get_settings
from ayat_backend.app.db import AccountSession, PasswordReset, SavedPlace, User, get_session
from ayat_backend.app.limiting import client_key, limiter

log = logging.getLogger("app.auth")
router = APIRouter(prefix="/api", tags=["auth"])
COOKIE = "seru_session"
MAX_AGE = 30 * 24 * 3600
_ph = PasswordHasher()
DbSession = Annotated[Session, Depends(get_session)]

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


ShortText = Annotated[str, Field(max_length=300)]
LongText = Annotated[str, Field(max_length=2000)]
Labels = Annotated[list[Annotated[str, Field(max_length=150)]], Field(max_length=32)]
Minutes = Annotated[int, Field(ge=0, le=10080)]


class SavedSnapshot(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore", allow_inf_nan=False)
    name: ShortText | None = None
    category: ShortText | None = None
    categoryKey: ShortText | None = None
    lat: Annotated[float, Field(ge=-90, le=90)] | None = None
    lon: Annotated[float, Field(ge=-180, le=180)] | None = None
    address: Annotated[str, Field(max_length=1000)] | None = None
    why: LongText | None = None
    action: LongText | None = None
    url: Annotated[str, Field(max_length=2048)] | None = None
    image: Annotated[str, Field(max_length=2048)] | None = None
    status: ShortText | None = None
    distance: ShortText | None = None
    travel: Minutes | None = None
    visit: Minutes | None = None
    visitRange: Annotated[list[Minutes], Field(min_length=2, max_length=2)] | None = None
    mode: ShortText | None = None
    features: Labels | None = None
    badges: Labels | None = None
    source: ShortText | None = None
    generated: bool | None = None
    dataSources: Labels | None = None
    descriptionSource: ShortText | None = None
    openConfidence: ShortText | None = None
    accessibility: ShortText | None = None

    @field_validator("url", "image")
    @classmethod
    def _safe_url(cls, value, info):
        if value is None:
            return value
        if any(c.isspace() or ord(c) < 32 for c in value) or "\\" in value:
            raise ValueError("invalid URL")
        parts = urlsplit(value)
        if info.field_name == "image" and value.startswith("/") and not value.startswith("//"):
            return value
        if parts.scheme not in {"https", "http"} or not parts.hostname or parts.username or parts.password:
            raise ValueError("URL must use HTTP(S)")
        return value


class SavedIn(BaseModel):
    data: SavedSnapshot = Field(default_factory=SavedSnapshot)

    @model_validator(mode="before")
    @classmethod
    def _byte_limit(cls, value):
        try:
            size = len(json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8"))
        except ValueError:
            # Python's request decoder accepts nonstandard NaN/Infinity. Do not
            # let those values enter a Pydantic error payload that itself cannot
            # be JSON encoded by the HTTP validation-error handler.
            raise HTTPException(status_code=422, detail="invalid_saved_snapshot") from None
        if size > 16 * 1024:
            raise ValueError("saved snapshot exceeds 16 KiB")
        return value


class SavedOut(BaseModel):
    poi_id: str
    data: dict
    created_at: dt.datetime


# --- helpers --------------------------------------------------------------------------------------

def _throttle(request: Request, bucket: str, limit: int) -> None:
    if not limiter.allow(bucket, client_key(request), limit, 600):
        raise HTTPException(status_code=429, detail="too_many_attempts")


def _token_hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def _set_session(response: Response, request: Request, user: User, db: Session) -> None:
    token = secrets.token_urlsafe(32)
    now = dt.datetime.now(dt.timezone.utc)
    db.execute(delete(AccountSession).where(AccountSession.expires_at <= now))
    db.add(AccountSession(token_hash=_token_hash(token), user_id=user.id,
                          credential_hash=_token_hash(user.password_hash), expires_at=now + dt.timedelta(seconds=MAX_AGE)))
    response.set_cookie(COOKIE, token, max_age=MAX_AGE, httponly=True,
                        secure=request.url.scheme == "https", samesite="lax", path="/")


def _out(u: User) -> UserOut:
    return UserOut(id=u.id, email=u.email, name=u.name, lang=u.lang, created_at=u.created_at)


def current_user(request: Request, db: DbSession) -> User:
    raw = request.cookies.get(COOKIE)
    if not raw:
        raise HTTPException(status_code=401, detail="not_authenticated")
    session = db.get(AccountSession, _token_hash(raw))
    now = dt.datetime.now(dt.timezone.utc)
    if not session or session.expires_at.replace(tzinfo=dt.timezone.utc) <= now:
        raise HTTPException(status_code=401, detail="session_expired")
    user = db.get(User, session.user_id)
    if not user or not secrets.compare_digest(session.credential_hash, _token_hash(user.password_hash)):
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
    db.flush()
    _set_session(response, request, user, db)
    db.commit()
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
    db.flush()
    _set_session(response, request, user, db)
    db.commit()
    return _out(user)


@router.post("/auth/logout", status_code=204, summary="Log out")
def logout(response: Response, request: Request, db: DbSession):
    raw = request.cookies.get(COOKIE)
    if raw:
        db.execute(delete(AccountSession).where(AccountSession.token_hash == _token_hash(raw)))
        db.commit()
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


@router.put("/me/saved/{poi_id:path}", response_model=SavedOut, summary="Save a place")
def saved_put(poi_id: str, body: SavedIn, user: CurrentUser, db: DbSession):
    if len(poi_id) > 80:
        raise HTTPException(status_code=422, detail="poi_id too long")
    data = body.data.model_dump(exclude_unset=True)
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


@router.delete("/me/saved/{poi_id:path}", status_code=204, summary="Remove a saved place")
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
    # Hash before acquiring the write lock. SQLite needs an explicit immediate
    # transaction; Postgres locks the owning user to serialize *all* reset links.
    password_hash = _ph.hash(body.password)
    if db.bind.dialect.name == "sqlite":
        db.execute(text("BEGIN IMMEDIATE"))
    digest = _token_hash(body.token)
    row = db.get(PasswordReset, digest)
    now = dt.datetime.now(dt.timezone.utc)
    if not row:
        raise HTTPException(status_code=400, detail="invalid_or_expired_token")
    user = db.scalar(select(User).where(User.id == row.user_id).with_for_update())
    consumed = db.execute(update(PasswordReset).where(
        PasswordReset.token_hash == digest, PasswordReset.used.is_(False), PasswordReset.expires_at > now,
    ).values(used=True).execution_options(synchronize_session=False).returning(PasswordReset.token_hash)).scalar_one_or_none()
    if not user or not consumed:
        db.rollback()
        raise HTTPException(status_code=400, detail="invalid_or_expired_token")
    user.password_hash = password_hash
    db.execute(update(PasswordReset).where(PasswordReset.user_id == user.id).values(used=True))
    db.execute(delete(AccountSession).where(AccountSession.user_id == user.id))
    _set_session(response, request, user, db)
    db.commit()
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

"""Accounts storage: Postgres in production (Railway DATABASE_URL), SQLite locally/tests.

What is stored about a user — and nothing else: email, display name, argon2 password hash,
UI language, saved places (POI id + a small card snapshot), timestamps. No locations, no queries.
City Insights keeps only anonymous counters (≈1 km cell × 3-hour slot × intent), never text or a person.
"""
from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, Float, String, UniqueConstraint, create_engine, event, delete, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from app.config import get_settings
from app.paths import BACKEND_DIR


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(80))
    password_hash: Mapped[str] = mapped_column(String(255))
    lang: Mapped[str] = mapped_column(String(2), default="ru")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    last_login_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SavedPlace(Base):
    __tablename__ = "saved_places"
    __table_args__ = (UniqueConstraint("user_id", "poi_id", name="uq_saved_user_poi"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    poi_id: Mapped[str] = mapped_column(String(80))
    data: Mapped[dict] = mapped_column(JSON, default=dict)  # card snapshot to render the saved list offline
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class PasswordReset(Base):
    __tablename__ = "password_resets"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    used: Mapped[bool] = mapped_column(default=False)


class AccountSession(Base):
    __tablename__ = "account_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    credential_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), index=True)


class RateLimit(Base):
    __tablename__ = "rate_limits"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    hits: Mapped[int] = mapped_column(Integer)
    expires_at: Mapped[float] = mapped_column(Float, index=True)


class BotHome(Base):
    """A Telegram user's home for «от дома»: keyed by the bot's salted user hash (never the Telegram id),
    rounded to ~100 m, deleted by /forget."""
    __tablename__ = "bot_homes"
    user_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    label: Mapped[str] = mapped_column(String(120))
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class DemandCount(Base):
    """City Insights counter: no text, no person, no exact place — a ~1 km cell, a 3-hour slot and an intent."""
    __tablename__ = "demand_counts"
    key: Mapped[str] = mapped_column(String(96), primary_key=True)
    day: Mapped[str] = mapped_column(String(10), index=True)
    cell_lat: Mapped[float] = mapped_column(Float)
    cell_lon: Mapped[float] = mapped_column(Float)
    slot: Mapped[int] = mapped_column(Integer)
    intent: Mapped[str] = mapped_column(String(32))
    unmet: Mapped[int] = mapped_column(Integer)
    hits: Mapped[int] = mapped_column(Integer)


def _url() -> str:
    url = get_settings().database_url.strip()
    if not url:
        local = BACKEND_DIR / ".local"
        local.mkdir(exist_ok=True)
        return f"sqlite:///{local / 'app.db'}"
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


_engine = None
SessionLocal: sessionmaker | None = None


def init_db() -> None:
    global _engine, SessionLocal
    url = _url()
    kw = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        kw["connect_args"] = {"check_same_thread": False}
    _engine = create_engine(url, **kw)
    if url.startswith("sqlite"):
        @event.listens_for(_engine, "connect")
        def _sqlite_constraints(connection, _record):
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA busy_timeout=30000")
    Base.metadata.create_all(_engine)
    SessionLocal = sessionmaker(_engine, expire_on_commit=False)
    # Additive migration: preserve users and valid saved/reset data, remove only
    # rows whose owning account no longer exists (legacy SQLite FK omission).
    with SessionLocal.begin() as session:
        for model in (SavedPlace, PasswordReset, AccountSession):
            session.execute(delete(model).where(~model.user_id.in_(select(User.id))))
        session.execute(delete(AccountSession).where(AccountSession.expires_at <= _utcnow()))
    if not url.startswith("sqlite"):
        purge_reserved_test_accounts()


RESERVED_DOMAINS = ("@example.com", "@example.org", "@example.net")


def purge_reserved_test_accounts() -> int:
    """Accounts on RFC 2606 reserved domains can only come from our own end-to-end checks: remove them."""
    from sqlalchemy import delete, or_, select
    with SessionLocal() as s:
        ids = s.scalars(select(User.id).where(or_(*[User.email.like("%" + d) for d in RESERVED_DOMAINS]))).all()
        if ids:
            s.execute(delete(SavedPlace).where(SavedPlace.user_id.in_(ids)))
            s.execute(delete(PasswordReset).where(PasswordReset.user_id.in_(ids)))
            s.execute(delete(AccountSession).where(AccountSession.user_id.in_(ids)))
            s.execute(delete(User).where(User.id.in_(ids)))
            s.commit()
            import logging
            logging.getLogger("app.db").info("removed %d test accounts on reserved domains", len(ids))
        return len(ids)


def get_session():
    if SessionLocal is None:
        init_db()
    with SessionLocal() as s:
        yield s


def db_kind() -> str:
    return "postgres" if _url().startswith("postgresql") else "sqlite"

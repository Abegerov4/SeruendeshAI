"""Atomic shared fixed-window budgets in the existing account SQL storage.

Only the ASGI peer is trusted; proxy-header trust belongs to the server/ingress.
Keys contain a hash rather than the client address, and expired rows are removed
on every attempt, keeping storage proportional to traffic within the longest TTL.
"""
from __future__ import annotations

import hashlib
import time

from sqlalchemy import delete
from starlette.requests import Request

from ayat_backend.app import db


def client_key(request: Request) -> str:
    return request.client.host if request.client else "unknown-peer"


class StorageLimiter:
    def allow(self, bucket: str, key: str, limit: int, window_s: int, *, now: float | None = None) -> bool:
        if db.SessionLocal is None:
            db.init_db()
        now = time.time() if now is None else now
        digest = hashlib.sha256(f"{bucket}\0{key}".encode()).hexdigest()
        with db.SessionLocal.begin() as session:
            session.execute(delete(db.RateLimit).where(db.RateLimit.expires_at <= now))
            dialect = session.bind.dialect.name
            if dialect == "sqlite":
                from sqlalchemy.dialects.sqlite import insert
            elif dialect == "postgresql":
                from sqlalchemy.dialects.postgresql import insert
            else:
                raise RuntimeError("Unsupported rate-limit storage")
            # One atomic upsert: workers cannot independently read/consume the
            # same remaining slot. Denials do not extend the window or grow rows.
            stmt = insert(db.RateLimit).values(key=digest, hits=1, expires_at=now + window_s)
            stmt = stmt.on_conflict_do_update(
                index_elements=[db.RateLimit.key],
                set_={"hits": db.RateLimit.hits + 1},
                where=db.RateLimit.hits < limit,
            ).returning(db.RateLimit.key)
            return limit > 0 and session.execute(stmt).scalar_one_or_none() is not None


limiter = StorageLimiter()

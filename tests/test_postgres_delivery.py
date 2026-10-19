"""Opt-in disposable PostgreSQL verification; runner owns container lifecycle."""
import datetime as dt
import hashlib
import os
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text


@pytest.fixture
def postgres_client():
    configured = os.environ.get("DELIVERY_POSTGRES_URL")
    if not configured:
        pytest.skip("Disposable PostgreSQL not requested; run scripts/test_delivery_postgres.py")
    parsed = urlsplit(configured.replace("postgresql+psycopg://", "postgresql://"))
    assert parsed.hostname in {"127.0.0.1", "localhost"} and parsed.path == "/delivery", "Only the disposable local delivery database is allowed"
    from app import auth, db
    from app.config import get_settings
    admin = create_engine(configured.replace("postgresql://", "postgresql+psycopg://"))
    schema = "delivery_" + uuid.uuid4().hex
    with admin.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    settings = get_settings()
    previous = settings.database_url, db._engine, db.SessionLocal
    settings.database_url = configured + "?options=-csearch_path%3D" + schema
    try:
        db.init_db()
        app = FastAPI()
        app.include_router(auth.router)
        with TestClient(app) as client:
            yield client
    finally:
        if db._engine is not None:
            db._engine.dispose()
        settings.database_url, db._engine, db.SessionLocal = previous
        with admin.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def register(client):
    response = client.post("/api/auth/register", json={"name": "PG Delivery", "email": "pg-delivery@example.com", "password": "long local test password"})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def insert_reset(user_id, value):
    from app import db
    with db.SessionLocal.begin() as session:
        session.add(db.PasswordReset(user_id=user_id, token_hash=hashlib.sha256(value.encode()).hexdigest(),
                                     expires_at=dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)))


def test_postgres_migration_preserves_existing_accounts_and_saved_cards(postgres_client):
    from app import auth, db
    user_id = register(postgres_client)
    assert postgres_client.put("/api/me/saved/osm:node/321", json={"data": {"name": "Existing canonical card", "lat": 51.128}}).status_code == 200
    # Simulate the pre-session/pre-throttle account schema while retaining its actual account and card.
    with db._engine.begin() as conn:
        conn.execute(text("DROP TABLE account_sessions, rate_limits"))
    old = db._engine
    db.init_db()
    old.dispose()
    login = postgres_client.post("/api/auth/login", json={"email": "pg-delivery@example.com", "password": "long local test password"})
    assert login.status_code == 200 and login.json()["id"] == user_id
    assert postgres_client.get("/api/me/saved").json()[0]["data"] == {"name": "Existing canonical card", "lat": 51.128}
    assert postgres_client.get("/api/auth/me").status_code == 200
    with db.SessionLocal() as session:
        assert len(list(session.scalars(select(db.User)))) == 1
        assert len(list(session.scalars(select(db.SavedPlace)))) == 1
        assert len(list(session.scalars(select(db.AccountSession)))) == 1


def test_postgres_reset_atomicity_and_all_session_revocation(postgres_client):
    from app import auth, db
    uid = register(postgres_client)
    old_cookie = postgres_client.cookies.get(auth.COOKIE)
    first, second = "a" * 32, "b" * 32
    insert_reset(uid, first)
    insert_reset(uid, second)
    def reset(_):
        return postgres_client.post("/api/auth/password-reset/confirm", json={"token": second, "password": "new local delivery password"}).status_code
    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(reset, range(2))) == [200, 400]
    assert postgres_client.post("/api/auth/password-reset/confirm", json={"token": first, "password": "another local password"}).status_code == 400
    postgres_client.cookies.set(auth.COOKIE, old_cookie)
    assert postgres_client.get("/api/auth/me").status_code == 401
    with db.SessionLocal() as session:
        resets = list(session.scalars(select(db.PasswordReset)))
        assert len(resets) == 2 and all(row.used for row in resets)
        assert len(list(session.scalars(select(db.AccountSession)))) == 1
    assert postgres_client.post("/api/auth/login", json={"email": "pg-delivery@example.com", "password": "new local delivery password"}).status_code == 200


def test_postgres_logout_revokes_only_selected_session(postgres_client):
    from app import auth
    register(postgres_client)
    initial = postgres_client.cookies.get(auth.COOKIE)
    assert postgres_client.post("/api/auth/login", json={"email": "pg-delivery@example.com", "password": "long local test password"}).status_code == 200
    other = postgres_client.cookies.get(auth.COOKIE)
    postgres_client.cookies.set(auth.COOKIE, initial)
    assert postgres_client.post("/api/auth/logout").status_code == 204
    postgres_client.cookies.set(auth.COOKIE, initial)
    assert postgres_client.get("/api/auth/me").status_code == 401
    postgres_client.cookies.set(auth.COOKIE, other)
    assert postgres_client.get("/api/auth/me").status_code == 200


def test_postgres_atomic_shared_limiter_and_ttl_cleanup(postgres_client):
    from app import db
    from app.limiting import StorageLimiter
    def consume(_):
        return StorageLimiter().allow("parallel", "peer", 3, 60, now=100)
    with ThreadPoolExecutor(max_workers=8) as executor:
        assert sum(executor.map(consume, range(30))) == 3
    assert not StorageLimiter().allow("parallel", "peer", 3, 60, now=101)
    assert StorageLimiter().allow("new", "peer", 1, 60, now=161)
    with db.SessionLocal() as session:
        assert session.execute(text("SELECT count(*) FROM rate_limits")).scalar_one() == 1


def test_postgres_delete_cascades_saved_reset_and_sessions(postgres_client):
    from app import db
    uid = register(postgres_client)
    insert_reset(uid, "d" * 32)
    assert postgres_client.put("/api/me/saved/osm:node/123", json={"data": {"name": "Delete with account"}}).status_code == 200
    assert postgres_client.delete("/api/me").status_code == 204
    with db.SessionLocal() as session:
        for model in (db.User, db.SavedPlace, db.PasswordReset, db.AccountSession):
            assert list(session.scalars(select(model))) == []

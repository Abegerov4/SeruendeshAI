"""Security regressions use only disposable databases and local HTTP clients."""
import datetime as dt
import hashlib
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from starlette.requests import Request

from app import auth, db
from app.config import get_settings


@pytest.fixture
def isolated(tmp_path):
    settings = get_settings()
    previous = settings.database_url, db._engine, db.SessionLocal
    settings.database_url = f"sqlite:///{tmp_path / 'accounts.db'}"
    db.init_db()
    app = FastAPI()
    app.include_router(auth.router)
    with TestClient(app) as client:
        yield client
    db._engine.dispose()
    settings.database_url, db._engine, db.SessionLocal = previous


def register(client):
    result = client.post('/api/auth/register', json={
        'name': 'Local User', 'email': 'security@example.com', 'password': 'long local password',
    })
    assert result.status_code == 201, result.text
    return result.json()['id']


def reset_token(uid, token):
    with db.SessionLocal() as session:
        session.add(db.PasswordReset(token_hash=hashlib.sha256(token.encode()).hexdigest(), user_id=uid,
                                     expires_at=dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)))
        session.commit()


def confirm(client, token):
    return client.post('/api/auth/password-reset/confirm', json={'token': token, 'password': 'a new local password'})


def request(xff='one'):
    return Request({'type': 'http', 'client': ('trusted-peer', 123), 'headers': [(b'x-forwarded-for', xff.encode())]})


def test_spoofed_xff_cannot_reset_auth_limit(isolated):
    for i in range(2):
        auth._throttle(request(str(i)), 'spoof:', 2)
    with pytest.raises(HTTPException) as error:
        auth._throttle(request('new-ip'), 'spoof:', 2)
    assert error.value.status_code == 429


def test_limiter_instances_share_atomic_budget_and_expire_storage(isolated):
    from app.limiting import StorageLimiter
    first, second = StorageLimiter(), StorageLimiter()
    assert first.allow('test', 'peer', 1, 60, now=100)
    assert not second.allow('test', 'peer', 1, 60, now=101)
    assert second.allow('test', 'other-peer', 1, 60, now=161)
    with db.SessionLocal() as session:
        rows = session.execute(text('SELECT count(*) FROM rate_limits')).scalar_one()
    assert rows == 1


def test_recommend_limiter_ignores_spoofed_xff(isolated, monkeypatch):
    from app import main
    monkeypatch.setattr(main.settings, 'rate_limit_per_min', 1)
    assert not main._rate_limited(request('one'))
    assert main._rate_limited(request('two'))


def test_logout_revokes_replayed_cookie_but_keeps_other_session(isolated):
    register(isolated)
    token = isolated.cookies.get(auth.COOKIE)
    login = isolated.post('/api/auth/login', json={'email': 'security@example.com', 'password': 'long local password'})
    assert login.status_code == 200
    other = isolated.cookies.get(auth.COOKIE)
    isolated.cookies.set(auth.COOKIE, token)
    assert isolated.post('/api/auth/logout').status_code == 204
    isolated.cookies.set(auth.COOKIE, token)
    assert isolated.get('/api/auth/me').json() == {"user": None}  # guests: 200 {user: null}
    isolated.cookies.set(auth.COOKIE, other)
    assert isolated.get('/api/auth/me').status_code == 200


def test_account_delete_cascades_all_owned_rows(isolated):
    uid = register(isolated)
    reset_token(uid, 'a' * 32)
    isolated.put('/api/me/saved/osm:node/1', json={'data': {'name': 'Museum'}})
    assert isolated.delete('/api/me').status_code == 204
    with db.SessionLocal() as session:
        assert session.execute(text('PRAGMA foreign_keys')).scalar_one() == 1
        assert list(session.scalars(select(db.PasswordReset))) == []
        assert list(session.scalars(select(db.SavedPlace))) == []
    assert confirm(isolated, 'a' * 32).status_code == 400


def test_orphan_reset_token_is_controlled_error(isolated):
    with db._engine.connect() as conn:
        conn.exec_driver_sql('PRAGMA foreign_keys=OFF')
        conn.execute(text("INSERT INTO password_resets(token_hash,user_id,expires_at,used) VALUES (:token,'missing','2099-01-01',0)"),
                     {'token': hashlib.sha256(('o' * 32).encode()).hexdigest()})
        conn.commit()
        conn.exec_driver_sql('PRAGMA foreign_keys=ON')
    assert confirm(isolated, 'o' * 32).status_code == 400


def test_successful_reset_revokes_every_reset_and_prior_session(isolated):
    uid = register(isolated)
    old_session = isolated.cookies.get(auth.COOKIE)
    reset_token(uid, 'a' * 32)
    reset_token(uid, 'b' * 32)
    assert confirm(isolated, 'b' * 32).status_code == 200
    assert confirm(isolated, 'a' * 32).status_code == 400
    isolated.cookies.set(auth.COOKIE, old_session)
    assert isolated.get('/api/auth/me').json() == {"user": None}  # guests: 200 {user: null}


def test_reset_consumption_is_atomic(isolated):
    uid = register(isolated)
    reset_token(uid, 'c' * 32)
    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = list(executor.map(lambda _: confirm(isolated, 'c' * 32).status_code, range(2)))
    assert sorted(statuses) == [200, 400]


@pytest.mark.parametrize('data', [
    {'name': 'x' * 1_000_000}, {'lat': '51.1'}, {'lat': 91}, {'features': {}},
    {'url': 'javascript:alert(1)'}, {'features': ['x'] * 200},
])
def test_saved_snapshot_rejects_unbounded_or_mistyped_fields(isolated, data):
    register(isolated)
    assert isolated.put('/api/me/saved/osm:node/123', json={'data': data}).status_code in (413, 422)


def test_sqlite_migration_keeps_accounts_and_valid_saved_data(isolated):
    uid = register(isolated)
    reset_token(uid, 'v' * 32)
    assert isolated.put('/api/me/saved/osm:node/321', json={'data': {'name': 'Kept card'}}).status_code == 200
    with db._engine.connect() as conn:
        conn.exec_driver_sql('PRAGMA foreign_keys=OFF')
        conn.execute(text("INSERT INTO saved_places(user_id,poi_id,data,created_at) VALUES ('missing','old','{}','2020-01-01')"))
        conn.execute(text("INSERT INTO password_resets(token_hash,user_id,expires_at,used) VALUES ('orphan','missing','2099-01-01',0)"))
        conn.commit()
        conn.exec_driver_sql('PRAGMA foreign_keys=ON')
    old_engine = db._engine
    db.init_db()
    old_engine.dispose()
    assert isolated.get('/api/auth/me').status_code == 200
    assert isolated.get('/api/me/saved').json()[0]['data'] == {'name': 'Kept card'}
    with db.SessionLocal() as session:
        assert len(list(session.scalars(select(db.User)))) == 1
        assert len(list(session.scalars(select(db.SavedPlace)))) == 1
        assert len(list(session.scalars(select(db.PasswordReset)))) == 1
        assert session.execute(text('PRAGMA foreign_key_check')).all() == []


def test_limiter_concurrent_consumption_cannot_exceed_budget(isolated):
    from app.limiting import StorageLimiter
    def consume(_):
        return StorageLimiter().allow('concurrent', 'peer', 3, 60, now=100)
    with ThreadPoolExecutor(max_workers=8) as executor:
        assert sum(executor.map(consume, range(30))) == 3


def test_sessions_store_only_verifiers_and_enforce_expiry(isolated):
    uid = register(isolated)
    raw = isolated.cookies.get(auth.COOKIE)
    with db.SessionLocal.begin() as session:
        stored = session.scalar(select(db.AccountSession).where(db.AccountSession.user_id == uid))
        assert stored.token_hash != raw
        assert stored.token_hash == hashlib.sha256(raw.encode()).hexdigest()
        stored.expires_at = dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=1)
    assert isolated.get('/api/auth/me').json() == {"user": None}  # guests: 200 {user: null}


def test_complete_valid_snapshot_survives_slash_id_roundtrip(isolated):
    register(isolated)
    card = {'name': 'Park', 'category': 'Парк', 'categoryKey': 'park', 'lat': 51.128, 'lon': 71.43,
            'image': '/images/stories/walk.webp', 'url': 'https://www.openstreetmap.org/node/123',
            'why': 'Рядом и спокойно', 'action': 'Пройти по дорожке', 'distance': '500 м',
            'travel': 7, 'visit': 20, 'visitRange': [15, 30], 'mode': 'walk', 'features': ['Бесплатно'],
            'badges': ['outdoor'], 'dataSources': ['osm'], 'status': 'Часы неизвестны',
            'openConfidence': 'none', 'accessibility': 'unknown', 'source': 'Данные POI', 'generated': False}
    response = isolated.put('/api/me/saved/osm:node/123', json={'data': card})
    assert response.status_code == 200, response.text
    assert isolated.get('/api/me/saved').json()[0]['data'] == card


def test_independent_processes_share_the_same_sql_budget(isolated):
    import subprocess
    import sys
    program = '''
import sys
from app.config import get_settings
get_settings().database_url = sys.argv[1]
from app import db
from app.limiting import StorageLimiter
db.init_db()
print(int(StorageLimiter().allow("workers", "peer", 1, 60, now=100)))
'''
    url = get_settings().database_url
    def consume(_):
        result = subprocess.run([sys.executable, '-c', program, url], capture_output=True, text=True, check=True)
        return int(result.stdout.strip())
    with ThreadPoolExecutor(max_workers=4) as executor:
        assert sum(executor.map(consume, range(4))) == 1


@pytest.mark.parametrize('number', ['NaN', 'Infinity', '-Infinity'])
def test_saved_snapshot_nonfinite_coordinate_is_controlled_error(isolated, number):
    register(isolated)
    response = isolated.put('/api/me/saved/osm:node/123', content='{"data":{"lat":' + number + '}}',
                            headers={'content-type': 'application/json'})
    assert response.status_code == 422


def test_saved_snapshot_byte_limit_counts_utf8_bytes(isolated):
    register(isolated)
    data = {'why': '界' * 2000, 'action': '界' * 2000, 'features': ['界' * 150] * 16}
    # Every individual field satisfies its character/list limit, but UTF-8 total exceeds 16 KiB.
    assert isolated.put('/api/me/saved/osm:node/123', json={'data': data}).status_code == 422

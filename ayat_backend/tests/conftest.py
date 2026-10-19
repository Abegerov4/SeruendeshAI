"""Ayat tests use local data and a disposable SQLite database, with no providers."""
import os
import socket

import pytest


for key, value in {
    "LLM_ENABLED": "false", "EMBED_MODEL": "off", "WEATHER_ENABLED": "false",
    "OPENAI_API_KEY": "", "LLM_API_KEY": "", "openai_api_key": "",
    "SMTP_HOST": "", "SMTP_FROM": "", "SMTP_USER": "", "SMTP_PASSWORD": "",
    "SECRET_KEY": "ayat-local-tests-only",
}.items():
    os.environ[key] = value

from ayat_backend.app.config import Settings, get_settings  # noqa: E402

# Test collection must never obtain secrets from a checkout's dotenv files.
Settings.model_config = {**Settings.model_config, "env_file": None}
get_settings.cache_clear()


@pytest.fixture(scope="module", autouse=True)
def no_external_network():
    def deny_connection(*args, **kwargs):
        raise AssertionError("Ayat tests must not open external network connections")

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(socket.socket, "connect", deny_connection)
        monkeypatch.setattr(socket.socket, "connect_ex", deny_connection)
        yield


@pytest.fixture(scope="module")
def client(tmp_path_factory, no_external_network):
    from fastapi.testclient import TestClient

    from ayat_backend.app import db
    from ayat_backend.app.main import RT, app

    settings = get_settings()
    prior_url = settings.database_url
    settings.database_url = f"sqlite:///{tmp_path_factory.mktemp('ayat-accounts') / 'accounts.db'}"
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        if db._engine is not None:
            db._engine.dispose()
        db._engine = None
        db.SessionLocal = None
        RT.clear()
        settings.database_url = prior_url

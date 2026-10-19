"""The Telegram bot gets per-user rate-limit keys only with the shared secret."""
from types import SimpleNamespace

from starlette.requests import Request

from app import limiting


def req(headers: dict[str, str], ip="10.0.0.1") -> Request:
    raw = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    return Request({"type": "http", "headers": raw, "client": (ip, 1234)})


def test_bot_users_get_separate_keys_with_the_secret(monkeypatch):
    monkeypatch.setattr(limiting, "get_settings", lambda: SimpleNamespace(bot_api_key="s3cret"))
    a = limiting.api_client_key(req({"X-Seru-Bot-Key": "s3cret", "X-Seru-User": "aaa"}))
    b = limiting.api_client_key(req({"X-Seru-Bot-Key": "s3cret", "X-Seru-User": "bbb"}))
    assert a == "bot:aaa" and b == "bot:bbb"


def test_without_a_valid_secret_the_ip_is_the_key(monkeypatch):
    monkeypatch.setattr(limiting, "get_settings", lambda: SimpleNamespace(bot_api_key="s3cret"))
    assert limiting.api_client_key(req({"X-Seru-Bot-Key": "wrong", "X-Seru-User": "aaa"})) == "10.0.0.1"
    assert limiting.api_client_key(req({"X-Seru-Bot-Key": "s3cret"})) == "10.0.0.1"
    monkeypatch.setattr(limiting, "get_settings", lambda: SimpleNamespace(bot_api_key=""))
    assert limiting.api_client_key(req({"X-Seru-Bot-Key": "", "X-Seru-User": "aaa"})) == "10.0.0.1"

"""Both backend applications must be importable from the repository root."""
import importlib

import pytest


def test_ayat_and_primary_apps_import_without_generic_app_package(monkeypatch):
    for key, value in {
        "LLM_ENABLED": "false", "EMBED_MODEL": "off", "WEATHER_ENABLED": "false",
        "OPENAI_API_KEY": "", "LLM_API_KEY": "", "openai_api_key": "",
        "LANGFUSE_PUBLIC_KEY": "", "LANGFUSE_SECRET_KEY": "",
    }.items():
        monkeypatch.setenv(key, value)
    try:
        ayat = importlib.import_module("ayat_backend.app.main")
        primary = importlib.import_module("backend.app.main")
    except ModuleNotFoundError as error:
        pytest.fail(f"Backend applications must use their own package namespace: {error}")
    assert ayat.app is not primary.app
    assert "/api/meta" in ayat.app.openapi()["paths"]
    assert "/api/recommend/photo" in primary.app.openapi()["paths"]

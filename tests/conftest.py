"""External components are opt-in. Explicit opt-in failures must never be skipped."""

import importlib
import json
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]


def pytest_addoption(parser):
    group = parser.getgroup("astana-qa")
    group.addoption("--live-api", action="store_true", help="Enable actual backend HTTP checks")
    group.addoption("--live-backend", action="store_true", help="Import actual backend guards for local security unit checks")
    group.addoption("--base-url", default="http://127.0.0.1:8000", help="Backend base URL")
    group.addoption("--pois", default=None, help="Real POI JSON; enables dataset checks")
    group.addoption("--live-rag", action="store_true", help="Import the actual local RAG modules")
    group.addoption("--live-ui", action="store_true", help="Open actual frontend using optional Playwright")
    group.addoption("--ui-url", default="http://127.0.0.1:5173", help="Frontend URL")


@pytest.fixture(scope="session")
def api_client(pytestconfig):
    if not pytestconfig.getoption("--live-api"):
        pytest.skip("Product backend NOT TESTED: enable --live-api to run")
    base_url = pytestconfig.getoption("--base-url").rstrip("/")
    with httpx.Client(base_url=base_url, timeout=15, follow_redirects=False, trust_env=False) as client:
        try:
            response = client.get("/api/health")
        except httpx.HTTPError as error:
            pytest.fail(f"Explicitly enabled backend unavailable ({type(error).__name__}) at {base_url}")
        assert response.status_code == 200, f"Backend health returned {response.status_code}"
        yield client


@pytest.fixture(scope="session")
def real_pois(pytestconfig):
    configured = pytestconfig.getoption("--pois")
    needs_data = pytestconfig.getoption("--live-api") or pytestconfig.getoption("--live-rag")
    if not configured:
        if needs_data:
            pytest.fail("Real data is required: pass --pois data/processed/pois.json")
        pytest.skip("Real POI dataset NOT TESTED: pass --pois to run")
    path = Path(configured)
    try:
        pois = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        pytest.fail(f"Cannot read explicitly requested POI file: {type(error).__name__}")
    assert isinstance(pois, list) and pois, "Real dataset must be a nonempty JSON list"
    assert all(isinstance(poi, dict) for poi in pois), "Every POI must be an object"
    assert not any(str(poi.get("id", "")).startswith("test:") for poi in pois), "Synthetic QA IDs cannot validate the real product"
    assert not any(poi.get("source") == "test_fixture" for poi in pois), "Use actual collected POIs, not fixtures"
    return pois


@pytest.fixture(scope="session")
def backend_guards(pytestconfig):
    if not pytestconfig.getoption("--live-backend"):
        pytest.skip("Actual backend guards NOT TESTED: enable --live-backend to run")
    try:
        module = importlib.import_module("backend.app.guards")
    except ImportError as error:
        pytest.fail(f"Explicitly enabled backend guards cannot import: {error}")
    assert callable(getattr(module, "mask_pii", None)), "Planned backend guards must expose mask_pii(query)"
    return module


@pytest.fixture(scope="session")
def rag_modules(pytestconfig, real_pois):
    if not pytestconfig.getoption("--live-rag"):
        pytest.skip("Actual RAG NOT TESTED: enable --live-rag to run")
    try:
        return {name: importlib.import_module(f"rag.{name}") for name in ("retriever", "geo", "hours")}
    except ImportError as error:
        pytest.fail(f"Explicitly enabled RAG cannot import its implementation: {error}")


@pytest.fixture(scope="session")
def synthetic_pois():
    return json.loads((ROOT / "tests/fixtures/pois_sample.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def synthetic_response():
    return json.loads((ROOT / "tests/fixtures/response_walk.json").read_text(encoding="utf-8"))


@pytest.fixture
def ui_page(pytestconfig):
    if not pytestconfig.getoption("--live-ui"):
        pytest.skip("Frontend NOT TESTED: enable --live-ui and install Playwright")
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        pytest.fail("For requested UI checks install playwright and run: python -m playwright install chromium")
    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(headless=True)
        except Exception as error:
            pytest.fail(f"Cannot launch requested browser ({type(error).__name__}); install Chromium for Playwright")
        context = browser.new_context(viewport={"width": 1280, "height": 800}, locale="ru-RU")
        page = context.new_page()
        page.set_default_timeout(8000)
        yield page
        context.close()
        browser.close()

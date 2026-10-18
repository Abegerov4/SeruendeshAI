"""Actual UI rendering checks. Only the final test uses the actual backend too."""

import copy
import json
import re

import pytest

pytestmark = pytest.mark.live_ui


def serve_fixture(page, response, status=200, captured=None):
    def handle(route):
        if captured is not None:
            captured.append(route.request.post_data_json)
        route.fulfill(status=status, content_type="application/json", body=json.dumps(response, ensure_ascii=False))
    page.route("**/api/recommend", handle)


def open_and_submit(page, config, query="Хочу погулять рядом"):
    page.goto(config.getoption("--ui-url"), wait_until="domcontentloaded")
    page.get_by_test_id("query-input").fill(query)
    page.get_by_test_id("submit-query").click()


def test_ui_shows_recommendation_context_and_unknown_hours(ui_page, pytestconfig, synthetic_response):
    from playwright.sync_api import expect

    serve_fixture(ui_page, synthetic_response)
    open_and_submit(ui_page, pytestconfig)
    card = ui_page.get_by_test_id("recommendation-card").first
    expect(card).to_be_visible()
    expect(card).to_contain_text("QA TEST парк")
    expect(card.get_by_test_id("open-status")).to_contain_text(re.compile("неизвест|unknown|белгісіз", re.I))
    expect(card.get_by_test_id("source-label")).to_be_visible()
    expect(ui_page.get_by_test_id("used-context")).to_be_visible()
    expect(ui_page.get_by_test_id("map")).to_be_visible()


def test_ui_displays_actionable_server_error(ui_page, pytestconfig):
    from playwright.sync_api import expect

    serve_fixture(ui_page, {"detail": "Synthetic service unavailable"}, status=503)
    open_and_submit(ui_page, pytestconfig)
    expect(ui_page.get_by_test_id("error-message")).to_be_visible()
    expect(ui_page.get_by_test_id("submit-query")).to_be_enabled()


def test_ui_explains_empty_response(ui_page, pytestconfig, synthetic_response):
    from playwright.sync_api import expect

    body = copy.deepcopy(synthetic_response)
    body["recommendations"] = []
    body["notes"] = ["Укажите ориентир или приблизительную локацию."]
    serve_fixture(ui_page, body)
    open_and_submit(ui_page, pytestconfig)
    expect(ui_page.get_by_test_id("empty-state")).to_be_visible()
    expect(ui_page.get_by_test_id("recommendation-card")).to_have_count(0)


def test_ui_renders_model_text_without_executing_html(ui_page, pytestconfig, synthetic_response):
    from playwright.sync_api import expect

    body = copy.deepcopy(synthetic_response)
    body["recommendations"][0]["why"] = '<img src=x onerror="window.__qaXss=1">'
    serve_fixture(ui_page, body)
    open_and_submit(ui_page, pytestconfig)
    expect(ui_page.get_by_test_id("recommendation-card").first).to_be_visible()
    assert ui_page.evaluate("window.__qaXss") is None
    assert ui_page.get_by_test_id("recommendation-card").locator("img[onerror]").count() == 0


def test_ui_rounds_gps_before_network_and_does_not_persist_it(ui_page, pytestconfig, synthetic_response):
    from playwright.sync_api import expect

    captured = []
    ui_page.add_init_script("""Object.defineProperty(navigator, 'geolocation', {value: {
      getCurrentPosition(success) { window.__qaGeoCalls = (window.__qaGeoCalls || 0) + 1;
        success({coords:{latitude:51.12845678,longitude:71.43056789,accuracy:1},timestamp:Date.now()}); },
      watchPosition(success) { this.getCurrentPosition(success); return 1; },
      clearWatch() {}
    }});""")
    serve_fixture(ui_page, synthetic_response, captured=captured)
    ui_page.goto(pytestconfig.getoption("--ui-url"), wait_until="domcontentloaded")
    assert ui_page.evaluate("window.__qaGeoCalls || 0") == 0, "GPS requires an explicit user click"
    ui_page.get_by_test_id("geolocation-button").click()
    ui_page.get_by_test_id("query-input").fill("Хочу парк рядом")
    ui_page.get_by_test_id("submit-query").click()
    expect(ui_page.get_by_test_id("recommendation-card").first).to_be_visible()
    assert captured and captured[-1].get("location") == {"lat": 51.128, "lon": 71.431}
    stored = ui_page.evaluate("JSON.stringify({local:{...localStorage},session:{...sessionStorage}})")
    for value in ("51.12845678", "71.43056789", "51.128", "71.431"):
        assert value not in stored, "Location must not persist in browser storage"


def test_mobile_ui_has_no_horizontal_overflow(ui_page, pytestconfig, synthetic_response):
    from playwright.sync_api import expect

    ui_page.set_viewport_size({"width": 360, "height": 800})
    serve_fixture(ui_page, synthetic_response)
    open_and_submit(ui_page, pytestconfig)
    expect(ui_page.get_by_test_id("recommendation-card").first).to_be_visible()
    assert ui_page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")


def test_real_frontend_backend_path(ui_page, pytestconfig, api_client, real_pois):
    from playwright.sync_api import expect
    from eval.validators import validate_response

    ui_page.goto(pytestconfig.getoption("--ui-url"), wait_until="domcontentloaded")
    ui_page.get_by_test_id("query-input").fill("Я возле Mega Silk Way, хочу погулять 30–60 минут")
    with ui_page.expect_response(lambda response: "/api/recommend" in response.url and response.request.method == "POST") as pending:
        ui_page.get_by_test_id("submit-query").click()
    response = pending.value
    assert response.status == 200
    request = response.request.post_data_json
    errors = validate_response(response.json(), request, real_pois, {"outcome": "recommendations"})
    assert not errors, "\n".join(errors)
    expect(ui_page.get_by_test_id("recommendation-card").first).to_be_visible()

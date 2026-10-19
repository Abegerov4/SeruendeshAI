import json
from pathlib import Path

from bot.format import format_response

EXAMPLES = Path(__file__).resolve().parents[2] / "docs" / "api" / "examples"


def test_formats_a_real_api_answer():
    resp = json.loads((EXAMPLES / "walk.json").read_text())
    text = format_response(resp)
    assert resp["recommendations"][0]["name"] in text and "2gis.kz" in text and "Учёл:" in text


def test_escapes_html_and_handles_empty_answer():
    resp = {"recommendations": [], "notes": ["<b>нет</b> мест"], "used_context": {}, "disclaimer": "ИИ"}
    text = format_response(resp)
    assert "&lt;b&gt;нет&lt;/b&gt;" in text and "локация не указана" in text


def test_labels_follow_the_answer_language_and_routes_start_at_the_origin():
    resp = json.loads((EXAMPLES / "walk.json").read_text())
    resp["lang"] = "en"
    resp["used_context"]["location"] = {"lat": 51.128, "lon": 71.43, "label": "Baiterek"}
    text = format_response(resp)
    assert "Why:" in text and "Took into account:" in text and "directions/points/71.43%2C51.128%7C" in text


def test_every_real_place_gets_a_route_and_a_pin_button():
    from bot.format import pins, place_buttons
    resp = json.loads((EXAMPLES / "walk.json").read_text())
    rows, saved = place_buttons(resp), pins(resp)
    real = [r for r in resp["recommendations"] if r.get("source") != "generated"]
    assert len(rows) == len(real) == len(saved)
    assert rows[0][0]["url"].startswith("https://2gis.kz/") and rows[0][1]["callback"] == "pin:0"
    assert saved[0]["name"] == real[0]["name"] and {"lat", "lon"} <= saved[0].keys()

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

"""Export the API contract for the frontend: docs/api/openapi.json + real example responses.

    cd backend && uv run python ../scripts/export_contract.py [--no-llm]
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
if "--no-llm" in sys.argv:
    os.environ["LLM_ENABLED"] = "false"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

EXAMPLES = {
    "walk": {"query": "Я сейчас возле Mega Silk Way, хочу прогуляться 30–60 минут — что посоветуете?",
             "lang": "ru", "now": "2026-10-18T15:00:00+05:00", "weather": {"temperature_c": 9, "feels_like_c": 6, "wind_ms": 5}},
    "child": {"query": "Еду с ребёнком — где рядом есть детские площадки или музей с интерактивами?",
              "lang": "ru", "location": {"lat": 51.13, "lon": 71.41}, "with_child": True,
              "now": "2026-10-18T12:00:00+05:00", "weather": {"temperature_c": 9, "feels_like_c": 6, "wind_ms": 5}},
    "tourist": {"query": "Я - турист, у меня 2 часа перед вылетом: что можно посмотреть поблизости?",
                "lang": "ru", "location": {"lat": 51.128, "lon": 71.43}, "tourist": True,
                "now": "2026-10-18T14:00:00+05:00", "weather": {"temperature_c": 9, "feels_like_c": 6, "wind_ms": 5}},
    "kazakh": {"query": "Бәйтеректің жанындамын, бір сағат серуендегім келеді", "lang": "kk",
               "now": "2026-10-18T16:00:00+05:00", "weather": {"temperature_c": 9, "feels_like_c": 6, "wind_ms": 5}},
    "night": {"query": "Ищу необычную ночную активность (последние пару часов).", "lang": "ru",
              "location": {"lat": 51.128, "lon": 71.43}, "now": "2026-10-18T23:00:00+05:00",
              "weather": {"temperature_c": 2, "feels_like_c": -2, "wind_ms": 4}},
}

out = ROOT / "docs" / "api"
(out / "examples").mkdir(parents=True, exist_ok=True)
(out / "openapi.json").write_text(json.dumps(app.openapi(), ensure_ascii=False, indent=1))
with TestClient(app) as c:
    for name, body in EXAMPLES.items():
        r = c.post("/api/recommend", json=body)
        r.raise_for_status()
        (out / "examples" / f"{name}.request.json").write_text(json.dumps(body, ensure_ascii=False, indent=1))
        (out / "examples" / f"{name}.json").write_text(json.dumps(r.json(), ensure_ascii=False, indent=1))
        print(name, r.json()["llm"])
    (out / "examples" / "meta.json").write_text(json.dumps(c.get("/api/meta").json(), ensure_ascii=False, indent=1))
print("exported to", out)

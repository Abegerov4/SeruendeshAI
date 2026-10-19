"""Интеграция backend + настоящий rag/ (ветка data-rag).

Основные тесты идут на mock-фикстуре (conftest ставит MOCK_RAG=1 до импорта), поэтому реальный rag/
проверяем в отдельном процессе: BM25-режим, без LLM и без сети.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from backend.app import llm
from backend.app.pipeline import recommend
from backend.app.schemas import RecommendRequest

ROOT = Path(__file__).resolve().parents[2]

SCRIPT = r"""
import json
from backend.app import rag_adapter as rag
from backend.app.pipeline import recommend
from backend.app.schemas import RecommendRequest
out = {"backend": rag.backend_name(), "pois": len(rag.all_pois())}
out["landmark_declined"] = rag.resolve_landmark("я сейчас возле Байтерека", allow_network=False)
r = recommend(RecommendRequest(query="хочу кофе возле Хан Шатыра", now="2026-10-18T15:00:00+05:00"))
ids = {p["id"] for p in rag.all_pois()}
out["recs"] = [x.poi_id for x in r.recommendations]
out["all_ids_valid"] = all(x.poi_id in ids for x in r.recommendations)
out["categories"] = [x.category for x in r.recommendations]
out["loc"] = r.used_context.location_label
print(json.dumps(out, ensure_ascii=False))
"""


@pytest.mark.skipif(not (ROOT / "rag" / "retriever.py").exists(), reason="rag/ ещё не смержен")
def test_backend_works_with_real_rag_bm25():
    env = {**os.environ, "MOCK_RAG": "0", "RAG_SEARCH_MODE": "bm25", "OPENAI_API_KEY": "", "LLM_API_KEY": "",
           "openai_api_key": "", "LANGFUSE_PUBLIC_KEY": "", "LANGFUSE_SECRET_KEY": ""}
    proc = subprocess.run([sys.executable, "-c", SCRIPT], cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr[-2000:]
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    assert out["backend"] == "real" and out["pois"] > 300
    assert out["landmark_declined"] and "Байтерек" in out["landmark_declined"]["label"]
    assert out["recs"] and out["all_ids_valid"]
    assert set(out["categories"]) & {"cafe", "restaurant", "coworking"}
    assert "Хан Шатыр" in (out["loc"] or "")


def test_llm_saying_nothing_fits_is_respected(monkeypatch):
    monkeypatch.setattr(llm, "chat_json", lambda *a, **k: (
        {"recommendations": [], "notes": ["Рядом нет детских площадок и музеев."]}
        if k.get("role") == "decision" else None))
    monkeypatch.setattr(llm, "is_enabled", lambda: True)
    r = recommend(RecommendRequest(query="с ребёнком площадка", location={"lat": 51.0899, "lon": 71.4110},
                                   now="2026-10-18T15:00:00+05:00"))
    assert r.recommendations == []
    assert r.notes and any("подбор не сформирован" in n for n in r.notes)
    assert not any("Рядом нет" in n for n in r.notes), "Model refusal is not evidence that the city has no such places"

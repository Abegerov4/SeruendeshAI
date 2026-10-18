"""Necessary localization checks; these do not grade RU/KK/EN prose quality.

Generated helper text for a distinct requested language must not simply reuse
the Russian fallback. Venue names and source descriptions are left untranslated
and are deliberately excluded from the comparison.
"""
from copy import deepcopy

import pytest


@pytest.mark.parametrize("lang", ["en", "kk"])
@pytest.mark.parametrize("scenario", ["clarification", "recommendation"])
def test_requested_language_has_distinct_generated_fallback(qa_backend, lang, scenario):
    # A single controlled candidate isolates generated helper text from ranking.
    park = next(p for p in qa_backend.pois if p["id"] == "test:park")
    qa_backend.set_pois([park])
    request = {"query": "Хочу парк рядом", "lang": "ru", "now": "2026-10-18T17:00:00+05:00"}
    if scenario == "recommendation":
        request["location"] = {"lat": 51.128, "lon": 71.430}
        request["time_budget_min"] = 60
    russian = qa_backend.client.post("/api/recommend", json=request)
    translated = qa_backend.client.post("/api/recommend", json={**deepcopy(request), "lang": lang})
    assert russian.status_code == translated.status_code == 200
    before, after = russian.json(), translated.json()
    assert after["disclaimer"] != before["disclaimer"], f"lang={lang} reused the Russian disclaimer"
    if scenario == "clarification":
        assert not before["recommendations"] and not after["recommendations"]
        assert after["notes"] and after["notes"] != before["notes"], f"lang={lang} reused Russian clarification"
    else:
        assert before["recommendations"] and after["recommendations"]
        before_actions = {r["poi_id"]: r["what_to_do"] for r in before["recommendations"]}
        after_actions = {r["poi_id"]: r["what_to_do"] for r in after["recommendations"]}
        assert before_actions.keys() == after_actions.keys() == {park["id"]}
        assert after_actions[park["id"]] != before_actions[park["id"]], f"lang={lang} reused Russian generated activities"

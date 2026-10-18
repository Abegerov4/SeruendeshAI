"""Unit/integration expectations against actual RAG functions once implemented."""

from datetime import datetime

import pytest

from eval.validators import haversine_m

pytestmark = pytest.mark.live_rag


@pytest.mark.parametrize("hours,now,status,confidence", [
    (None, "2026-10-18T17:00:00+05:00", "unknown", "none"),
    ("nonsense", "2026-10-18T17:00:00+05:00", "unknown", "none"),
    ("24/7", "2026-10-18T23:30:00+05:00", "open", "high"),
    ("Mo-Su 10:00-22:00", "2026-10-18T10:00:00+05:00", "open", "high"),
    ("Mo-Su 10:00-22:00", "2026-10-18T22:00:00+05:00", "closed", "high"),
    ("Mo-Su 10:00-22:00", "2026-10-18T09:59:00+05:00", "closed", "high"),
    ("Mo-Su 20:00-02:00", "2026-10-18T23:30:00+05:00", "open", "high"),
    ("Mo-Su 20:00-02:00", "2026-10-19T01:00:00+05:00", "open", "high"),
    ("Mo-Su 20:00-02:00", "2026-10-19T02:00:00+05:00", "closed", "high"),
    ("Mo-Fr 10:00-18:00; Sa-Su 11:00-16:00", "2026-10-18T10:30:00+05:00", "closed", "high"),
    ("Mo-Fr 10:00-18:00; Sa-Su 11:00-16:00", "2026-10-19T10:30:00+05:00", "open", "high"),
    ("Mo-Su 10:00-22:00", "2026-10-18T05:00:00+00:00", "open", "high"),
])
def test_opening_hours_boundaries(rag_modules, hours, now, status, confidence):
    actual_status, actual_confidence = rag_modules["hours"].open_status(hours, datetime.fromisoformat(now))
    assert actual_status == status
    assert actual_confidence == confidence


@pytest.mark.parametrize("coords,expected", [
    ((51.128, 71.43, 51.128, 71.43), 0),
    ((51.128, 71.43, 51.129, 71.43), 111),
    ((51.128, 71.43, 51.128, 71.431), 70),
])
def test_distance_matches_independent_literals(rag_modules, coords, expected):
    assert rag_modules["geo"].haversine_m(*coords) == pytest.approx(expected, abs=2)


def test_search_respects_radius_categories_and_real_ids(rag_modules, real_pois):
    results = rag_modules["retriever"].search("тихое кафе кофе", 51.128, 71.43, radius_m=1500, categories=["cafe"], top_k=5)
    assert isinstance(results, list) and len(results) <= 5
    ids = {poi["id"] for poi in real_pois}
    seen = set()
    for poi in results:
        assert poi["id"] in ids and poi["id"] not in seen
        seen.add(poi["id"])
        assert poi["category"] == "cafe"
        assert haversine_m(51.128, 71.43, poi["lat"], poi["lon"]) <= 1501
        assert 0 <= poi["distance_m"] <= 1501
        assert isinstance(poi["score"], (int, float))
    # Empty retrieval does not establish useful search. Relevance is measured separately.


def test_landmark_mega_silk_way_resolves_in_astana(rag_modules):
    location = rag_modules["geo"].resolve_landmark("Mega Silk Way")
    assert location is not None, "The primary demo landmark must resolve"
    assert 51.07 <= location["lat"] <= 51.11
    assert 71.39 <= location["lon"] <= 71.45
    assert location.get("label")

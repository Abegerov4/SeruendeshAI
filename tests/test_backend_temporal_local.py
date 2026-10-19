import pytest
from pathlib import Path

if not (Path(__file__).resolve().parents[1] / "backend/app/intent.py").exists():
    pytest.skip("Earlier primary backend replaced by backend/ in the merged main", allow_module_level=True)
"""B10: arrival and each sequential visit must fit actual opening hours."""
from datetime import datetime


def test_backend_excludes_place_closed_before_arrival(qa_backend):
    from backend.app.intent import Intent
    h = {"id": "late", "name": "Museum", "category": "museum", "lat": 51.13, "lon": 71.43,
         "distance_m": 1000, "opening_hours": "Mo-Su 10:00-18:00"}
    found, closed = qa_backend.pipeline._filter_candidates([h], Intent(time_budget_min=90, mode="walk"), datetime(2026, 10, 19, 17, 55))
    assert found == [] and closed


def test_backend_excludes_visit_that_cannot_finish_before_close(qa_backend):
    from backend.app.intent import Intent
    h = {"id": "late", "name": "Cafe", "category": "cafe", "lat": 51.13, "lon": 71.43,
         "distance_m": 100, "opening_hours": "Mo-Su 10:00-18:00"}
    found, closed = qa_backend.pipeline._filter_candidates([h], Intent(time_budget_min=90, mode="walk"), datetime(2026, 10, 19, 17, 50))
    assert found == [] and closed


def test_backend_route_checks_each_stops_own_arrival(qa_backend):
    from backend.app.routing import build_route
    recs = [{"poi_id": "a", "lat": 51.128, "lon": 71.43, "visit_min": [30, 30], "opening_hours": "Mo-Su 10:00-18:00"},
            {"poi_id": "b", "lat": 51.1281, "lon": 71.43, "visit_min": [30, 30], "opening_hours": "Mo-Su 10:00-18:00"}]
    assert build_route((51.128, 71.43), recs, 90, "walk", now=datetime(2026, 10, 19, 17, 10)) is None


def test_backend_unchecked_hours_are_open_with_low_confidence(qa_backend):
    from backend.app.intent import Intent
    h = {"id": "cafe", "name": "Cafe", "category": "cafe", "lat": 51.13, "lon": 71.43,
         "distance_m": 100, "opening_hours": "Mo-Su 10:00-22:00", "hours_source": "official",
         "hours_source_url": "https://example.org/hours", "check_date": None}
    found, _ = qa_backend.pipeline._filter_candidates([h], Intent(time_budget_min=90, mode="walk"), datetime(2026, 10, 19, 12))
    assert found and found[0]["open_status"] == "open"
    assert found[0]["open_confidence"] == "low"

"""Runtime regressions for source hours emitted by the follow-up extractor."""
import datetime as dt
import importlib.util
from pathlib import Path

import pytest

from ayat_backend.app.hours import opening_status

spec = importlib.util.spec_from_file_location("followup", Path(__file__).with_name("discovery-followup-build.py"))
followup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(followup)


@pytest.mark.parametrize("weekday_start,weekend_start,end,when", [
    ("07:14", "08:14", "01:00", "2026-10-20T00:30:00"),
    ("11:00", "10:00", "02:00", "2026-10-20T00:30:00"),
    ("12:00", "11:00", "01:00", "2026-10-24T00:30:00"),
    ("11:00", "10:00", "02:00", "2026-10-19T00:30:00"),
])
def test_source_overnight_tail_remains_open_in_runtime(weekday_start, weekend_start, end, when):
    schedule = {day: {"working_hours": [{"from": weekend_start if day in ("Sat", "Sun") else weekday_start,
                                        "to": end}]} for day in followup.DAYS}
    value = followup.schedule_value(schedule)
    status = opening_status({"opening_hours": value}, dt.datetime.fromisoformat(when), 10, "ru", None)
    assert status["status"] == "open", (value, status)


def test_source_closed_gap_stays_closed_after_overnight_tail():
    schedule = {day: {"working_hours": [{"from": "10:00" if day == "Sat" else "11:00", "to": "02:00"}]}
                for day in followup.DAYS}
    value = followup.schedule_value(schedule)
    assert opening_status({"opening_hours": value}, dt.datetime(2026, 10, 20, 3, 0), 10, "ru", None)["status"] == "closed"


def test_missing_weekday_is_not_inferred_closed():
    assert followup.schedule_value({"Mon": {"working_hours": [{"from": "09:00", "to": "18:00"}]}}) is None


def test_existing_physical_firm_is_found_in_facts_when_identity_uses_wolt():
    record = {"identity": {"source_url": "https://wolt.com/en/kaz/astana/restaurant/ocean-basket"},
              "facts": [{"source": {"url": "https://2gis.kz/astana/firm/70000001028263064/tab/info"}}],
              "prices": [{"source": {"identity_url": "https://2gis.kz/astana/firm/70000001028263064"}}],
              "menu_items": []}
    assert hasattr(followup, "source_firm_ids"), "Physical-branch duplicate check must inspect accepted evidence URLs"
    assert followup.source_firm_ids(record) == {"70000001028263064"}

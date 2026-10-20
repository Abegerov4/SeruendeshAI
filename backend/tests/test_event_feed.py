"""The public event feed reads real snapshots without recommendation POI restrictions."""
import json
from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient


def event(event_id="event-1", **fields):
    return {
        "id": event_id, "title": "Вечер музыки", "venue": "Концертный зал",
        "address": "проспект Республики, 1", "start": "2026-10-21T19:00:00+05:00", "end": None,
        "sessions": [], "source": "ticketon", "url": f"https://ticketon.kz/event/{event_id}",
        "category": "concerts", "currency": "KZT", "price_from": "3000.00",
        "published_at": None, "first_seen_at": "2026-10-18T10:00:00+05:00",
        "fetched_at": "2026-10-20T17:00:00+05:00", **fields,
    }


@pytest.fixture
def feed(tmp_path, monkeypatch):
    from app import event_feed, paths
    from app.main import RT, app

    path = tmp_path / "events.jsonl"
    monkeypatch.setattr(paths, "EVENTS_FILE", path)
    monkeypatch.setenv("DATA_SNAPSHOT_MODE", "legacy")
    monkeypatch.setitem(RT, "rt", None)
    monkeypatch.setattr(event_feed, "_now", lambda: datetime.fromisoformat("2026-10-20T18:00:00+05:00"))
    client = TestClient(app)

    def load(rows):
        path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows), encoding="utf-8")
        return client

    return load


def ids(response):
    assert response.status_code == 200, response.text
    return [item["id"] for item in response.json()["items"]]


def test_events_endpoint_is_registered_and_reads_the_snapshot(tmp_path, monkeypatch):
    from app import paths
    from app.main import RT, app

    path = tmp_path / "events.jsonl"
    path.write_text(json.dumps({
        "id": "unlinked-event", "title": "Афиша без привязки к POI", "venue": "Новый зал",
        "start": "2099-11-01T19:00:00+05:00", "source": "ticketon",
        "url": "https://ticketon.kz/event/unlinked", "price_from": None,
    }), encoding="utf-8")
    monkeypatch.setattr(paths, "EVENTS_FILE", path)
    monkeypatch.setenv("DATA_SNAPSHOT_MODE", "legacy")
    monkeypatch.setitem(RT, "rt", None)
    response = TestClient(app).get("/api/events")

    assert response.status_code == 200, response.text
    assert [item["id"] for item in response.json()["items"]] == ["unlinked-event"]


def test_feed_contract_preserves_source_metadata_and_numeric_price(feed):
    client = feed([event(description="Живой звук", image_url="https://example.test/poster.jpg",
                         published_at="2026-10-19T09:00:00+05:00")])
    response = client.get("/api/events")
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"items", "total", "offset", "limit", "today", "categories", "months", "updated_at"}
    assert body["total"] == 1 and body["offset"] == 0 and body["limit"] == 20
    assert body["today"] == "2026-10-20"
    assert body["updated_at"] == "2026-10-20T17:00:00+05:00"
    assert body["categories"] == [{"value": "concerts", "label": "Концерты"}]
    assert body["months"] == []
    assert body["items"] == [{
        "id": "event-1", "title": "Вечер музыки", "description": "Живой звук",
        "venue": "Концертный зал", "address": "проспект Республики, 1",
        "start": "2026-10-21T19:00:00+05:00", "end": None, "sessions": [],
        "schedule_kind": "continuous",
        "price_from": 3000, "currency": "KZT", "category": "concerts", "category_label": "Концерты",
        "image_url": "https://example.test/poster.jpg", "announced_at": "2026-10-19T09:00:00+05:00",
        "first_seen_at": "2026-10-18T10:00:00+05:00",
        "sources": [{"name": "ticketon", "url": "https://ticketon.kz/event/event-1"}], "is_archived": False,
    }]


def test_announcement_order_never_uses_event_dates_or_refresh_timestamps(feed):
    rows = [event("new", title="Новый анонс", start="2027-12-01", published_at="2026-10-19T10:00:00+05:00"),
            event("old", title="Старый анонс", start="2026-10-21", published_at="2026-10-10T10:00:00+05:00"),
            event("seen", title="Новая находка", first_seen_at="2026-10-20T10:00:00+05:00"),
            event("unknown", title="Нет даты анонса", first_seen_at=None, fetched_at="2026-10-20T17:59:00+05:00")]
    client = feed(rows)
    assert ids(client.get("/api/events")) == ["seen", "new", "old", "unknown"]
    rows[1]["fetched_at"] = "2026-10-20T23:59:00+05:00"
    assert ids(feed(rows).get("/api/events")) == ["seen", "new", "old", "unknown"]


def test_archive_uses_local_end_times_and_safe_day_end_fallback(feed):
    client = feed([
        event("ended", start="2026-10-20T15:00:00+05:00", end="2026-10-20T17:59:00+05:00"),
        event("today", start="2026-10-20", end="2026-10-20"),
        event("unknown-duration", start="2026-10-20T10:00:00+05:00"),
        event("yesterday", start="2026-10-19T19:00:00+05:00"),
        event("tomorrow"),
    ])
    assert set(ids(client.get("/api/events"))) == {"today", "unknown-duration", "tomorrow"}
    response = client.get("/api/events?view=archive")
    assert ids(response) == ["ended", "yesterday"]
    assert all(row["is_archived"] for row in response.json()["items"])
    assert response.json()["months"] == ["2026-10"]


def test_today_and_naive_dates_follow_almaty_not_utc(feed, monkeypatch):
    from app import event_feed

    client = feed([event("local", start="2026-10-21", end="2026-10-21"),
                   event("naive", start="2026-10-20T22:00:00", end="2026-10-20T23:30:00")])
    monkeypatch.setattr(event_feed, "_now", lambda: datetime.fromisoformat("2026-10-20T19:01:00+00:00"))
    assert ids(client.get("/api/events")) == ["local"]
    assert client.get("/api/events").json()["today"] == "2026-10-21"
    assert ids(client.get("/api/events?view=archive")) == ["naive"]


def test_discrete_sessions_do_not_match_days_between_performances(feed):
    client = feed([event("series", start="2026-10-21T19:00:00+05:00", end="2026-10-25T20:30:00+05:00",
                         sessions=["2026-10-21T19:00:00+05:00", "2026-10-25T19:00:00+05:00"])])
    assert ids(client.get("/api/events?date_from=2026-10-22&date_to=2026-10-24")) == []
    assert ids(client.get("/api/events?date_from=2026-10-25&date_to=2026-10-25")) == ["series"]


def test_final_session_end_moves_series_into_archive(feed, monkeypatch):
    from app import event_feed

    client = feed([event("series", start="2026-10-19T19:00:00+05:00", end="2026-10-21T20:30:00+05:00",
                         sessions=["2026-10-19T19:00:00+05:00", "2026-10-21T19:00:00+05:00"])])
    monkeypatch.setattr(event_feed, "_now", lambda: datetime.fromisoformat("2026-10-21T20:31:00+05:00"))
    assert ids(client.get("/api/events")) == []
    assert ids(client.get("/api/events?view=archive")) == ["series"]


def test_continuous_event_overlaps_inclusive_date_boundaries(feed):
    client = feed([event("exhibition", start="2026-10-01", end="2026-11-03", sessions=[])])
    assert ids(client.get("/api/events?date_from=2026-11-03&date_to=2026-11-03")) == ["exhibition"]
    assert ids(client.get("/api/events?date_from=2026-11-04")) == []
    assert ids(client.get("/api/events?date_to=2026-09-30")) == []


def test_collector_single_start_session_preserves_multiday_exhibition(feed):
    client = feed([event("exhibition", start="2026-11-07T10:00:00+05:00", end="2026-11-15T20:00:00+05:00",
                         sessions=["2026-11-07T10:00:00+05:00"], schedule_kind="continuous")])
    assert ids(client.get("/api/events?date_from=2026-11-12&date_to=2026-11-12")) == ["exhibition"]
    assert client.get("/api/events/exhibition").json()["schedule_kind"] == "continuous"


def test_explicit_single_session_does_not_expand_to_series_envelope(feed, monkeypatch):
    from app import event_feed

    client = feed([event("performance", start="2026-10-22T19:00:00+05:00", end="2026-12-31T20:30:00+05:00",
                         sessions=["2026-10-22T19:00:00+05:00"], schedule_kind="sessions")])
    assert ids(client.get("/api/events?date_from=2026-10-23&date_to=2026-10-23")) == []
    assert client.get("/api/events/performance").json()["schedule_kind"] == "sessions"
    monkeypatch.setattr(event_feed, "_now", lambda: datetime.fromisoformat("2026-10-23T18:00:00+05:00"))
    assert ids(client.get("/api/events")) == []
    assert ids(client.get("/api/events?view=archive")) == ["performance"]


@pytest.mark.parametrize("sessions,want", [
    ([], "continuous"), (["2026-10-21T19:00:00+05:00"], "continuous"),
    (["2026-10-22T19:00:00+05:00"], "sessions"),
    (["2026-10-21T19:00:00+05:00", "2026-10-25T19:00:00+05:00"], "sessions"),
])
def test_legacy_schedule_kind_infers_discrete_occurrences(feed, sessions, want):
    client = feed([event(sessions=sessions)])
    assert client.get("/api/events/event-1").json()["schedule_kind"] == want


def test_explicit_continuous_schedule_overrides_discrete_legacy_inference(feed):
    client = feed([event("exhibition", start="2026-10-21", end="2026-10-25",
                         sessions=["2026-10-21", "2026-10-25"], schedule_kind="continuous")])
    assert ids(client.get("/api/events?date_from=2026-10-23&date_to=2026-10-23")) == ["exhibition"]


def test_different_schedule_kinds_are_not_merged_across_sources(feed):
    client = feed([event("continuous", start="2026-10-22", end="2026-12-31", sessions=["2026-10-22"],
                         schedule_kind="continuous"),
                   event("session", source="sxodim", start="2026-10-22", end="2026-12-31", sessions=["2026-10-22"],
                         schedule_kind="sessions")])
    assert set(ids(client.get("/api/events"))) == {"continuous", "session"}


@pytest.mark.parametrize("sessions", ["not-a-list", {"start": "2026-10-21"}, 42, [None, {}, 42]])
def test_malformed_sessions_do_not_break_other_valid_events(feed, sessions):
    client = feed([event("valid"), event("malformed", sessions=sessions)])
    assert set(ids(client.get("/api/events"))) == {"valid", "malformed"}


@pytest.mark.parametrize("source", [None, ["ticketon"], {"name": "ticketon"}, 42])
def test_malformed_sources_are_excluded_without_breaking_the_feed(feed, source):
    client = feed([event("valid"), event("malformed", source=source)])
    assert ids(client.get("/api/events")) == ["valid"]


def test_explicit_source_city_excludes_out_of_city_events(feed):
    client = feed([event("astana", source_city="Астана"), event("outside", source_city="Алматы")])
    assert ids(client.get("/api/events")) == ["astana"]


@pytest.mark.parametrize("unknown", [None, "", "по запросу", "NaN", "Infinity", -1, True])
def test_unknown_prices_are_neither_free_nor_paid(feed, unknown):
    client = feed([event("unknown", price_from=unknown), event("free", title="Бесплатный концерт", price_from="0.00"),
                   event("paid", title="Платный концерт", price_from="1500")])
    assert ids(client.get("/api/events?price=free")) == ["free"]
    assert ids(client.get("/api/events?price=paid")) == ["paid"]
    unknown_item = client.get("/api/events/unknown").json()
    assert unknown_item["price_from"] is None


def test_search_category_source_and_pagination_combine(feed):
    client = feed([event("one", description="Джазовый вечер", source="sxodim", category="concerts"),
                   event("two", description="Джаз для всей семьи", source="sxodim", category="children"),
                   event("three", description="Джазовый вечер", source="ticketon", category="concerts"),
                   event("four", title="Джаз квартет", source="sxodim", category="concerts")])
    response = client.get("/api/events?q=ДЖАЗ&category=concerts&source=sxodim&offset=1&limit=1")
    assert response.status_code == 200
    assert response.json()["total"] == 2
    assert response.json()["offset"] == 1 and response.json()["limit"] == 1
    assert len(response.json()["items"]) == 1
    assert ids(client.get("/api/events?offset=100")) == []


def test_cross_source_duplicates_keep_links_and_detail_aliases(feed):
    client = feed([event("ticket", published_at="2026-10-18T09:00:00+05:00"),
                   event("sx", source="sxodim", url="https://sxodim.com/astana/event/music",
                         title=" ВЕЧЕР  МУЗЫКИ ", description="Живой концерт",
                         published_at="2026-10-19T09:00:00+05:00", first_seen_at="2026-10-19T10:00:00+05:00")])
    response = client.get("/api/events?source=sxodim")
    assert ids(response) == ["ticket"]
    row = response.json()["items"][0]
    assert row["description"] == "Живой концерт"
    assert row["announced_at"] == "2026-10-18T09:00:00+05:00"
    assert row["first_seen_at"] == "2026-10-18T10:00:00+05:00"
    assert row["sources"] == [{"name": "ticketon", "url": "https://ticketon.kz/event/ticket"},
                              {"name": "sxodim", "url": "https://sxodim.com/astana/event/music"}]
    assert client.get("/api/events/sx").json() == row
    assert client.get("/api/events/missing").status_code == 404


def test_duplicate_safety_keeps_different_occurrences_addresses_and_same_source_rows(feed):
    client = feed([event("one"), event("same-source"),
                   event("another-date", source="sxodim", start="2026-10-22T19:00:00+05:00"),
                   event("another-address", source="sxodim", address="Улица Достык, 10"),
                   event("no-venue", source="sxodim", venue=None)])
    assert len(ids(client.get("/api/events"))) == 5


def test_archive_months_filter_uses_occurrences_not_announcement_dates(feed):
    client = feed([event("september", start="2026-09-30", end="2026-09-30", published_at="2026-08-01"),
                   event("october", start="2026-10-01", end="2026-10-19", published_at="2026-09-01"),
                   event("series", start="2026-07-01", end="2026-09-15",
                         sessions=["2026-07-01", "2026-09-15"])])
    response = client.get("/api/events?view=archive&month=2026-09")
    assert ids(response) == ["september", "series"]
    assert response.json()["months"] == ["2026-10", "2026-09", "2026-07"]


def test_month_and_date_filters_must_match_the_same_occurrence(feed):
    client = feed([event("series", start="2026-07-01", end="2026-09-15",
                         sessions=["2026-07-01", "2026-09-15"])])
    assert ids(client.get("/api/events?view=archive&month=2026-07&date_from=2026-09-01")) == []


def test_ambiguous_duplicate_candidates_are_not_arbitrarily_merged(feed):
    client = feed([event("one"), event("two"), event("sx", source="sxodim")])
    assert len(ids(client.get("/api/events"))) == 3


@pytest.mark.parametrize("query", [
    "view=unknown", "source=unknown", "price=unknown", "offset=-1", "limit=0", "limit=101",
    "date_from=2026-02-30", "date_to=nope", "date_from=20261020",
    "date_from=2026-10-22&date_to=2026-10-21", "month=2026-13", "month=2026-1", "month=nope",
])
def test_invalid_filters_return_422(feed, query):
    assert feed([]).get(f"/api/events?{query}").status_code == 422


def test_outside_astana_rows_are_excluded_without_changing_snapshot(feed):
    from app import paths

    client = feed([event("astana"), event("outside", title="Вечер музыки в Алматы")])
    before = paths.EVENTS_FILE.read_bytes()
    assert ids(client.get("/api/events")) == ["astana"]
    assert client.get("/api/events/outside").status_code == 404
    assert paths.EVENTS_FILE.read_bytes() == before


@pytest.mark.parametrize("mode", ["legacy", "canonical"])
def test_feed_reads_fresh_dedicated_file_independently_of_runtime_bundle(feed, tmp_path, monkeypatch, mode):
    from app.main import RT

    client = feed([event("fresh", poi_id=None)])
    bundle = tmp_path / "bound"
    bundle.mkdir()
    (bundle / "events.jsonl").write_text(json.dumps(event("bound", poi_id=None)))
    before = (bundle / "events.jsonl").read_bytes()
    monkeypatch.setenv("DATA_SNAPSHOT_MODE", mode)
    monkeypatch.setitem(RT, "rt", SimpleNamespace(store=SimpleNamespace(events=[], manifest={"snapshot_path": str(bundle)})))
    assert ids(client.get("/api/events")) == ["fresh"]
    feed([event("refreshed", poi_id=None)])
    assert ids(client.get("/api/events")) == ["refreshed"]
    assert client.get("/api/events/refreshed").json()["id"] == "refreshed"
    assert client.get("/api/events/fresh").status_code == 404
    assert (bundle / "events.jsonl").read_bytes() == before


def test_canonical_feed_reads_dedicated_file_before_runtime_startup(feed, tmp_path, monkeypatch):
    from data.snapshot import publish_snapshot

    client = feed([event("fresh")])
    publish_snapshot(tmp_path, {
        "pois.json": [{"id": "venue", "category": "other"}], "pois_leisure.json": [],
        "source_manifest.json": {}, "stats.json": {}, "events.jsonl": json.dumps(event("published", poi_id=None)),
    })
    monkeypatch.setenv("DATA_SNAPSHOT_MODE", "canonical")
    assert ids(client.get("/api/events")) == ["fresh"]


def test_empty_snapshot_returns_stable_empty_metadata(feed):
    body = feed([]).get("/api/events").json()
    assert body == {"items": [], "total": 0, "offset": 0, "limit": 20, "today": "2026-10-20",
                    "categories": [], "months": [], "updated_at": None}

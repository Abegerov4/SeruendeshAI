"""Collector contracts: archive safety, source identity and honest source metadata."""
import json
import urllib.error

import pytest

from pipeline import events


@pytest.fixture
def snapshot(tmp_path, monkeypatch):
    pois = tmp_path / "pois.jsonl"
    output = tmp_path / "events.jsonl"
    pois.write_text("")
    monkeypatch.setattr(events, "POIS_FILE", pois)
    monkeypatch.setattr(events, "EVENTS_FILE", output)
    monkeypatch.setattr(events, "collect_ticketon", lambda: [])
    monkeypatch.setattr(events, "collect_sxodim", lambda: [])
    return output


def event(**changes):
    row = {"source": "sxodim", "url": "https://sxodim.com/astana/event/concert",
           "title": "Astana concert", "venue": "New venue", "address": None,
           "lat": None, "lon": None, "start": "2026-10-25T18:00:00+05:00",
           "end": None, "sessions": ["2026-10-25T18:00:00+05:00"], "price_from": None}
    row.update(changes)
    return row


def read_rows(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_refresh_retains_ended_archive_and_unlocated_astana_events(snapshot, monkeypatch):
    old = event(id="legacy-id", title="Ended concert", start="2020-01-01", end="2020-01-02",
                url="https://sxodim.com/astana/event/ended", fetched_at="2020-01-01T12:00:00+05:00")
    snapshot.write_text(json.dumps(old) + "\n")
    monkeypatch.setattr(events, "collect_sxodim", lambda: [event()])
    report = events.collect_events()
    rows = read_rows(snapshot)
    assert {row["title"] for row in rows} == {"Ended concert", "Astana concert"}
    assert next(row for row in rows if row["title"] == "Ended concert")["id"] == "legacy-id"
    assert next(row for row in rows if row["title"] == "Astana concert")["lat"] is None
    assert report["retained_events"] == 1


def test_total_source_failure_preserves_snapshot_and_is_reported(snapshot, monkeypatch):
    original = json.dumps(event(id="legacy-id")) + "\n"
    snapshot.write_text(original)

    def failed():
        raise urllib.error.HTTPError("https://example.test", 403, "Forbidden", {}, None)

    monkeypatch.setattr(events, "collect_ticketon", failed)
    monkeypatch.setattr(events, "collect_sxodim", failed)
    report = events.collect_events()
    assert snapshot.read_text() == original
    assert report["status"] == "failed"
    assert report["sources"]["ticketon"]["status"] == "failed"
    assert "403" in report["sources"]["sxodim"]["errors"][0]


def test_upsert_preserves_legacy_id_first_seen_and_prior_rich_metadata(snapshot, monkeypatch):
    original = event(id="legacy-id", title="Old title", fetched_at="2026-10-18T12:00:00+05:00",
                     published_at="2026-10-10T10:00:00+05:00", description="Source description",
                     image_url="https://sxodim.com/concert.jpg")
    snapshot.write_text(json.dumps(original) + "\n")
    monkeypatch.setattr(events, "collect_sxodim", lambda: [event(title="Corrected title")])
    events.collect_events()
    row = read_rows(snapshot)[0]
    assert row["id"] == "legacy-id"
    assert row["first_seen_at"] == "2026-10-18T12:00:00+05:00"
    assert row["title"] == "Corrected title"
    assert row["published_at"] == "2026-10-10T10:00:00+05:00"
    assert row["description"] == "Source description"
    assert row["image_url"] == "https://sxodim.com/concert.jpg"
    monkeypatch.setattr(events, "collect_sxodim", lambda: [event(title="Corrected again")])
    events.collect_events()
    assert read_rows(snapshot)[0]["first_seen_at"] == row["first_seen_at"]


def test_source_identity_does_not_collapse_distinct_source_records(snapshot, monkeypatch):
    monkeypatch.setattr(events, "collect_sxodim", lambda: [event()])
    monkeypatch.setattr(events, "collect_ticketon", lambda: [event(source="ticketon", url="https://ticketon.kz/music/event/tckt2-concert")])
    events.collect_events()
    rows = read_rows(snapshot)
    assert len(rows) == 2
    assert len({row["id"] for row in rows}) == 2
    assert {row["source"] for row in rows} == {"sxodim", "ticketon"}


def test_placeholder_source_point_is_kept_as_evidence_but_not_a_feed_coordinate(snapshot, monkeypatch):
    monkeypatch.setattr(events, "collect_sxodim", lambda: [event(lat=51.129547, lon=71.443112)])
    events.collect_events()
    row = read_rows(snapshot)[0]
    assert row["lat"] is None and row["lon"] is None
    assert row["source_lat"] == 51.129547 and row["source_lon"] == 71.443112
    assert row["match_status"] == "unmatched"


def test_normalizer_keeps_explicit_free_price_and_source_metadata():
    row = events._norm({"@type": ["Thing", "MusicEvent"], "name": "Concert",
                        "datePublished": "2026-10-17T09:00:00+05:00",
                        "description": "<p>A free &amp; open concert.</p>",
                        "image": [{"@type": "ImageObject", "contentUrl": "https://example.test/image.jpg"}],
                        "location": {"address": {"addressLocality": "Астана"}},
                        "offers": {"price": 0, "lowPrice": 900, "priceCurrency": "KZT"}},
                       "sxodim", "https://sxodim.com/astana/event/concert")
    assert row["price_from"] == 0
    assert row["published_at"] == "2026-10-17T09:00:00+05:00"
    assert row["description"] == "A free & open concert."
    assert row["image_url"] == "https://example.test/image.jpg"
    assert row["type"] == "MusicEvent"
    assert row["source_city"] == "Астана"


def test_offer_valid_from_is_not_claimed_as_publication_time():
    row = events._norm({"name": "Concert", "offers": {"validFrom": "2026-10-01", "priceCurrency": "KZT"}},
                       "sxodim", "https://sxodim.com/astana/event/concert")
    assert row["price_from"] is None
    assert row.get("published_at") is None


def test_nested_jsonld_event_and_single_session_are_normalized(monkeypatch):
    payload = {"@context": "https://schema.org", "@graph": [
        {"@type": "ItemList", "itemListElement": [{"@type": "ListItem", "item": {
            "@type": ["Thing", "MusicEvent"], "name": "Nested concert",
            "url": "https://sxodim.com/astana/event/nested",
            "subEvent": {"@type": "Event", "startDate": "2026-10-29T19:00:00+05:00"},
            "location": {"name": "Hall", "address": {"addressLocality": "Астана"}}
        }}]}
    ]}
    html = "<script TYPE='application/ld+json'>" + json.dumps(payload) + "</script>"
    monkeypatch.setattr(events, "_fetch", lambda url: html)
    rows = events.collect_sxodim(pages=1)
    assert len(rows) == 1
    assert rows[0]["title"] == "Nested concert"
    assert rows[0]["sessions"] == ["2026-10-29T19:00:00+05:00"]


def test_listing_failure_is_present_in_refresh_report(tmp_path, monkeypatch):
    def failed_fetch(url, *args):
        raise urllib.error.HTTPError(url, 403, "Forbidden", {}, None)

    pois, output = tmp_path / "pois.jsonl", tmp_path / "events.jsonl"
    pois.write_text("")
    monkeypatch.setattr(events, "POIS_FILE", pois)
    monkeypatch.setattr(events, "EVENTS_FILE", output)
    monkeypatch.setattr(events, "_fetch", failed_fetch)
    report = events.collect_events()
    assert report["status"] == "failed"
    assert report["sources"]["ticketon"]["errors"]
    assert report["sources"]["sxodim"]["errors"]


def test_successful_refresh_backfills_discovery_for_unseen_archive(snapshot, monkeypatch):
    snapshot.write_text(json.dumps(event(id="archive", url="https://sxodim.com/astana/event/archive",
                                         fetched_at="2026-09-01T12:00:00+05:00")) + "\n")
    monkeypatch.setattr(events, "collect_sxodim", lambda: [event()])
    events.collect_events()
    archive = next(row for row in read_rows(snapshot) if row["id"] == "archive")
    assert archive["first_seen_at"] == "2026-09-01T12:00:00+05:00"


def test_one_generic_venue_token_cannot_link_a_different_venue():
    row = events.match_event_venue(event(venue="Өnergy Creative Hub"),
                                  [{"id": "osm:coffee", "name": "Coffee Hub", "lat": 51.16, "lon": 71.41}])
    assert row["match_status"] == "unmatched"
    assert "poi_id" not in row
    assert row["source_venue"] == "Өnergy Creative Hub"


def test_ticketon_page_metadata_fills_missing_jsonld_editorial_fields(monkeypatch):
    monkeypatch.setattr(events, "TICKETON_LISTINGS", ["astana"])
    event_url = "https://ticketon.kz/music/event/tckt2-concert"
    detail = '''<meta property="article:published_time" content="2026-10-01T12:00:00+05:00">
                <meta property="og:image" content="/image.jpg">
                <meta name="description" content="A concert &amp; discussion">
                <script type="application/ld+json">{"@type":"MusicEvent","name":"Concert"}</script>'''
    monkeypatch.setattr(events, "_fetch", lambda url: '/music/event/tckt2-concert' if url.endswith('/astana') else detail)
    row = events.collect_ticketon()[0]
    assert row["url"] == event_url
    assert row["published_at"] == "2026-10-01T12:00:00+05:00"
    assert row["image_url"] == "https://ticketon.kz/image.jpg"
    assert row["description"] == "A concert & discussion"


def test_partial_refresh_reports_failure_and_keeps_other_source_archive(tmp_path, monkeypatch):
    snapshot = tmp_path / "events.jsonl"
    pois = tmp_path / "pois.jsonl"
    pois.write_text("")
    snapshot.write_text(json.dumps(event(source="ticketon", id="ticketon-old", url="https://ticketon.kz/music/event/tckt2-old")) + "\n")

    def source_fetch(url, *args):
        if 'ticketon' in url:
            raise urllib.error.HTTPError(url, 403, "Forbidden", {}, None)
        if 'page=1' in url:
            return '<script type="application/ld+json">{"@type":"Event","name":"New concert","url":"https://sxodim.com/astana/event/new","startDate":"2026-10-28"}</script>'
        raise TimeoutError("source timed out")

    # Use real source adapters against controlled HTTP responses.
    monkeypatch.setattr(events, "POIS_FILE", pois)
    monkeypatch.setattr(events, "EVENTS_FILE", snapshot)
    monkeypatch.setattr(events, "_fetch", source_fetch)
    report = events.collect_events()
    assert report["status"] == "partial"
    assert report["sources"]["ticketon"]["status"] == "failed"
    assert report["sources"]["sxodim"]["status"] == "partial"
    assert {row["title"] for row in read_rows(snapshot)} == {"Astana concert", "New concert"}
    assert next(row for row in read_rows(snapshot) if row["source"] == "ticketon")["id"] == "ticketon-old"


def test_serialization_failure_leaves_previous_archive_intact(snapshot, monkeypatch):
    original = json.dumps(event(id="previous")) + "\n"
    snapshot.write_text(original)
    monkeypatch.setattr(events, "collect_sxodim", lambda: [event(unsafe_value={object()})])
    with pytest.raises(TypeError):
        events.collect_events()
    assert snapshot.read_text() == original
    assert list(snapshot.parent.glob('.events.jsonl.*')) == []


@pytest.mark.parametrize(("source_fields", "kind", "sessions"), [
    ({"startDate": "2026-10-25", "endDate": "2026-10-30"}, "continuous", ["2026-10-25"]),
    ({"startDate": "2026-10-25", "subEvent": {"startDate": "2026-10-25T19:00:00+05:00"}},
     "sessions", ["2026-10-25T19:00:00+05:00"]),
    ({"subEvents": [{"startDate": "2026-10-28T19:00:00+05:00"}]},
     "sessions", ["2026-10-28T19:00:00+05:00"]),
])
def test_schedule_kind_records_actual_source_occurrence_structure(source_fields, kind, sessions):
    row = events._norm({"name": "Concert", **source_fields}, "sxodim", "https://sxodim.com/astana/event/concert")
    assert row["schedule_kind"] == kind
    assert row["sessions"] == sessions


@pytest.mark.parametrize("changes", [
    {"start": None, "end": None, "sessions": []},
    {"start": "not-a-date", "end": "2026-99-99", "sessions": ["broken"]},
    {"start": "2026-10-25", "end": "not-a-date", "sessions": ["2026-10-25"]},
])
def test_incomplete_refresh_preserves_entire_previous_schedule(snapshot, monkeypatch, changes):
    prior = event(id="legacy-id", start="2026-10-20T10:00:00+05:00", end="2026-10-30T20:00:00+05:00",
                  sessions=["2026-10-20T10:00:00+05:00"], schedule_kind="continuous")
    snapshot.write_text(json.dumps(prior) + "\n")
    monkeypatch.setattr(events, "collect_sxodim", lambda: [event(title="Corrected title", schedule_kind="sessions", **changes)])
    report = events.collect_events()
    row = read_rows(snapshot)[0]
    assert row["id"] == "legacy-id"
    assert row["title"] == "Corrected title"
    assert row["start"] == "2026-10-20T10:00:00+05:00"
    assert row["end"] == "2026-10-30T20:00:00+05:00"
    assert row["sessions"] == ["2026-10-20T10:00:00+05:00"]
    assert row["schedule_kind"] == "continuous"
    assert report["degraded_events"] == 1
    assert report["status"] == "partial"
    assert report["sources"]["sxodim"]["status"] == "partial"
    assert report["sources"]["sxodim"]["errors"]


def test_new_record_without_parseable_occurrence_is_rejected(snapshot, monkeypatch):
    monkeypatch.setattr(events, "collect_sxodim", lambda: [event(start="broken", end=None, sessions=[])])
    report = events.collect_events()
    assert report["events"] == 0
    assert report["rejected_events"] == 1
    assert report["sources"]["sxodim"]["status"] == "failed"
    assert report["status"] == "failed"
    assert not snapshot.exists()


def test_explicit_sessions_can_supply_occurrence_without_parent_start(snapshot, monkeypatch):
    monkeypatch.setattr(events, "collect_sxodim", lambda: [event(start=None, end=None,
                        sessions=["2026-10-28T19:00:00+05:00"], schedule_kind="sessions")])
    report = events.collect_events()
    row = read_rows(snapshot)[0]
    assert row["start"] is None and row["end"] is None
    assert row["sessions"] == ["2026-10-28T19:00:00+05:00"]
    assert report["status"] == "ok"


@pytest.mark.parametrize("end", ["2026-10-25", "2026-10-27"])
def test_date_only_end_covers_the_whole_source_day(snapshot, monkeypatch, end):
    monkeypatch.setattr(events, "collect_sxodim", lambda: [event(
        start="2026-10-25T19:00:00+05:00", end=end,
        sessions=["2026-10-25T19:00:00+05:00"], schedule_kind="continuous")])
    report = events.collect_events()
    assert report["status"] == "ok"
    assert report["rejected_events"] == 0
    row = read_rows(snapshot)[0]
    assert row["start"] == "2026-10-25T19:00:00+05:00"
    assert row["end"] == end


SXODIM_TOUR_URL = "https://sxodim.com/astana/event/obzornaya-ekskursiya-po-gorodu-lyubimaya-astana"
# Bounded extracts of the first-party detail HTML checked on 2026-10-20.
SXODIM_TOUR_DETAIL = '''<div class="publication">Дата публикации: 05.06.2024</div>
<script type="application/ld+json">{
  "@context": "http://schema.org", "@type": "Article",
  "mainEntityOfPage": {"@type": "WebPage", "@id": "https://sxodim.com/astana/event/obzornaya-ekskursiya-po-gorodu-lyubimaya-astana"},
  "headline": "Обзорная экскурсия по городу «Любимая Астана»",
  "datePublished": "2024-06-05T15:12:00+05:00",
  "dateModified": "2026-09-25T14:24:47+05:00"
}</script>
<script type="application/ld+json">{
  "@type": "Event", "url": "https://sxodim.com/astana/event/obzornaya-ekskursiya-po-gorodu-lyubimaya-astana",
  "startDate": "2026-09-27", "endDate": "2026-10-25",
  "offers": {"validFrom": "2024-06-05T15:13:14+05:00"},
  "image": ["https://sxodim.com/uploads/posts/2026/09/25/optimized/tour.jpg"]
}</script>'''


def sxodim_listing(*urls):
    return '<script type="application/ld+json">' + json.dumps([
        {"@type": "Event", "name": "Обзорная экскурсия по городу «Любимая Астана»",
         "url": url, "startDate": "2026-10-25"} for url in urls
    ]) + '</script>'


def test_sxodim_detail_supplies_real_publication_once_per_event(monkeypatch):
    calls = []

    def fetch(url, max_age_h=0.25):
        calls.append((url, max_age_h))
        if "/afisha?" in url:
            return sxodim_listing(SXODIM_TOUR_URL, SXODIM_TOUR_URL)
        return SXODIM_TOUR_DETAIL

    monkeypatch.setattr(events, "_fetch", fetch)
    rows = events.collect_sxodim(pages=2)
    assert len(rows) == 1
    assert rows[0]["published_at"] == "2024-06-05T15:12:00+05:00"
    assert [call for call in calls if "/event/" in call[0]] == [(SXODIM_TOUR_URL, 72)]
    assert rows.errors == []


@pytest.mark.parametrize("article_identity", [
    {"mainEntityOfPage": {"@id": SXODIM_TOUR_URL}},
    {"mainEntityOfPage": SXODIM_TOUR_URL},
    {"url": SXODIM_TOUR_URL + "/"},
    {"@id": SXODIM_TOUR_URL + "#article"},
])
def test_sxodim_publication_matches_article_in_graph(monkeypatch, article_identity):
    detail = '<script type="application/ld+json">' + json.dumps({"@graph": [
        {"@type": "Article", "url": "https://sxodim.com/astana/event/unrelated", "datePublished": "2026-10-20"},
        {"@type": ["Thing", "Article"], **article_identity, "datePublished": "2024-06-05T15:12:00+05:00"},
        {"@type": "Event", "url": SXODIM_TOUR_URL, "startDate": "2026-10-25"},
    ]}) + '</script>'
    monkeypatch.setattr(events, "_fetch", lambda url, *args: sxodim_listing(SXODIM_TOUR_URL) if "/afisha?" in url else detail)
    assert events.collect_sxodim(pages=1)[0]["published_at"] == "2024-06-05T15:12:00+05:00"


def test_sxodim_explicit_visible_publication_keeps_day_precision(monkeypatch):
    detail = '<div class="publication">Дата публикации: <span>05.06.2024</span></div>'
    monkeypatch.setattr(events, "_fetch", lambda url, *args: sxodim_listing(SXODIM_TOUR_URL) if "/afisha?" in url else detail)
    assert events.collect_sxodim(pages=1)[0]["published_at"] == "2024-06-05"


def test_sxodim_detail_canonical_must_match_requested_event(monkeypatch):
    detail = '<link rel="canonical" href="https://sxodim.com/astana/event/unrelated">' + SXODIM_TOUR_DETAIL
    monkeypatch.setattr(events, "_fetch", lambda url, *args: sxodim_listing(SXODIM_TOUR_URL) if "/afisha?" in url else detail)
    rows = events.collect_sxodim(pages=1)
    assert rows[0].get("published_at") is None
    assert rows.errors


def test_sxodim_explicit_page_metadata_supplies_publication(monkeypatch):
    detail = '<link rel="canonical" href="' + SXODIM_TOUR_URL + '"><meta property="article:published_time" content="2024-06-05T15:12:00+05:00">'
    monkeypatch.setattr(events, "_fetch", lambda url, *args: sxodim_listing(SXODIM_TOUR_URL) if "/afisha?" in url else detail)
    assert events.collect_sxodim(pages=1)[0]["published_at"] == "2024-06-05T15:12:00+05:00"


@pytest.mark.parametrize("detail", [
    '<script type="application/ld+json">{"@type":"Article","url":"https://sxodim.com/astana/event/unrelated","datePublished":"2026-10-20"}</script>',
    '<script type="application/ld+json">{"@type":"Article","datePublished":"2026-10-20"}</script>',
    '<script type="application/ld+json">{"@type":"Event","startDate":"2026-10-25","offers":{"validFrom":"2026-10-20"},"image":"/uploads/posts/2026/10/20/photo.jpg"}</script>',
    '<script type="application/ld+json">{"@type":"Article","url":"' + SXODIM_TOUR_URL + '","dateModified":"2026-10-20"}</script>',
])
def test_sxodim_never_infers_publication_from_unrelated_or_nonpublication_dates(monkeypatch, detail):
    monkeypatch.setattr(events, "_fetch", lambda url, *args: sxodim_listing(SXODIM_TOUR_URL) if "/afisha?" in url else detail)
    assert events.collect_sxodim(pages=1)[0].get("published_at") is None


@pytest.mark.parametrize("publication", [
    "2026-02-30", "2026-10-01T25:00:00+05:00", "2026-10-01T12:00:00+05:99", "yesterday", 123,
])
def test_sxodim_invalid_publication_is_unknown_and_reported(monkeypatch, publication):
    detail = '<script type="application/ld+json">' + json.dumps({
        "@type": "Article", "url": SXODIM_TOUR_URL, "datePublished": publication,
    }) + '</script>'
    monkeypatch.setattr(events, "_fetch", lambda url, *args: sxodim_listing(SXODIM_TOUR_URL) if "/afisha?" in url else detail)
    rows = events.collect_sxodim(pages=1)
    assert rows[0].get("published_at") is None
    assert rows.errors
    assert SXODIM_TOUR_URL in rows.errors[0]


@pytest.mark.parametrize("url", [
    "https://other.test/astana/event/concert", "http://sxodim.com/astana/event/concert",
    "https://sxodim.com@other.test/astana/event/concert", "https://sxodim.com/astana/place/concert",
])
def test_sxodim_never_fetches_publication_from_untrusted_event_url(monkeypatch, url):
    calls = []

    def fetch(requested, *args):
        calls.append(requested)
        return sxodim_listing(url)

    monkeypatch.setattr(events, "_fetch", fetch)
    rows = events.collect_sxodim(pages=1)
    assert len(rows) == 1
    assert rows[0].get("published_at") is None
    assert calls == ["https://sxodim.com/astana/afisha?page=1"]


def test_sxodim_publication_url_guard_rejects_malformed_url():
    assert events._sxodim_event_url("https://[sxodim.com/astana/event/concert") is None


def test_sxodim_detail_failure_preserves_prior_publication_and_persists_diagnostics(tmp_path, monkeypatch):
    output, pois = tmp_path / "events.jsonl", tmp_path / "pois.jsonl"
    pois.write_text("")
    prior = event(id="existing-tour", url=SXODIM_TOUR_URL, published_at="2024-06-05T15:12:00+05:00",
                  first_seen_at="2026-10-18T12:00:00+05:00")
    output.write_text(json.dumps(prior) + "\n")

    def fetch(url, *args):
        if "/afisha?" in url:
            return sxodim_listing(SXODIM_TOUR_URL)
        raise TimeoutError("publication detail timed out")

    monkeypatch.setattr(events, "EVENTS_FILE", output)
    monkeypatch.setattr(events, "POIS_FILE", pois)
    monkeypatch.setattr(events, "_fetch", fetch)
    monkeypatch.setattr(events, "collect_ticketon", lambda: [])
    report = events.collect_events()
    row = read_rows(output)[0]
    assert row["published_at"] == "2024-06-05T15:12:00+05:00"
    assert row["id"] == "existing-tour"
    assert row["first_seen_at"] == "2026-10-18T12:00:00+05:00"
    assert report["sources"]["sxodim"]["status"] == "partial"
    persisted = json.loads(output.with_name("events_refresh.json").read_text())
    assert any("publication detail timed out" in error for error in persisted["sources"]["sxodim"]["errors"])

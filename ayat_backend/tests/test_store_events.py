"""Event venues must use the same identifiers as the canonical recommendation store."""
import asyncio
import json

import httpx
import pytest

from ayat_backend.app import store
from ayat_backend.app.schemas import RecommendRequest, RecommendResponse
from ayat_backend.app.service import Runtime, recommend


def poi(poi_id="osm:way/123", name="Тестовый концертный зал", **fields):
    return {
        "id": poi_id, "name": name, "category": "theatre", "lat": 51.1285, "lon": 71.4305,
        "source": "osm", "source_url": "https://www.openstreetmap.org/way/123",
        "source_records": [{"id": poi_id, "source": "osm"}],
        "opening_hours": "Mo-Su 10:00-23:00", "raw_tags": {}, **fields,
    }


def event(poi_id="osm:w123", event_id="event:1"):
    return {
        "id": event_id, "poi_id": poi_id, "title": "Вечерний концерт",
        "source": "ticketon", "url": "https://ticketon.kz/event/example",
        "sessions": ["2026-10-20T18:20:00+05:00"], "price_from": "3000",
    }


@pytest.fixture
def snapshot(tmp_path, monkeypatch):
    paths = {
        "CANONICAL_POIS_FILE": tmp_path / "pois.json", "POIS_FILE": tmp_path / "pois.jsonl",
        "CANONICAL_QUARANTINE_FILE": tmp_path / "quarantine.json",
        "GAZETTEER_FILE": tmp_path / "gazetteer.json", "MANIFEST_FILE": tmp_path / "manifest.json",
        "EMBEDDINGS_FILE": tmp_path / "embeddings.npy", "EVENTS_FILE": tmp_path / "events.jsonl",
        "RIVER_FILE": tmp_path / "river.json",
    }
    for name, path in paths.items():
        monkeypatch.setattr(store, name, path)

    def load(rows, events, *, canonical=True):
        if canonical:
            paths["CANONICAL_POIS_FILE"].write_text(json.dumps(rows, ensure_ascii=False))
        paths["POIS_FILE"].write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows))
        paths["EVENTS_FILE"].write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in events))
        original_events = paths["EVENTS_FILE"].read_bytes()
        result = store.load_store("off")
        assert paths["EVENTS_FILE"].read_bytes() == original_events
        return result

    return load


def test_canonical_event_venues_resolve_unique_source_ids_and_aliases(snapshot):
    rows = [poi(source_records=[{"id": "osm:way/123", "source": "osm"},
                               {"id": "directory:venue-1", "source": "directory"}])]
    result = snapshot(rows, [event(), event("directory:venue-1", "event:2"),
                             event("osm:way/123", "event:3")])

    assert [(e["poi_id"], e["source_poi_id"]) for e in result.events] == [
        ("osm:way/123", "osm:w123"),
        ("osm:way/123", "directory:venue-1"),
        ("osm:way/123", "osm:way/123"),
    ]
    assert result.manifest["events"] == {
        "loaded": 3, "active": 3, "remapped": 2, "excluded": 0,
        "excluded_unmatched": 0, "excluded_ambiguous": 0,
    }


@pytest.mark.parametrize("other_category", ["theatre", "other"])
def test_canonical_events_with_missing_or_ambiguous_venues_are_inactive(snapshot, other_category):
    shared = {"id": "shared:venue", "source": "directory"}
    rows = [poi(source_records=[shared]), poi("osm:way/456", "Другой зал", category=other_category,
                                             source_records=[shared])]
    result = snapshot(rows, [event("shared:venue"), event("unmatched:venue", "event:2"),
                             event(None, "event:3")])

    assert result.events == []
    assert result.manifest["events"] == {
        "loaded": 3, "active": 0, "remapped": 0, "excluded": 3,
        "excluded_unmatched": 2, "excluded_ambiguous": 1,
    }


def test_legacy_snapshot_preserves_original_event_venue_ids(snapshot):
    original = event("unmatched:legacy")
    result = snapshot([poi("osm:w123")], [original], canonical=False)
    assert result.events == [original]


def test_remapped_event_is_attached_to_service_recommendation(snapshot):
    result = snapshot([poi()], [event()])

    async def run():
        async with httpx.AsyncClient() as http:
            runtime = Runtime(store=result, graph=None, poi_nodes=None, poi_snap=None,
                              embedder=None, http=http, cache={})
            return await recommend(runtime, RecommendRequest(
                query="Хочу на концерт", location={"lat": 51.128, "lon": 71.430},
                now="2026-10-20T18:00:00+05:00", time_budget_min=180, want_route=False,
                weather={"temperature_c": 12, "feels_like_c": 10, "wind_ms": 2},
            ))

    response = asyncio.run(run())
    RecommendResponse.model_validate(response)
    assert [(p["poi_id"], p["event"]) for p in response["recommendations"]] == [
        ("osm:way/123", {"title": "Вечерний концерт", "starts_at": "18:20",
                         "url": "https://ticketon.kz/event/example", "source": "ticketon", "price_from": "3000"}),
    ]

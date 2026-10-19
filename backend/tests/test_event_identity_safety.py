import json

from pipeline import events


import pytest as _pytest


@_pytest.fixture(scope="module", autouse=True)
def canonical_snapshot_mode():
    """These tests cover the team catalogue runtime (opt-in in production)."""
    with _pytest.MonkeyPatch.context() as mp:
        mp.setenv("DATA_SNAPSHOT_MODE", "canonical")
        yield


def test_same_name_network_remains_unresolved_in_both_orders_and_keeps_evidence(tmp_path, monkeypatch):
    pois = [{"id": "osm:n1", "name": "Coffee BOOM", "name_auto": False, "lat": 51.12, "lon": 71.43},
            {"id": "osm:n2", "name": "Coffee BOOM", "name_auto": False, "lat": 51.15, "lon": 71.46}]
    source = {"title": "Future concert", "venue": "Coffee BOOM", "lat": None, "lon": None,
              "address": None, "sessions": ["2099-01-01T18:00:00+05:00"], "start": "2099-01-01T18:00:00+05:00",
              "end": None, "source": "ticketon", "url": "https://example.test/event"}
    path, output = tmp_path / "pois.jsonl", tmp_path / "events.jsonl"
    monkeypatch.setattr(events, "POIS_FILE", path)
    monkeypatch.setattr(events, "EVENTS_FILE", output)
    monkeypatch.setattr(events, "collect_ticketon", lambda: [dict(source)])
    monkeypatch.setattr(events, "collect_sxodim", lambda: [])
    results = []
    for ordered in (pois, list(reversed(pois))):
        path.write_text("\n".join(json.dumps(p) for p in ordered))
        events.collect_events()
        linked = [json.loads(line) for line in output.read_text().splitlines()]
        assert not any(e.get("poi_id") for e in linked), "A chain name cannot choose a random branch"
        unresolved_path = output.with_name("events_unresolved.json")
        assert unresolved_path.exists()
        unresolved = json.loads(unresolved_path.read_bytes())
        assert len(unresolved) == 1
        assert unresolved[0]["source_venue"] == "Coffee BOOM"
        assert unresolved[0]["source_lat"] is None
        assert unresolved[0]["match_status"] == "ambiguous"
        assert [p["id"] for p in unresolved[0]["match_candidates"]] == ["osm:n1", "osm:n2"]
        results.append(unresolved[0]["match_candidates"])
    assert results[0] == results[1]

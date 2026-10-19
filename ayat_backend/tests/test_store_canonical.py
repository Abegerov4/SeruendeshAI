"""The integrated server must search the current canonical data, not stale JSONL."""
import hashlib
import json

import numpy as np
import pytest

from ayat_backend.app import store


@pytest.fixture
def snapshot(tmp_path, monkeypatch):
    canonical = tmp_path / "pois.json"
    row = {"id": "osm:node/1", "name": "Новая кофейня", "category": "cafe", "lat": 51.128,
           "lon": 71.430, "source": "osm", "source_url": "https://www.openstreetmap.org/node/1",
           "source_records": [{"id": "osm:node/1", "source": "osm", "source_url": "https://www.openstreetmap.org/node/1"}],
           "aliases": ["New coffee place"], "tags": [], "raw_tags": {}, "description": "Кофейня.",
           "description_kind": "source", "opening_hours": None, "kid_friendly": None, "wheelchair": None}
    canonical.write_text(json.dumps([row], ensure_ascii=False))
    legacy = tmp_path / "pois.jsonl"
    legacy.write_text(json.dumps({"id": "stale:1", "name": "Old", "category": "cafe", "lat": 51.128, "lon": 71.430}) + "\n")
    for field, path in {"POIS_FILE": legacy, "CANONICAL_POIS_FILE": canonical,
                        "CANONICAL_QUARANTINE_FILE": tmp_path / "quarantine.json",
                        "GAZETTEER_FILE": tmp_path / "gazetteer.json", "MANIFEST_FILE": tmp_path / "manifest.json",
                        "EMBEDDINGS_FILE": tmp_path / "embeddings.npy", "EVENTS_FILE": tmp_path / "events.jsonl",
                        "RIVER_FILE": tmp_path / "river.json"}.items():
        monkeypatch.setattr(store, field, path, raising=False)
    return canonical, row


def test_current_canonical_records_replace_legacy_search_snapshot(snapshot):
    canonical, _ = snapshot
    result = store.load_store("off")
    assert set(result.by_id) == {"osm:node/1"}
    assert result.manifest["canonical_sha256"] == hashlib.sha256(canonical.read_bytes()).hexdigest()
    assert "coffee" in store.stem_tokens(store.poi_document(result.pois[0]))


def test_old_dense_matrix_is_never_attached_to_canonical_records(snapshot):
    np.save(store.EMBEDDINGS_FILE, np.ones((1, 4)))
    store.MANIFEST_FILE.write_text(json.dumps({"embedding_model": "e5-large", "embedding_pois_sha": "old", "pois_sha": "old"}))
    result = store.load_store("e5-large")
    assert result.emb is None
    assert result.manifest["dense_disabled"] is True


def test_versioned_store_freezes_review_events_and_pois_together(snapshot):
    from data.snapshot import publish_snapshot
    canonical, row = snapshot
    def bundle(rows, event_id):
        return {"pois.json": rows, "pois_leisure.json": rows, "quarantine.json": [],
                "source_manifest.json": {"status": "ok", "sources": {}}, "stats.json": {"output_count": len(rows)},
                "events.jsonl": json.dumps({"id": event_id, "poi_id": "osm:node/1"}) + "\n"}
    old_handle = publish_snapshot(canonical.parent, bundle([row], "old-event"))
    old = store.load_store("off")
    extra = {**row, "id": "osm:node/2", "name": "Another Cafe", "source_records": [{"id": "osm:node/2", "source": "osm"}]}
    new_handle = publish_snapshot(canonical.parent, bundle([row, extra], "new-event"))
    new = store.load_store("off")
    assert old.manifest["snapshot_version"] == old_handle.version
    assert old.size == 1 and old.events[0]["id"] == "old-event"
    assert new.manifest["snapshot_version"] == new_handle.version
    assert new.size == 2 and new.events[0]["id"] == "new-event"

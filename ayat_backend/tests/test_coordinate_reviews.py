"""Reviewed routing coordinates stay source-bound and leave the master intact."""
from __future__ import annotations

import hashlib
import json

import pytest

from ayat_backend.app.team_data import load_team_snapshot
from data.snapshot import publish_snapshot, resolve_snapshot


@pytest.fixture
def coordinate_bundle():
    row = {
        "id": "citypass:64", "name": "Колесо обозрения Ailand",
        "category": "attraction", "lat": 51.13214, "lon": 71.4118,
        "source": "citypass", "source_url": "https://example.org/citypass/64",
        "address": "Коргалжынское шоссе, 2", "raw_tags": {},
        "source_records": [{"id": "citypass:64", "source": "citypass",
                            "source_url": "https://example.org/citypass/64"}],
    }
    raw = (json.dumps([row], ensure_ascii=False, indent=2) + "\n").encode()
    return {
        "pois.json": raw, "pois_leisure.json": [row],
        "source_manifest.json": {}, "stats.json": {"output_count": 1},
    }


def coordinate_reviews(raw, *, status="accepted", canonical_sha256=None):
    return {
        "schema_version": 1,
        "canonical_sha256": canonical_sha256 or hashlib.sha256(raw).hexdigest(),
        "reviews": [{
            "canonical_id": "citypass:64", "field": "coordinates",
            "value": {"lat": 51.147356, "lon": 71.414465}, "status": status,
            "source": "reviewed_directory", "source_id": "directory:wheel",
            "source_url": "https://example.org/directory/wheel",
            "checked_at": "2026-10-19", "reviewed_by": "curator",
            "evidence_excerpt": "Ailand wheel route destination: 51.147356, 71.414465.",
        }],
    }


def test_accepted_coordinate_review_reaches_runtime_from_immutable_snapshot(tmp_path, coordinate_bundle):
    original = coordinate_bundle["pois.json"]
    reviews = coordinate_reviews(original)
    handle = publish_snapshot(tmp_path, {**coordinate_bundle, "fact_reviews.json": reviews})

    pois, gazetteer, manifest = load_team_snapshot(handle.path / "pois.json")

    for view in (pois[0], gazetteer[0]):
        assert (view["lat"], view["lon"]) == (51.147356, 71.414465)
        assert (view["canonical_lat"], view["canonical_lon"]) == (51.13214, 71.4118)
        assert view["source_ids"] == ["citypass:64"]
        assert view["fact_reviews"] == reviews["reviews"]
        coordinate_evidence = [f for f in view["field_evidence"] if f["field"] == "coordinates"]
        assert len(coordinate_evidence) == 1
        assert coordinate_evidence[0]["value"] == {"lat": 51.147356, "lon": 71.414465}
        assert coordinate_evidence[0]["source_id"] == "directory:wheel"
    assert manifest["canonical_sha256"] == hashlib.sha256(original).hexdigest()
    assert (handle.path / "pois.json").read_bytes() == original
    assert json.loads((handle.path / "pois.json").read_bytes())[0]["lat"] == 51.13214


def test_pending_coordinate_review_does_not_move_runtime_location(tmp_path, coordinate_bundle):
    original = coordinate_bundle["pois.json"]
    handle = publish_snapshot(tmp_path, {
        **coordinate_bundle, "fact_reviews.json": coordinate_reviews(original, status="pending"),
    })

    pois, gazetteer, _ = load_team_snapshot(handle.path / "pois.json")

    for view in (pois[0], gazetteer[0]):
        assert (view["lat"], view["lon"]) == (51.13214, 71.4118)
        assert not any(f["field"] == "coordinates" for f in view.get("field_evidence", []))
    assert (handle.path / "pois.json").read_bytes() == original


def test_unresolved_geometry_is_absent_from_recommendations_and_origins(tmp_path, coordinate_bundle):
    row=json.loads(coordinate_bundle["pois.json"])[0]
    row["field_conflicts"]=[{"field":"coordinates","source_id":"old:1","value":"disputed"}]
    raw=json.dumps([row]).encode()
    (tmp_path/"pois.json").write_bytes(raw)
    (tmp_path/"fact_reviews.json").write_text(json.dumps(coordinate_reviews(raw)))
    pois,gaz,manifest=load_team_snapshot(tmp_path/"pois.json")
    assert pois == [] and gaz == []
    assert manifest["preserved_source_ids_count"] == 1


def test_coordinate_review_with_wrong_master_hash_cannot_load_runtime(tmp_path, coordinate_bundle):
    original = coordinate_bundle["pois.json"]
    canonical_path = tmp_path / "pois.json"
    canonical_path.write_bytes(original)
    (tmp_path / "fact_reviews.json").write_text(json.dumps(
        coordinate_reviews(original, canonical_sha256="0" * 64),
    ))

    with pytest.raises(ValueError, match="snapshot hash"):
        load_team_snapshot(canonical_path)

    assert canonical_path.read_bytes() == original


def test_wrong_hash_coordinate_review_cannot_replace_active_snapshot(tmp_path, coordinate_bundle):
    prior = publish_snapshot(tmp_path, coordinate_bundle)
    original = coordinate_bundle["pois.json"]

    with pytest.raises(ValueError, match="snapshot hash"):
        publish_snapshot(tmp_path, {
            **coordinate_bundle,
            "fact_reviews.json": coordinate_reviews(original, canonical_sha256="0" * 64),
        })

    assert resolve_snapshot(tmp_path).version == prior.version
    pois, _, _ = load_team_snapshot(prior.path / "pois.json")
    assert (pois[0]["lat"], pois[0]["lon"]) == (51.13214, 71.4118)
    assert (prior.path / "pois.json").read_bytes() == original

"""Refresh an actual published bundle without losing or guessing review decisions."""
from copy import deepcopy
import hashlib
import json

import pytest

from data import run_pipeline as pipeline
from data.eligibility import apply_fact_reviews, review_matches, safe_facts, source_ids
from data.snapshot import SnapshotHandle, SnapshotRejected, publish_snapshot, resolve_snapshot


BOUNDARY = {"type": "Polygon", "coordinates": [[[71.2, 50.85], [71.8, 50.85],
             [71.8, 51.35], [71.2, 51.35], [71.2, 50.85]]]}


def _seed(raw, rows):
    folder = raw / "osm"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "candidates.json").write_text(json.dumps(rows))
    (folder / "report.json").write_text(json.dumps({"status": "ok", "count": len(rows)}))
    (folder / "boundary.geojson").write_text(json.dumps(BOUNDARY))


def _row(number, **changes):
    return {"id": f"osm:node/{number}", "name": f"Distinct cafe {number}",
            "lat": 51.10 + number / 100, "lon": 71.43, "category": "cafe",
            "source": "osm", "source_url": f"https://www.openstreetmap.org/node/{number}",
            **changes}


def _reviewed_bundle(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "ROOT", tmp_path)
    raw, out = tmp_path / "raw", tmp_path / "processed"
    candidates = [_row(1), _row(2, opening_hours="Mo-Su 09:00-18:00"), _row(3)]
    _seed(raw, candidates)
    pipeline.run_pipeline(raw, out, sources=("osm",), offline=True)
    initial = resolve_snapshot(out)
    master = (initial.path / "pois.json").read_bytes()
    accepted = {"canonical_id": "osm:node/1", "field": "internet_access", "value": "wlan",
                "status": "accepted", "source": "venue_owner", "source_id": "owner:cafe-one",
                "source_url": "https://example.org/cafe-one", "checked_at": "2026-10-19",
                "reviewed_by": "human-reviewed", "evidence_excerpt": "Owner reports Wi-Fi at this branch."}
    disputed = {"canonical_id": "osm:node/2", "field": "opening_hours", "status": "disputed",
                "checked_at": "2026-10-19", "reviewed_by": "human-reviewed",
                "reason": "Two attributed sources report different closing times.",
                "reports": [{"source_id": "owner:cafe-two", "source_url": "https://example.org/cafe-two", "value": "Mo-Su 09:00-20:00"},
                            {"source_id": "city:cafe-two", "source_url": "https://example.org/city/cafe-two", "value": "Mo-Su 09:00-18:00"}]}
    quarantine = [{"id": "osm:node/3", "reason": "Reviewed wrong coordinates", "reviewed_on": "2026-10-19"}]
    reviews = {"schema_version": 1, "canonical_sha256": hashlib.sha256(master).hexdigest(),
               "reviews": [accepted, disputed]}
    artifacts = {name: (initial.path / name).read_bytes() for name in initial.manifest["files"]}
    artifacts.update({"fact_reviews.json": reviews, "quarantine.json": quarantine,
                      "quality_overrides.json": {}, "field_evidence.json": {}})
    prior = publish_snapshot(out, artifacts, required_sources=("osm",))
    return raw, out, candidates, prior, reviews, quarantine


def _read(handle, name):
    return json.loads((handle.path / name).read_bytes())


def test_added_source_row_preserves_unchanged_accepted_facts_and_all_policy(tmp_path, monkeypatch):
    raw, out, candidates, prior, reviews, quarantine = _reviewed_bundle(tmp_path, monkeypatch)
    old_rows = _read(prior, "pois.json")
    _seed(raw, [*candidates, _row(4)])
    pipeline.run_pipeline(raw, out, sources=("osm",), offline=True)
    current = resolve_snapshot(out)
    rows, carried = _read(current, "pois.json"), _read(current, "fact_reviews.json")
    assert current.version != prior.version
    assert carried["canonical_sha256"] == current.manifest["files"]["pois.json"]["sha256"]
    assert carried["canonical_sha256"] != reviews["canonical_sha256"]
    assert [r for r in rows if r["id"] != "osm:node/4"] == old_rows
    assert carried["reviews"] == reviews["reviews"]
    assert {ident for row in old_rows for ident in source_ids(row)} <= {ident for row in rows for ident in source_ids(row)}
    assert _read(current, "quarantine.json") == quarantine
    assert _read(current, "quality_overrides.json") == {}
    assert _read(current, "field_evidence.json") == {}
    derived = apply_fact_reviews(rows, carried, canonical_sha256=carried["canonical_sha256"])
    assert next(r for r in derived if r["id"] == "osm:node/1")["raw_tags"]["internet_access"] == "wlan"
    assert safe_facts(next(r for r in derived if r["id"] == "osm:node/2"))["opening_hours"] is None
    matched, unmatched, ambiguous = review_matches(rows, _read(current, "quarantine.json"))
    assert set(matched) == {"osm:node/3"} and not unmatched and not ambiguous


def test_changed_full_row_demotes_confirmation_and_preserves_original_review_history(tmp_path, monkeypatch):
    raw, out, candidates, prior, reviews, _ = _reviewed_bundle(tmp_path, monkeypatch)
    original = deepcopy(reviews["reviews"][0])
    # Even an unrelated canonical field change requires a fresh manual decision.
    _seed(raw, [{**candidates[0], "address": "New branch address 20"}, *candidates[1:]])
    pipeline.run_pipeline(raw, out, sources=("osm",), offline=True)
    current = resolve_snapshot(out)
    rows, carried = _read(current, "pois.json"), _read(current, "fact_reviews.json")
    pending = next(r for r in carried["reviews"] if r["canonical_id"] == "osm:node/1")
    assert pending["status"] == "pending"
    assert pending["reason"]
    assert pending["review_history"][-1] == {"canonical_sha256": reviews["canonical_sha256"], "review": original}
    assert {k: pending[k] for k in original if k != "status"} == {k: v for k, v in original.items() if k != "status"}
    assert carried["canonical_sha256"] == hashlib.sha256((current.path / "pois.json").read_bytes()).hexdigest()
    derived = apply_fact_reviews(rows, carried, canonical_sha256=carried["canonical_sha256"])
    assert next(r for r in derived if r["id"] == "osm:node/1").get("raw_tags", {}).get("internet_access") is None
    # A subsequent unchanged rebuild cannot silently promote a pending decision.
    pipeline.run_pipeline(raw, out, sources=("osm",), offline=True)
    assert _read(resolve_snapshot(out), "fact_reviews.json")["reviews"] == carried["reviews"]


def test_changed_disputed_record_stays_withheld_and_local_empty_quarantine_cannot_clear_prior(tmp_path, monkeypatch):
    raw, out, candidates, prior, reviews, quarantine = _reviewed_bundle(tmp_path, monkeypatch)
    (tmp_path / "data").mkdir()
    (tmp_path / "data/quarantine.json").write_text("[]")
    _seed(raw, [candidates[0], {**candidates[1], "opening_hours": "Mo-Su 08:00-22:00"}, candidates[2]])
    pipeline.run_pipeline(raw, out, sources=("osm",), offline=True)
    current = resolve_snapshot(out)
    rows, carried = _read(current, "pois.json"), _read(current, "fact_reviews.json")
    assert next(r for r in carried["reviews"] if r["status"] == "disputed") == reviews["reviews"][1]
    derived = apply_fact_reviews(rows, carried, canonical_sha256=carried["canonical_sha256"])
    assert safe_facts(next(r for r in derived if r["id"] == "osm:node/2"))["opening_hours"] is None
    assert _read(current, "quarantine.json") == quarantine


def test_refresh_cannot_hide_source_loss_or_mutate_published_review_history(tmp_path, monkeypatch):
    raw, out, candidates, prior, reviews, _ = _reviewed_bundle(tmp_path, monkeypatch)
    _seed(raw, candidates[:2])
    with pytest.raises(SnapshotRejected, match="lost_source_ids:osm:node/3"):
        pipeline.run_pipeline(raw, out, sources=("osm",), offline=True)
    assert resolve_snapshot(out).version == prior.version
    assert _read(prior, "fact_reviews.json") == reviews


def test_stale_prior_review_binding_is_rejected_before_rebinding(tmp_path):
    # Legacy imports lack a bundle manifest; the old overlay still must validate.
    master = (json.dumps([_row(1)], indent=2) + "\n").encode()
    (tmp_path / "pois.json").write_bytes(master)
    (tmp_path / "fact_reviews.json").write_text(json.dumps({
        "schema_version": 1, "canonical_sha256": "wrong-old-hash", "reviews": []}))
    with pytest.raises(ValueError, match="snapshot hash/schema mismatch"):
        pipeline._refresh_fact_reviews(SnapshotHandle(tmp_path, "legacy", {}), [_row(1)], master)

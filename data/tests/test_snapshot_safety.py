"""Publication must never replace usable data with a truncated or mixed bundle."""
import json

import pytest

try:
    from data import snapshot
except ImportError:
    snapshot = None


@pytest.fixture(autouse=True)
def snapshot_api_exists():
    assert snapshot is not None, "Missing atomic snapshot publication API"


def artifacts(ids, status="ok"):
    rows = [{"id": i, "category": "cafe", "source_records": [{"id": i}]} for i in ids]
    return {"pois.json": rows, "pois_leisure.json": rows,
            "source_manifest.json": {"status": status, "sources": {"osm": {"status": status}}},
            "stats.json": {"output_count": len(rows)}}


def test_partial_three_to_one_preserves_active_and_records_rejection(tmp_path):
    old = snapshot.publish_snapshot(tmp_path, artifacts(["a", "b", "c"]))
    with pytest.raises(snapshot.SnapshotRejected, match="lost_source_ids"):
        snapshot.publish_snapshot(tmp_path, artifacts(["a"], "partial"), required_sources=("osm",))
    assert snapshot.resolve_snapshot(tmp_path).version == old.version
    rejected = list((tmp_path / ".snapshots").glob("*.rejected.json"))
    assert json.loads(rejected[0].read_text())["reasons"]


@pytest.mark.parametrize("stage", ["write:pois.json", "write:pois_leisure.json", "write:source_manifest.json",
                                  "write:stats.json", "manifest", "validate", "freeze", "before_pointer"])
def test_failure_at_every_promotion_stage_retains_complete_old_handle(tmp_path, stage):
    old = snapshot.publish_snapshot(tmp_path, artifacts(["a", "b", "c"]))
    def fail(current):
        if current == stage:
            raise OSError("fault " + stage)
    with pytest.raises(OSError, match="fault"):
        snapshot.publish_snapshot(tmp_path, artifacts(["a", "b", "c", "d"]), fault=fail)
    selected = snapshot.resolve_snapshot(tmp_path)
    assert selected.version == old.version
    assert json.loads((selected.path / "stats.json").read_text())["output_count"] == 3


def test_bound_reader_retains_old_version_after_success_and_hashes_detect_corruption(tmp_path):
    old = snapshot.publish_snapshot(tmp_path, artifacts(["a", "b", "c"]))
    new = snapshot.publish_snapshot(tmp_path, artifacts(["a", "b", "c", "d"]))
    assert snapshot.resolve_snapshot(tmp_path).version == new.version != old.version
    assert json.loads((old.path / "pois.json").read_text()) == artifacts(["a", "b", "c"])["pois.json"]
    (new.path / "stats.json").write_text("{}")
    with pytest.raises(ValueError, match="hash"):
        snapshot.resolve_snapshot(tmp_path)


@pytest.mark.parametrize("sidecar", ["quarantine.json", "quality_overrides.json", "field_evidence.json", "fact_reviews.json"])
def test_promotion_cannot_drop_previous_policy_sidecars(tmp_path, sidecar):
    import hashlib
    first = artifacts(["a", "b", "c"])
    first[sidecar] = ([] if sidecar == "quarantine.json" else
                      {"schema_version": 1, "canonical_sha256": hashlib.sha256((json.dumps(first["pois.json"], ensure_ascii=False, indent=2) + "\n").encode()).hexdigest(), "reviews": []}
                      if sidecar == "fact_reviews.json" else {})
    old = snapshot.publish_snapshot(tmp_path, first)
    with pytest.raises(snapshot.SnapshotRejected, match="missing_policy_sidecar:" + sidecar):
        snapshot.publish_snapshot(tmp_path, artifacts(["a", "b", "c"]))
    assert snapshot.resolve_snapshot(tmp_path).version == old.version


def test_explicit_reviewed_policy_sidecar_removal_is_auditable(tmp_path):
    first = artifacts(["a", "b", "c"])
    first["quarantine.json"] = []
    snapshot.publish_snapshot(tmp_path, first)
    approval = {"reason": "Reviewed empty legacy policy replaced by current eligibility rules",
                "reviewed_by": "curator", "reviewed_on": "2026-10-19", "evidence_urls": ["https://example.org/review"]}
    new = snapshot.publish_snapshot(tmp_path, artifacts(["a", "b", "c"]),
                                    approved_removed_sidecars={"quarantine.json": approval})
    assert new.manifest["approved_removed_sidecars"] == {"quarantine.json": approval}
    assert not (new.path / "quarantine.json").exists()


def test_dropped_quarantine_cannot_reactivate_previously_excluded_candidates(tmp_path):
    from app.team_data import load_team_snapshot
    initial = artifacts(["osm:node/1", "osm:node/2", "osm:node/3"])
    for i, row in enumerate(initial["pois.json"]):
        row.update(name="Cafe " + str(i), lat=51.12, lon=71.43, source="osm", raw_tags={})
    initial["quarantine.json"] = [{"id": "osm:n1", "reason": "Reviewed wrong classification"}]
    old = snapshot.publish_snapshot(tmp_path, initial)
    active, _, _ = load_team_snapshot(old.path / "pois.json", quarantine_path=old.path / "quarantine.json")
    assert {p["id"] for p in active} == {"osm:node/2", "osm:node/3"}
    next_bundle = {name: value for name, value in initial.items() if name != "quarantine.json"}
    with pytest.raises(snapshot.SnapshotRejected, match="missing_policy_sidecar:quarantine.json"):
        snapshot.publish_snapshot(tmp_path, next_bundle)
    still_selected = snapshot.resolve_snapshot(tmp_path)
    active, _, _ = load_team_snapshot(still_selected.path / "pois.json", quarantine_path=still_selected.path / "quarantine.json")
    assert {p["id"] for p in active} == {"osm:node/2", "osm:node/3"}

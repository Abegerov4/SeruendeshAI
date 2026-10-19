"""New evidence follows the same immutable binding/retention rules as old reviews."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from data.snapshot import publish_snapshot, SnapshotRejected


def test_place_and_service_sidecars_are_required_to_survive_refresh(tmp_path):
    rows = [{"id":"one","name":"Cafe","category":"cafe","address":"A","lat":51.1,"lon":71.4}]
    raw = json.dumps(rows).encode()
    base = {"pois.json":raw,"pois_leisure.json":rows,"source_manifest.json":{},"stats.json":{}}
    publish_snapshot(tmp_path,{**base,"place_details.json":{"schema_version":1,"canonical_sha256":hashlib.sha256(raw).hexdigest(),
        "as_of":"2026-10-19","records":[]}, "city_services.json":{"schema_version":1,"as_of":"2026-10-19",
        "collected_at":"2026-10-19T00:00:00+05:00","operators":[],"services":[]}})
    with pytest.raises(SnapshotRejected,match="missing_policy_sidecar"):
        publish_snapshot(tmp_path,base)


def test_changed_canonical_record_withholds_its_old_details_but_retains_history(tmp_path):
    from data.run_pipeline import _refresh_place_details
    rows = [{"id":"one","name":"Cafe","address":"A","lat":51.1,"lon":71.4},
            {"id":"two","name":"Cafe","address":"B","lat":51.2,"lon":71.4}]
    raw = json.dumps(rows).encode()
    (tmp_path/"pois.json").write_bytes(raw)
    details = {"schema_version":1,"canonical_sha256":hashlib.sha256(raw).hexdigest(),"as_of":"2026-10-19",
               "records":[{"canonical_id":"one","identity":{},"facts":[]}, {"canonical_id":"two","identity":{},"facts":[]}]}
    (tmp_path/"place_details.json").write_text(json.dumps(details))
    updated = [rows[0],{**rows[1],"phone":"new"}]
    newraw = json.dumps(updated).encode()
    out = _refresh_place_details(SimpleNamespace(path=tmp_path),updated,newraw)
    assert [r["canonical_id"] for r in out["records"]] == ["one"]
    assert out["canonical_sha256"] == hashlib.sha256(newraw).hexdigest()
    assert out["pending_records"][0]["record"]["canonical_id"] == "two"
    assert out["pending_records"][0]["canonical_sha256"] == details["canonical_sha256"]


def test_dense_fingerprint_tracks_place_data_and_reader(tmp_path):
    from app.canonical_index import policy_hashes
    first = policy_hashes(tmp_path)
    (tmp_path/"place_details.json").write_text('{}')
    second = policy_hashes(tmp_path)
    assert first != second
    assert second["place_details_code"]

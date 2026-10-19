"""Reviewed coordinates change routing atomically without rewriting source rows."""
from copy import deepcopy
import hashlib
import json

import pytest

from data.eligibility import apply_fact_reviews


def coordinate_review(**changes):
    return {"canonical_id": "citypass:64", "field": "coordinates",
            "value": {"lat": 51.147356, "lon": 71.414465}, "status": "accepted",
            "source": "2gis", "source_id": "2gis:70000001028675326",
            "source_url": "https://2gis.kz/astana/firm/70000001028675326/tab/info",
            "checked_at": "2026-10-19", "reviewed_by": "source-review",
            "evidence_excerpt": "Ailand wheel, 65m, 36 cabins; exact branch route destination.",
            **changes}


def apply(review, *, snapshot_hash="master"):
    original = {"id": "citypass:64", "name": "Колесо обозрения «Ailand»",
                "lat": 51.1351, "lon": 71.4001, "category": "attraction"}
    result = apply_fact_reviews([original], {"schema_version": 1, "canonical_sha256": snapshot_hash,
                                "reviews": [review]}, canonical_sha256="master")
    return original, result[0]


def test_accepted_coordinates_change_both_derived_axes_and_retain_originals():
    review = coordinate_review()
    before = deepcopy(review)
    original, derived = apply(review)
    assert (derived["lat"], derived["lon"]) == (51.147356, 71.414465)
    assert (derived["canonical_lat"], derived["canonical_lon"]) == (51.1351, 71.4001)
    assert (original["lat"], original["lon"]) == (51.1351, 71.4001)
    assert "coordinates" not in derived
    assert derived["field_evidence"][0]["value"] == {"lat": 51.147356, "lon": 71.414465}
    assert derived["field_evidence"][0]["review_status"] == "accepted"
    assert review == before


@pytest.mark.parametrize("field", ["coordinates","lat","lon"])
def test_unresolved_geometry_is_withheld_until_explicit_resolution(field):
    from data.eligibility import safe_facts, exclusion_reasons
    row={"id":"citypass:64","lat":51.1351,"lon":71.4001,"category":"attraction",
         "field_conflicts":[{"field":field,"source_id":"old:1","value":"different point"}]}
    payload={"schema_version":1,"canonical_sha256":"master","reviews":[coordinate_review()]}
    result=apply_fact_reviews([row],payload,canonical_sha256="master")[0]
    assert (result["lat"],result["lon"]) == (row["lat"],row["lon"])
    assert safe_facts(result)["lat"] is None and safe_facts(result)["lon"] is None
    assert "unresolved_geometry" in exclusion_reasons(result)
    payload["reviews"][0].update(resolves_conflicts=True,resolved_source_ids=["old:1"],
                                  resolution_reason="Exact provider route identifies this branch")
    resolved=apply_fact_reviews([row],payload,canonical_sha256="master")[0]
    assert (resolved["lat"],resolved["lon"]) == (51.147356,71.414465)
    assert "unresolved_geometry" not in exclusion_reasons(resolved)


@pytest.mark.parametrize("status", ["pending", "rejected"])
def test_unaccepted_coordinate_assertion_cannot_change_routing(status):
    original, derived = apply(coordinate_review(status=status))
    assert (derived["lat"], derived["lon"]) == (51.1351, 71.4001)
    assert derived == original


@pytest.mark.parametrize("value", [
    {"lat": True, "lon": 71.414465}, {"lat": 51.147356, "lon": False},
    {"lat": "51.147356", "lon": 71.414465},
    {"lat": float("nan"), "lon": 71.414465},
    {"lat": 51.147356, "lon": float("inf")},
    {"lat": -90.0001, "lon": 71.414465}, {"lat": 90.0001, "lon": 71.414465},
    {"lat": 51.147356, "lon": -180.0001}, {"lat": 51.147356, "lon": 180.0001},
    {"lat": 51.147356}, {"lon": 71.414465},
    {"lat": 51.147356, "lon": 71.414465, "alt": 65},
    [51.147356, 71.414465], None,
])
def test_accepted_coordinates_require_one_complete_finite_numeric_pair(value):
    with pytest.raises(ValueError, match="coordinates"):
        apply(coordinate_review(value=value))


def test_coordinate_review_cannot_bypass_master_hash_binding():
    with pytest.raises(ValueError, match="snapshot hash"):
        apply(coordinate_review(), snapshot_hash="old-master")


@pytest.mark.parametrize("missing", ["source", "source_id", "source_url", "checked_at", "reviewed_by", "evidence_excerpt"])
def test_coordinate_review_requires_every_existing_provenance_field(missing):
    review = coordinate_review()
    del review[missing]
    with pytest.raises(ValueError, match="Accepted review requires"):
        apply(review)


def test_changed_source_row_demotes_old_coordinates_instead_of_carrying_routing_fix(tmp_path):
    from data.run_pipeline import _refresh_fact_reviews
    from data.snapshot import SnapshotHandle

    old = [{"id": "citypass:64", "name": "Колесо обозрения «Ailand»",
            "lat": 51.1351, "lon": 71.4001, "category": "attraction"}]
    master = json.dumps(old).encode()
    old_hash = hashlib.sha256(master).hexdigest()
    review = coordinate_review()
    payload = {"schema_version": 1, "canonical_sha256": old_hash, "reviews": [review]}
    (tmp_path / "pois.json").write_bytes(master)
    (tmp_path / "fact_reviews.json").write_text(json.dumps(payload))
    changed = [{**old[0], "lat": 51.1474}]
    new_master = json.dumps(changed).encode()
    refreshed = _refresh_fact_reviews(SnapshotHandle(tmp_path, "legacy", {}), changed, new_master)
    pending = refreshed["reviews"][0]
    assert pending["status"] == "pending"
    assert pending["value"] == {"lat": 51.147356, "lon": 71.414465}
    assert pending["review_history"] == [{"canonical_sha256": old_hash, "review": review}]
    derived = apply_fact_reviews(changed, refreshed, canonical_sha256=hashlib.sha256(new_master).hexdigest())
    assert (derived[0]["lat"], derived[0]["lon"]) == (51.1474, 71.4001)
    assert (tmp_path / "pois.json").read_bytes() == master

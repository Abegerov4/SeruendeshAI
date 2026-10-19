"""Review mechanisms must distinguish attributed source facts from real checks."""
import json

import pytest

try:
    from data.review import build_review
except ImportError:
    build_review = None


def test_review_keeps_unknowns_false_conflicts_and_license_holds_separate():
    assert build_review is not None, "Missing reproducible source-review mechanism"
    row = {"id": "p:1", "name": "Cafe", "category": "cafe", "lat": 51.12, "lon": 71.43,
           "opening_hours": "24/7", "wheelchair": "no", "source": "osm", "source_records": [{"id": "p:1"}],
           "description": "Unlicensed source text", "description_kind": "source", "description_license": "not_specified",
           "field_evidence": [{"field": "opening_hours", "value": "24/7", "source_id": "p:1", "source_url": "https://example.test", "checked_at": "2012-01-01"},
                              {"field": "wheelchair", "value": "no", "source_id": "p:1", "source_url": "https://example.test"}],
           "field_conflicts": [{"field": "opening_hours", "value": "Mo-Fr 09:00-18:00", "source_id": "p:2"}]}
    report = build_review([row], [row], as_of="2026-10-19")
    fields = report["field_review"][0]["fields"]
    assert fields["opening_hours"]["state"] == "conflicting"
    assert fields["opening_hours"]["freshness"]["status"] == "stale"
    assert fields["wheelchair"]["state"] == "false"
    assert fields["internet_access"]["state"] == "unknown"
    assert report["license_queue"][0]["publication_status"] == "held_pending_license_review"
    assert row["description"] == "Unlicensed source text"


def test_duplicates_are_unresolved_without_review_and_keep_tenant_host_decision():
    assert build_review is not None, "Missing reproducible duplicate-review mechanism"
    rows = [{"id": "p:1", "name": "Ailand", "category": "mall", "lat": 51.12, "lon": 71.43},
            {"id": "p:2", "name": "Ailand", "category": "museum", "lat": 51.12001, "lon": 71.43}]
    report = build_review(rows, rows, as_of="2026-10-19", decisions={"p:1|p:2": {"decision": "keep", "reason": "Tenant and host", "evidence_urls": ["https://example.test"]}})
    assert report["duplicates"][0]["decision"] == "keep"
    report = build_review(rows, rows, as_of="2026-10-19")
    assert report["duplicates"][0]["decision"] == "unresolved"
    assert report["duplicates"][0]["source_ids"] == ["p:1", "p:2"]

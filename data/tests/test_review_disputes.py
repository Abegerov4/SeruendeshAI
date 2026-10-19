from data.eligibility import apply_fact_reviews, safe_facts


def test_dated_unresolved_review_masks_old_hours_without_losing_reports():
    row = {"id": "osm:node/1", "opening_hours": "Mo-Su 09:00-21:00", "raw_tags": {}}
    review = {"canonical_id": row["id"], "field": "opening_hours", "status": "disputed",
              "reports": [{"source_id": "owner:1", "source_url": "https://owner.example/hours", "value": "10:00-21:00"},
                          {"source_id": "city:1", "source_url": "https://city.example/hours", "value": "09:00-21:00"}],
              "checked_at": "2026-10-19", "reviewed_by": "source_review", "reason": "Unresolved published schedules"}
    rows = apply_fact_reviews([row], {"schema_version": 1, "canonical_sha256": "same", "reviews": [review]}, canonical_sha256="same")
    assert safe_facts(rows[0])["opening_hours"] is None
    assert rows[0]["canonical_opening_hours"] == row["opening_hours"]
    assert {f["source_id"] for f in rows[0]["field_conflicts"]} == {"owner:1", "city:1"}
    assert row.get("field_conflicts") is None

import pytest

from data.collect.quality import apply_quality_overrides


def test_post_enrichment_review_does_not_change_pre_enrichment_candidates():
    rows = [{"id": "osm:1", "name": "Place"}, {"id": "citypass:1", "name": "Place"}]
    overrides = {"citypass:1": {"phase": "after_enrichment", "action": "verified_same_place",
                               "target_id": "osm:1", "reason": "Reviewed identity"}}
    before, quarantine, report = apply_quality_overrides(rows, overrides)
    assert before == rows and not quarantine and not report["applied_overrides"]
    after, _, report = apply_quality_overrides(rows, overrides, phase="after_enrichment")
    assert after[1]["verified_identity_parent_id"] == "osm:1"
    assert report["applied_overrides"] == [{"id": "citypass:1", "action": "verified_same_place"}]
    assert "verified_identity_parent_id" not in rows[1]


def test_legacy_review_is_applied_only_before_enrichment():
    rows = [{"id": "osm:1", "name": "Place"}]
    overrides = {"osm:1": {"action": "quarantine", "reason": "Reviewed source error"}}
    after, quarantine, report = apply_quality_overrides(rows, overrides, phase="after_enrichment")
    assert after == rows and not quarantine and not report["applied_overrides"]


@pytest.mark.parametrize("phase", ["typo", None, ""])
def test_unknown_review_phase_fails_instead_of_silently_ignoring_rules(phase):
    with pytest.raises(ValueError, match="phase"):
        apply_quality_overrides([{"id": "osm:1"}], {"osm:1": {"phase": phase, "action": "quarantine"}})
    with pytest.raises(ValueError, match="phase"):
        apply_quality_overrides([{"id": "osm:1"}], {}, phase=phase)


def test_review_quarantines_suspect_location_without_rewriting_source_coordinates():
    row = {"id": "bad_airport", "name": "Airport", "lat": 51.138, "lon": 71.4249}
    safe, quarantine, report = apply_quality_overrides([row], {"bad_airport": {"action": "quarantine", "reason": "Location conflicts with aerodrome", "evidence_urls": ["https://example.org/airport"]}})
    assert not safe and len(quarantine) == 1
    assert quarantine[0]["lat"] == row["lat"]
    assert "quality_review_notes" in quarantine[0]
    assert "quality_review_notes" not in row
    assert report["quarantine_count"] == 1


def test_corrected_upstream_coordinates_are_not_quarantined_by_old_review():
    row = {"id": "airport", "lat": 51.0259, "lon": 71.4663}
    safe, quarantine, _ = apply_quality_overrides([row], {"airport": {"action": "quarantine", "when": {"lat": 51.138, "lon": 71.4249}, "reason": "Prior central-city error"}})
    assert safe == [row] and not quarantine


def test_conflicting_article_link_stays_auditable_but_is_not_enriched():
    row = {"id": "university", "raw_tags": {"wikipedia": "en:Ministry", "wikidata": "Q1"}}
    safe, _, _ = apply_quality_overrides([row], {"university": {"action": "suppress_wikimedia", "reason": "University versus ministry"}})
    assert safe[0]["skip_wikimedia_enrichment"] is True
    assert safe[0]["raw_tags"]["wikidata"] == "Q1"


def test_reviewed_same_place_retains_source_address_and_merges_only_nearby_target():
    from data.collect.normalize import normalize_candidates
    base = {"id": "osm:monument", "name": "Бәйтерек", "lat": 51.12828, "lon": 71.43045, "category": "monument", "source": "osm", "source_url": "https://example.org/1", "address": "Street A 1"}
    alternate = {**base, "id": "overture:monument", "name": "Baiterek", "source": "overture", "address": "Different source address 38", "lat": 51.12821}
    safe, _, _ = apply_quality_overrides([base, alternate], {alternate["id"]: {"action": "verified_same_place", "target_id": base["id"], "reason": "Reviewed source identity"}})
    pois, _ = normalize_candidates(safe)
    assert len(pois) == 1 and len(pois[0]["source_records"]) == 2
    assert any(c["value"] == alternate["address"] for c in pois[0]["field_conflicts"])
    safe[1]["lat"] += .01
    assert len(normalize_candidates(safe)[0]) == 2


def test_flagged_cuisine_is_kept_raw_but_excluded_from_generated_retrieval_text():
    from data.collect.normalize import normalize_candidates
    row = {"id": "cafe", "name": "Cafe", "source": "osm", "source_url": "https://example.org/cafe", "lat": 51.13, "lon": 71.43,
           "category": "cafe", "raw_tags": {"cuisine": "cuisine_one;cuisine_two"}, "tags": ["cuisine=cuisine_one;cuisine_two"]}
    safe, _, _ = apply_quality_overrides([row], {"cafe": {"action": "suppress_cuisine_text", "reason": "Unverified anomalous tag"}})
    pois, _ = normalize_candidates(safe)
    assert "cuisine_one" not in pois[0]["description"]
    assert not pois[0]["tags"]
    assert pois[0]["raw_tags"]["cuisine"] == row["raw_tags"]["cuisine"]

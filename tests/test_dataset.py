"""Checks for the real collected dataset, not for synthetic fixture coverage."""

import json
from pathlib import Path

import pytest

from eval.validators import validate_pois

pytestmark = pytest.mark.dataset


def test_real_dataset_follows_contract(real_pois):
    assert not (errors := validate_pois(real_pois)), "\n".join(errors)


def test_cp1_has_at_least_300_pois(real_pois):
    assert len(real_pois) >= 300, "CP1 requires at least 300 collected POIs"


def test_cp1_description_coverage(real_pois):
    coverage = sum(bool(str(poi.get("description") or "").strip()) for poi in real_pois) / len(real_pois)
    assert coverage >= 0.60, f"Data-role DoD requires >=60% descriptions; observed {coverage:.1%}"


def test_generated_descriptions_are_labeled(real_pois):
    for poi in real_pois:
        if poi.get("description"):
            assert poi.get("description_source") in {"osm", "wikipedia", "website", "llm_generated"}, poi["id"]


def test_pois_have_plausible_astana_coordinates(real_pois):
    # Broad envelope includes the airport; the collection bbox in the plan is narrower.
    # This is a geographic sanity check, not a city administrative-boundary assertion.
    for poi in real_pois:
        assert 50.8 <= poi["lat"] <= 51.4 and 71.0 <= poi["lon"] <= 71.8, poi["id"]


def test_relevance_labels_exist_in_actual_dataset(real_pois):
    known = {poi["id"] for poi in real_pois}
    cases = json.loads((Path(__file__).resolve().parents[1] / "eval/golden_set.json").read_text(encoding="utf-8"))
    for case in cases:
        for poi_id in case["expect"].get("relevant_poi_ids", []):
            assert poi_id in known, f"{case['id']}: relevance label {poi_id} absent from current dataset"


def _companion(pytestconfig, filename):
    return Path(pytestconfig.getoption("--pois")).resolve().parent / filename


def _http_url(value):
    from urllib.parse import urlsplit

    if not isinstance(value, str) or not value.strip():
        return False
    try:
        parsed = urlsplit(value)
        return parsed.scheme in {"http", "https"} and bool(parsed.hostname)
    except ValueError:
        return False


def test_every_poi_is_inside_companion_administrative_polygon(real_pois, pytestconfig):
    """An envelope alone cannot prove membership in a city with holes/islands."""
    from shapely.geometry import Point, shape

    path = _companion(pytestconfig, "boundary.geojson")
    if not path.exists():
        pytest.skip("Administrative polygon NOT TESTED: no companion boundary.geojson")
    boundary = json.loads(path.read_text(encoding="utf-8"))
    geometry = shape(boundary["geometry"] if boundary.get("type") == "Feature" else boundary)
    assert geometry.geom_type in {"Polygon", "MultiPolygon"}
    assert not geometry.is_empty and geometry.is_valid, "Companion administrative polygon is invalid"
    outside = [poi["id"] for poi in real_pois if not geometry.covers(Point(poi["lon"], poi["lat"]))]
    assert not outside, f"POIs outside the administrative polygon: {outside[:20]} ({len(outside)} total)"


def test_source_provenance_retains_ids_links_and_explicit_license_state(real_pois):
    """Missing reuse rights must be explicit rather than silently called open data."""
    unknown_states = {"unknown", "not_specified", "unverified", "not_verified", "reuse_unverified"}
    for poi in real_pois:
        records = poi.get("source_records")
        assert isinstance(records, list) and records, f"{poi['id']}: missing source provenance"
        ids = []
        for record in records:
            assert isinstance(record, dict), poi["id"]
            assert isinstance(record.get("id"), str) and record["id"].strip(), poi["id"]
            assert isinstance(record.get("source"), str) and record["source"].strip(), poi["id"]
            assert _http_url(record.get("source_url")), f"{poi['id']}: untraceable source {record.get('id')}"
            license_value = record.get("license") or record.get("source_license")
            status = record.get("license_status") or record.get("reuse_status")
            assert (isinstance(license_value, str) and license_value.strip()) or status in unknown_states, (
                f"{poi['id']}: source {record['id']} has neither a license nor explicit unknown status"
            )
            ids.append(record["id"])
        assert len(ids) == len(set(ids)), f"{poi['id']}: repeated provenance ID"
        assert poi["id"] in ids, f"{poi['id']}: primary identity missing from source_records"


def test_description_statistics_separate_source_text_and_structured_templates(real_pois, pytestconfig):
    """Coverage may include factual templates; authored-source coverage must not."""
    described = [poi for poi in real_pois if (poi.get("description") or "").strip()]
    source_count = sum(poi.get("description_kind") == "source" for poi in described)
    template_count = sum(poi.get("description_kind") == "structured_template" for poi in described)
    generated_count = sum(poi.get("description_source") == "llm_generated" for poi in described)
    for poi in described:
        if poi.get("description_kind") == "structured_template":
            assert poi.get("description_source") != "llm_generated", poi["id"]
            detail = poi.get("description_source_detail")
            assert isinstance(detail, str) and detail.strip(), f"{poi['id']}: derived text has no explanation"
        if poi.get("description_kind") == "source":
            assert poi.get("description_source") != "llm_generated", poi["id"]
    path = _companion(pytestconfig, "stats.json")
    if path.exists():
        stats = json.loads(path.read_text(encoding="utf-8"))
        if "source_description_count" in stats:
            assert stats["source_description_count"] == source_count
        if "template_description_count" in stats:
            assert stats["template_description_count"] == template_count
        if "source_description_count" in stats and "template_description_count" in stats:
            assert source_count + template_count + generated_count == len(described), (
                "Source text, structured templates and explicitly generated text do not account for reported coverage"
            )
        if "output_count" in stats:
            assert stats["output_count"] == len(real_pois), "Statistics describe a different dataset export"


def test_wikipedia_text_keeps_article_and_contributor_attribution(real_pois):
    for poi in real_pois:
        if poi.get("description_source") != "wikipedia" or not poi.get("description"):
            continue
        attribution = poi.get("wikipedia_attribution") or poi.get("description_attribution")
        assert isinstance(attribution, dict), f"{poi['id']}: Wikipedia description lost attribution"
        assert isinstance(attribution.get("title"), str) and attribution["title"].strip(), poi["id"]
        assert _http_url(attribution.get("url") or poi.get("description_url")), poi["id"]
        license_value = attribution.get("license") or poi.get("description_license")
        assert isinstance(license_value, str) and license_value.strip(), poi["id"]
        assert _http_url(attribution.get("license_url")), f"{poi['id']}: missing text license link"
        credit = attribution.get("attribution") or attribution.get("author") or attribution.get("authors")
        assert credit, f"{poi['id']}: missing contributor credit"


def test_quarantined_sources_cannot_reappear_through_a_merged_poi(real_pois, pytestconfig):
    path = _companion(pytestconfig, "quarantined_pois.json")
    if not path.exists():
        pytest.skip("Quarantine exclusions NOT TESTED: no companion quarantined_pois.json")
    quarantined = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(quarantined, list), "Quarantine export must be a list of reviewed source records"
    rejected_ids = {row["id"] for row in quarantined}
    exported_ids = {poi["id"] for poi in real_pois}
    exported_ids.update(record["id"] for poi in real_pois for record in poi.get("source_records", []))
    assert not (leaked := rejected_ids & exported_ids), f"Quarantined sources leaked into export: {sorted(leaked)}"


def test_unknown_ratings_are_not_replaced_with_source_popularity_or_confidence(real_pois):
    no_review_ratings = {"osm", "overture", "wikidata", "wikipedia", "geonames"}
    for poi in real_pois:
        if poi.get("rating") is None:
            assert poi.get("rating_count") is None, f"{poi['id']}: review count exists without a rating"
        sources = {row.get("source") for row in poi.get("source_records", [])}
        if sources and sources <= no_review_ratings and not poi.get("rating_source"):
            assert poi.get("rating") is None and poi.get("rating_count") is None, (
                f"{poi['id']}: gazetteer/map confidence, traffic or sitelinks cannot establish visitor ratings"
            )

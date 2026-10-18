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

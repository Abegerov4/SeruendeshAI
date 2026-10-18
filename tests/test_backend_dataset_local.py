"""Actual in-process backend + real export, using its local keyword fallback.

These checks need --pois and do not claim that Chroma/hybrid RAG or an external
LLM has been tested. The fixture writes only its temporary copy of the dataset.
"""
import pytest

from eval.validators import haversine_m, validate_response

pytestmark = pytest.mark.dataset


def test_local_backend_health_counts_the_entire_real_dataset(qa_backend, real_pois):
    qa_backend.set_pois(real_pois)
    response = qa_backend.client.get("/api/health")
    assert response.status_code == 200
    health = response.json()
    assert health["status"] == "ok"
    assert health["pois"] == len(real_pois), "Backend still reads a fixture or a truncated export"
    assert health["llm"] == "disabled", "Local dataset QA must not depend on a provider call"


@pytest.mark.parametrize("anchor_fraction", [0.2, 0.8])
def test_map_neighborhood_matches_real_ids_facts_and_independent_radius(qa_backend, real_pois, anchor_fraction):
    qa_backend.set_pois(real_pois)
    anchor = real_pois[int((len(real_pois) - 1) * anchor_fraction)]
    lat, lon = round(anchor["lat"], 3), round(anchor["lon"], 3)
    radius, limit = 250, 5000
    distances = {poi["id"]: haversine_m(lat, lon, poi["lat"], poi["lon"]) for poi in real_pois}
    # The current fallback truncates distances to whole metres. Allow only that
    # numeric boundary tolerance; use an independent oracle for the geometry.
    inside = {ident for ident, distance in distances.items() if distance < radius - 1}
    possible = {ident for ident, distance in distances.items() if distance <= radius + 1}
    response = qa_backend.client.get("/api/pois", params={"lat": lat, "lon": lon, "radius_m": radius, "limit": limit})
    assert response.status_code == 200
    markers = response.json()
    assert isinstance(markers, list) and markers, "A neighborhood containing a source POI must return markers"
    by_id = {poi["id"]: poi for poi in real_pois}
    marker_ids = [marker["id"] for marker in markers]
    assert len(marker_ids) <= limit, "Map exceeded the requested result limit"
    assert len(marker_ids) == len(set(marker_ids)), "Map returned duplicate identities"
    assert set(marker_ids) <= possible, "Map returned an unknown or out-of-radius identity"
    if len(possible) <= limit:
        assert inside <= set(marker_ids), "Map silently omitted real nearby POIs below the requested result limit"
    elif len(inside) >= limit:
        # Only points definitely inside can prove that a full page is required.
        # The 1m uncertainty annulus must not create a false missing-result fail.
        assert len(markers) == limit
    for marker in markers:
        source = by_id[marker["id"]]
        assert marker["name"] == source["name"]
        assert marker["category"] == source["category"]
        assert marker["lat"] == pytest.approx(source["lat"], abs=1e-9, rel=0)
        assert marker["lon"] == pytest.approx(source["lon"], abs=1e-9, rel=0)


def test_real_dataset_recommendations_preserve_ids_facts_and_unknown_hours(qa_backend, real_pois):
    qa_backend.set_pois(real_pois)
    # Choose from the export rather than pinning a particular current venue ID.
    unknown_parks = [poi for poi in real_pois if poi["category"] == "park" and not poi.get("opening_hours")]
    assert unknown_parks, "The export needs a real unknown-hours park to exercise this scenario"
    anchor = max(unknown_parks, key=lambda poi: len(poi["name"].split()))
    request = {
        "query": f"Хочу погулять в парке «{anchor['name']}».",
        "location": {"lat": round(anchor["lat"], 3), "lon": round(anchor["lon"], 3)},
        "time_budget_min": 90, "mode": "walk", "lang": "ru",
        "now": "2026-10-18T12:00:00+05:00",
    }
    response = qa_backend.client.post("/api/recommend", json=request)
    assert response.status_code == 200
    body = response.json()
    errors = validate_response(body, request, real_pois, {"outcome": "recommendations", "count_between": [1, 3]})
    assert not errors, "\n".join(errors)
    by_id = {poi["id"]: poi for poi in real_pois}
    unknown_cards = [card for card in body["recommendations"] if not by_id[card["poi_id"]].get("opening_hours")]
    assert unknown_cards, "Scenario did not exercise any actual unknown-hours recommendation"
    for card in unknown_cards:
        assert card["open_status"] == "unknown"
        assert card["open_confidence"] == "none"

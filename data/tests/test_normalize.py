"""Guard real collection failures: bad coordinates, false metadata and over-merging."""
from copy import deepcopy

from data.collect.normalize import normalize_candidates


def candidate(ident="osm:node/1", name="Точка кофе", lat=51.13, lon=71.43, **extra):
    return {"id": ident, "name": name, "lat": lat, "lon": lon, "category": "cafe",
            "source": "osm", "source_url": "https://www.openstreetmap.org/node/1", **extra}


def run(rows, **kwargs):
    return normalize_candidates(rows, collected_at="2026-10-18", **kwargs)


def test_invalid_and_nameless_records_are_excluded_without_mutating_input():
    rows = [candidate(), candidate("bad", lat=float("nan")), candidate("empty", name=" "),
            candidate("bool", lat=True), candidate("far", lat=43.25, lon=76.9)]
    original = deepcopy(rows[0])
    pois, report = run(rows)
    assert [p["id"] for p in pois] == ["osm:node/1"]
    assert rows[0] == original
    assert report["rejected_count"] == 4


def test_actual_boundary_excludes_nearby_non_city_records_and_keeps_edge():
    polygon = {"type": "Polygon", "coordinates": [[[71.40, 51.10], [71.50, 51.10],
                 [71.50, 51.20], [71.40, 51.20], [71.40, 51.10]]]}
    pois, _ = run([candidate("inside"), candidate("outside", lon=71.60),
                   candidate("edge", name="Другое кафе", lon=71.40)], boundary=polygon)
    assert {p["id"] for p in pois} == {"inside", "edge"}


def test_cross_source_duplicate_merges_missing_facts_and_keeps_attribution():
    osm = candidate()
    overture = candidate("overture:abc", name="Точка Кофе", lat=51.1301,
                         source="overture", source_url="https://docs.overturemaps.org/guides/places/",
                         website="https://coffee.example", source_license="CDLA-Permissive-2.0")
    pois, report = run([overture, osm])
    assert len(pois) == 1 and pois[0]["id"] == "osm:node/1"
    assert pois[0]["website"] == "https://coffee.example"
    assert {s["id"] for s in pois[0]["source_records"]} == {"osm:node/1", "overture:abc"}
    assert report["merged_count"] == 1


def test_explicit_russian_osm_alias_matches_cross_source_name():
    osm = candidate(name="Бәйтерек", category="monument", raw_tags={"name:ru": "Байтерек", "name:kk": "Бәйтерек"})
    wiki = candidate("wikipedia:ru:123", name="Байтерек", category="other", source="wikipedia")
    pois, report = run([osm, wiki])
    assert len(pois) == 1
    assert "Байтерек" in pois[0]["aliases"]
    assert report["merged_count"] == 1


def test_chain_branches_different_floors_and_distinct_colocated_venues_survive():
    rows = [candidate("floor1", raw_tags={"level": "1"}),
            candidate("floor2", raw_tags={"level": "2"}),
            candidate("far_branch", lat=51.14),
            candidate("other", name="Другой ресторан", category="restaurant")]
    pois, _ = run(rows)
    assert len(pois) == 4


def test_same_name_with_different_explicit_addresses_is_not_collapsed():
    pois, _ = run([candidate("a", address="ул. А, 1"), candidate("b", address="ул. А, 3")])
    assert len(pois) == 2


def test_validated_directory_identity_merges_with_coordinate_parent_and_keeps_conflict():
    base = candidate(address="Kabanbay Batyr Avenue 62")
    fact = candidate("mega_silkway:1", source="mega_silkway", address="MEGA Silk Way, floor 1",
                     coordinate_source_id=base["id"], coordinate_match_verified=True, coordinate_match_method="mall_scope")
    pois, _ = run([base, fact])
    assert len(pois) == 1
    assert {r["source"] for r in pois[0]["source_records"]} == {"osm", "mega_silkway"}
    assert any(c["field"] == "address" for c in pois[0]["field_conflicts"])
    fact["coordinate_match_verified"] = False
    assert len(run([base, fact])[0]) == 2


def test_unknown_facts_remain_null_and_template_contains_only_supported_facts():
    pois, _ = run([candidate(website="javascript:bad", raw_tags={"cuisine": "coffee_shop"})])
    poi = pois[0]
    assert poi["opening_hours"] is None and poi["rating"] is None
    assert poi["wheelchair"] is None and poi["kid_friendly"] is None and poi["website"] is None
    assert poi["description_kind"] == "structured_template"
    assert poi["description_source"] != "llm_generated"
    assert "розет" not in poi["description"].lower() and "тих" not in poi["description"].lower()


def test_source_description_is_preserved_and_not_reported_as_a_template():
    pois, report = run([candidate(description="В описании источника указана выставка.",
                                   description_source="wikipedia")])
    assert pois[0]["description"] == "В описании источника указана выставка."
    assert pois[0]["description_kind"] == "source"
    assert report["source_description_count"] == 1


def test_unknown_accessibility_and_child_suitability_are_not_negative_claims():
    pois, _ = run([candidate("play", name="Площадка", category="playground"), candidate()])
    by_id = {p["id"]: p for p in pois}
    assert by_id["play"]["kid_friendly"] is True
    assert by_id["osm:node/1"]["kid_friendly"] is None


def test_explicit_negative_child_suitability_is_not_overridden_by_category():
    pois, _ = run([candidate(category="playground", kid_friendly=False)])
    assert pois[0]["kid_friendly"] is False


def test_cached_rerun_is_order_independent_and_does_not_drop_same_id_metadata():
    a = candidate(description="Кофейня.", description_source="osm")
    b = candidate(phone="+7 7172 123456")
    forward, _ = run([a, b])
    backward, _ = run([b, a])
    assert forward == backward
    assert len(forward) == 1 and forward[0]["phone"] == "+7 7172 123456"

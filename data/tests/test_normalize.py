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


def test_secondary_source_name_survives_as_searchable_alias():
    base = candidate(name="MEGA Silk Way", name_en="Mega Silkway", category="mall")
    alternate = candidate("osm:node/2", name="Мега Силк Вей", category="mall",
                          name_en="MEGA Silk Way Shopping Centre", name_kk="МЕГА сауда орталығы",
                          verified_identity_parent_id=base["id"])
    pois, _ = run([base, alternate])
    assert len(pois) == 1
    assert {"MEGA Silk Way", "Мега Силк Вей"} <= set(pois[0]["aliases"])
    assert {"Mega Silkway", "MEGA Silk Way Shopping Centre", "МЕГА сауда орталығы"} <= set(pois[0]["aliases"])


def test_wifi_fact_from_secondary_source_keeps_its_own_provenance():
    base = candidate()
    alternate = candidate("osm:node/2", source_url="https://www.openstreetmap.org/node/2",
                          collected_at="2026-10-10", source_updated_at="2026-10-09",
                          raw_tags={"internet_access": "wlan", "internet_access:fee": "customers"})
    pois, _ = run([base, alternate])
    assert len(pois) == 1
    assert {"Wi-Fi", "интернет"} <= set(pois[0]["tags"])
    assert {"field": "internet_access", "value": "wlan", "source_id": "osm:node/2",
            "source_url": "https://www.openstreetmap.org/node/2", "collected_at": "2026-10-10",
            "source_updated_at": "2026-10-09"} in pois[0]["amenity_facts"]
    assert not any("free" in tag.casefold() or "бесплат" in tag.casefold() for tag in pois[0]["tags"])


def test_conflicting_internet_sources_do_not_produce_unqualified_wifi_tag():
    yes = candidate(raw_tags={"internet_access": "wlan"})
    no = candidate("osm:node/2", raw_tags={"internet_access": "no"})
    pois, _ = run([yes, no])
    assert len(pois) == 1
    assert "Wi-Fi" not in pois[0]["tags"]
    assert {fact["value"] for fact in pois[0]["amenity_facts"]} == {"wlan", "no"}
    assert "conflicting_internet_access" in pois[0]["quality_flags"]


def test_held_source_description_is_auditable_and_not_used_as_description():
    raw = candidate(held_description="Disputed identity text.", description_review_status="pending",
                    description_review_reason="Source title and text identify different museums.",
                    description_url="https://example.org/museum", description_license="not_specified",
                    description_attribution={"language": "ru", "raw_cache_sha256": "original-cache-hash"},
                    description_review_evidence={"resolved_description_html": "<p>Disputed identity text.</p>"})
    pois, _ = run([raw])
    assert pois[0]["description_kind"] == "structured_template"
    assert "Disputed identity" not in pois[0]["description"]
    assert pois[0]["held_descriptions"][0]["text"] == "Disputed identity text."
    assert pois[0]["held_descriptions"][0]["source_id"] == raw["id"]
    assert "description_attribution" not in pois[0]
    base = candidate("osm:node/2", description="Existing source text.", description_source="osm")
    merged = run([base, raw])[0][0]
    held = merged["held_descriptions"][0]
    assert held["description_attribution"] == {"language": "ru", "raw_cache_sha256": "original-cache-hash"}
    assert held["description_license"] == "not_specified"
    assert held["review_evidence"] == {"resolved_description_html": "<p>Disputed identity text.</p>"}


def test_unverified_provider_category_does_not_confirm_child_suitability():
    raw = candidate(category="playground", source="overture", quality_flags=["source_classification_unverified"])
    poi = run([raw])[0][0]
    assert poi["category"] == "playground"
    assert poi["kid_friendly"] is None
    assert "source_classification_unverified" in poi["quality_flags"]


def test_derived_metadata_does_not_change_existing_primary_identity():
    base = candidate("osm:node/2", aliases=["Coffee point"], phone="111")
    secondary = candidate("osm:node/1", raw_tags={"internet_access": "wlan"}, phone="222")
    pois, _ = run([base, secondary])
    assert pois[0]["id"] == "osm:node/2"
    assert pois[0]["phone"] == "111"
    assert {"field": "phone", "value": "222", "source_id": "osm:node/1"} in pois[0]["field_conflicts"]


def test_preserved_search_names_do_not_expand_identity_matching_mid_pass():
    base = candidate(name="Alpha", name_en="Alpha")
    translated = candidate("wikipedia:1", name="Beta", name_en="Alpha", source="wikipedia")
    possible_namesake = candidate("overture:1", name="Beta", source="overture")
    pois, _ = run([base, translated, possible_namesake])
    assert {p["id"] for p in pois} == {base["id"], "overture:1"}
    assert "Beta" in next(p for p in pois if p["id"] == base["id"])["aliases"]


def test_hours_field_provenance_survives_merge_without_rebuild_freshening():
    from data.collect.normalize import normalize_candidates
    rows = [dict(id="osm:way/101", name="Tower", category="monument", lat=51.12, lon=71.43,
                 source="osm", source_url="https://example.org/osm", raw_tags={}, opening_hours=None),
            dict(id="citypass:57", name="Tower", category="monument", lat=51.12001, lon=71.43,
                 source="citypass", source_url="https://example.org/citypass", raw_tags={"check_date:opening_hours": "2020-01-01"},
                 collected_at="2021-02-01", source_updated_at="2019-12-01", opening_hours="Mo-Su 09:00-21:00")]
    pois, _ = normalize_candidates(rows, collected_at="2026-10-19")
    assert len(pois) == 1
    evidence = [e for e in pois[0].get("field_evidence", []) if e["field"] == "opening_hours"]
    assert evidence, "Merged hours need their field source and dates"
    assert evidence[0]["source_id"] == "citypass:57"
    assert evidence[0]["acquired_at"] == "2021-02-01"
    assert evidence[0]["checked_at"] == "2020-01-01"
    assert evidence[0]["source_updated_at"] == "2019-12-01"

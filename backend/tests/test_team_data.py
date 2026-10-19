"""The canonical team dataset must survive adaptation without invented facts."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest


import pytest as _pytest


@_pytest.fixture(scope="module", autouse=True)
def canonical_snapshot_mode():
    """These tests cover the team catalogue runtime (opt-in in production)."""
    with _pytest.MonkeyPatch.context() as mp:
        mp.setenv("DATA_SNAPSHOT_MODE", "canonical")
        yield


def record(poi_id="osm:node/10", *, category="cafe", **fields):
    return {
        "id": poi_id, "name": "Example Café", "lat": 51.128, "lon": 71.430,
        "category": category, "source": "osm", "source_url": "https://example.test/10",
        "name_en": "Example Café", "name_kk": "Мысал", "address": None,
        "opening_hours": None, "phone": None, "website": None, "wheelchair": None,
        "kid_friendly": None, "rating": None, "rating_count": None,
        "tags": [], "raw_tags": {}, "source_records": [
            {"id": poi_id, "source": "osm", "source_url": "https://example.test/10",
             "license": "ODbL-1.0", "collected_at": "2026-10-18", "source_updated_at": None}
        ], "description": None, "description_source": None, "description_kind": None,
        "collected_at": "2026-10-19", "updated_at": "2026-10-19", "source_updated_at": None,
        **fields,
    }


def snapshot(tmp_path, rows, quarantine=None):
    from app.team_data import load_team_snapshot

    path = tmp_path / "pois.json"
    path.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    kwargs = {}
    if quarantine is not None:
        qpath = tmp_path / "quarantine.json"
        qpath.write_text(json.dumps(quarantine), encoding="utf-8")
        kwargs["quarantine_path"] = qpath
    return path, load_team_snapshot(path, **kwargs)


def test_explicit_lifecycle_exclusion_hides_origin_but_preserves_archive_ids(tmp_path):
    _, (pois, gazetteer, manifest) = snapshot(tmp_path, [record()], [{
        "id":"osm:node/10", "reason":"Source confirms permanent closure",
        "reason_code":"confirmed_permanent_closure", "exclude_from_origins":True}])
    assert pois == [] and gazetteer == []
    assert manifest["preserved_source_ids_count"] == manifest["raw_source_ids_count"] == 1
    assert manifest["archived_canonical_ids"] == ["osm:node/10"]


def test_adapter_preserves_canonical_identity_provenance_and_unknown_facts(tmp_path):
    row = record(
        aliases=["Бұрынғы атауы"], opening_hours="Mo-Fr 09:00-18:00",
        description="An attributed description.", description_source="wikipedia",
        description_url="https://en.wikipedia.org/wiki/Example",
        description_license="CC-BY-SA-4.0", wheelchair="no", kid_friendly=False,
        raw_tags={"wheelchair": "no", "fee": "yes", "outdoor_seating": "no"},
    )
    path, (pois, gazetteer, manifest) = snapshot(tmp_path, [row])
    poi = pois[0]
    assert poi["id"] == "osm:node/10" and poi["name"] == "Example Café"
    assert poi["names"] == {"en": "Example Café", "kk": "Мысал"}
    for key in ("aliases", "source_records", "description", "description_source", "description_url",
                "description_license", "opening_hours", "kid_friendly", "raw_tags"):
        assert poi[key] == row[key]
    assert poi["features"] == {"wheelchair": "no", "free": False, "outdoor_seating": False}
    assert poi["indoor"] is None and poi["popularity"] == 0.0
    assert poi["sources"] == ["osm"]
    assert poi["source_ids"] == ["osm:node/10"]
    assert "osm:n10" in poi["id_aliases"]
    assert gazetteer[0]["poi_id"] == "osm:node/10"
    assert "бұрынғы атауы" not in gazetteer[0]["keys"]  # Kazakh letters are folded for matching.
    assert "бурынгы атауы" in gazetteer[0]["keys"]
    assert manifest["canonical_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert manifest["canonical_count"] == manifest["adapted_count"] == 1
    assert manifest["raw_source_ids_count"] == manifest["preserved_source_ids_count"] == 1
    assert manifest["dense_disabled"] and manifest["dense_disabled_reason"]
    assert not any(k.startswith("embedding_") for k in manifest)
    assert json.loads(path.read_text(encoding="utf-8")) == [row]


@pytest.mark.parametrize("category,want", [
    ("attraction", "landmark"), ("sport", "active"), ("nightlife", "nightclub"),
    ("cafe", "cafe"),
])
def test_adapter_maps_only_the_explicit_coarse_category(tmp_path, category, want):
    _, (pois, _, _) = snapshot(tmp_path, [record(category=category, name="Museum and free Wi-Fi playground")])
    assert pois[0]["category"] == want
    assert pois[0]["canonical_category"] == category
    assert pois[0]["features"] == {}  # Name text does not establish amenities or finer classes.


@pytest.mark.parametrize("access,fee,want", [
    (["wlan"], None, {"wifi": True}),
    (["yes"], None, {}),
    (["no"], None, {"wifi": False}),
    (["wlan", "no"], None, {}),
    (["wlan", "unknown"], None, {}),
    ([], "no", {}),
    (["yes"], "no", {}),
    (["wlan"], "customers", {"wifi": True}),
])
def test_wifi_requires_nonconflicting_wlan_and_internet_fee_is_not_venue_fee(tmp_path, access, fee, want):
    facts = [{"field": "internet_access", "value": v, "source_id": "osm:node/10",
              "source_url": "https://example.test/10"} for v in access]
    if fee:
        facts.append({"field": "internet_access:fee", "value": fee, "source_id": "osm:node/10",
                      "source_url": "https://example.test/10"})
    _, (pois, _, _) = snapshot(tmp_path, [record(
        amenity_facts=facts,
        raw_tags={"internet_access": access[0] if access else "", "internet_access:fee": fee},
    )])
    assert pois[0]["features"] == want
    assert pois[0]["amenity_facts"] == facts


def test_conflicting_hours_and_accessibility_stay_unknown_in_api_fields(tmp_path):
    _, (pois, _, _) = snapshot(tmp_path, [record(
        opening_hours="24/7", wheelchair="yes",
        raw_tags={"opening_hours": "24/7", "wheelchair": "yes", "fee": "no"},
        field_conflicts=[
            {"field": "opening_hours", "value": "Mo-Fr 09:00-18:00", "source_id": "other:1"},
            {"field": "wheelchair", "value": "no", "source_id": "other:1"},
            {"field": "fee", "value": "yes", "source_id": "other:1"},
        ],
    )])
    poi = pois[0]
    assert poi["opening_hours"] is None and poi["canonical_opening_hours"] == "24/7"
    assert poi["features"] == {}
    assert poi["canonical_wheelchair"] == "yes" and poi["wheelchair"] is None
    assert len(poi["field_conflicts"]) == 3


def test_quarantine_matches_old_ids_and_merged_source_ids_without_dropping_origins(tmp_path):
    rows = [
        record("osm:way/20", name="First"),
        record("overture:3dda9f68-24a5-4047-a0a0-101ce0a047fc", name="Second"),
        record("osm:way/30", name="Third", source_records=[
            {"id": "osm:way/30", "source": "osm"},
            {"id": "citypass:57", "source": "citypass"},
        ]),
        record("osm:node/40", name="Kept"),
    ]
    path, (pois, gazetteer, manifest) = snapshot(tmp_path, rows, [
        {"id": "osm:w20", "reason": "reviewed"},
        {"id": "ov:3dda9f68-24a5-40", "reason": "reviewed"},
        {"id": "cp:57", "reason": "reviewed"},
    ])
    assert [p["id"] for p in pois] == ["osm:node/40"]
    assert len(gazetteer) == 4
    assert all(g["origin_only"] for g in gazetteer if g["id"] != "osm:node/40")
    assert "citypass:57" in next(g for g in gazetteer if g["id"] == "osm:way/30")["source_ids"]
    assert manifest["excluded_by_reason"] == {"quarantine": 3}
    assert manifest["quarantine_unmatched_ids"] == []
    assert manifest["raw_source_ids_count"] == manifest["preserved_source_ids_count"] == 5
    assert json.loads(path.read_text(encoding="utf-8")) == rows


def test_other_and_unverified_playground_remain_origin_anchors(tmp_path):
    rows = [
        record("osm:node/10", category="other", name="Hotel Example"),
        record("overture:20", category="playground", name="PS5", quality_flags=["source_classification_unverified"]),
        record("osm:node/30", category="playground", name="Actual Playground", kid_friendly=True),
    ]
    _, (pois, gazetteer, manifest) = snapshot(tmp_path, rows)
    assert [p["id"] for p in pois] == ["osm:node/30"]
    assert [(g["id"], g["origin_only"]) for g in gazetteer] == [
        ("osm:node/10", True), ("overture:20", True), ("osm:node/30", False),
    ]
    assert manifest["excluded_by_reason"] == {"origin_only_category": 1, "unverified_playground": 1}


def test_ambiguous_name_and_truncated_id_aliases_are_reported_without_arbitrary_resolution(tmp_path):
    rows = [
        record("overture:12345678-1234-12aa-a", name="One", aliases=["Shared Brand"]),
        record("overture:12345678-1234-12bb-b", name="Two", aliases=["Shared Brand"]),
    ]
    _, (pois, gazetteer, manifest) = snapshot(tmp_path, rows)
    assert len(pois) == 2 and len(gazetteer) == 2
    assert manifest["alias_collisions"]["shared brand"] == [rows[0]["id"], rows[1]["id"]]
    assert manifest["id_alias_collisions"]["ov:12345678-1234-12"] == [rows[0]["id"], rows[1]["id"]]
    assert all("shared brand" not in g["keys"] for g in gazetteer)
    assert [g["ambiguous_keys"] for g in gazetteer] == [["example café", "shared brand", "мысал"],
                                                      ["example café", "shared brand", "мысал"]]
    assert all("ov:12345678-1234-12" not in g["keys"] for g in gazetteer)
    assert all("ov:12345678-1234-12" not in p["id_aliases"] for p in pois)
    assert all(g["id"] in g["keys"] for g in gazetteer)


def test_real_master_is_preserved_and_all_source_ids_remain_available():
    from app.team_data import load_team_snapshot

    root = Path(__file__).resolve().parents[2]
    path = root / "data/processed/pois.json"
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    pois, gazetteer, manifest = load_team_snapshot(path, quarantine_path=root / "data/quarantine.json")
    assert manifest["canonical_count"] == 14006
    assert manifest["raw_source_ids_count"] == manifest["preserved_source_ids_count"] == 14607
    assert manifest["adapted_count"] == len(pois) == 2742
    assert len(gazetteer) == 13999
    assert manifest["archived_canonical_ids"] == ["citypass:119","citypass:142","citypass:94",
        "overture:3105494a-8102-4450-9d78-12ca652ce768", "overture:5a405c91-d5d6-47ee-9b9b-546134f0505d",
        "overture:a4de9304-82bf-4d82-b811-1a18cc29a44e", "overture:dc97b064-be10-46d8-9168-76343e2e115d"]
    assert manifest["excluded_by_reason"] == {
        "origin_only_category": 11246, "quarantine": 14, "unverified_playground": 3, "suspicious_classification": 1,
    }
    assert manifest["quarantine_unmatched_ids"] == []
    # The current directory classifies Loft Park as a lottery club. Its name
    # remains a usable origin, while food recommendations must withhold it.
    assert "osm:node/13448013130" not in {p["id"] for p in pois}
    assert "osm:node/13448013130" in {p["id"] for p in gazetteer}
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before



def test_hours_source_comes_from_field_evidence_not_entity_primary(tmp_path):
    _, (pois, _, _) = snapshot(tmp_path, [record(
        opening_hours="Mo-Su 09:00-21:00", source="osm",
        field_evidence=[{"field": "opening_hours", "value": "Mo-Su 09:00-21:00", "source": "citypass",
                         "source_id": "citypass:57", "source_url": "https://example.org/citypass/57",
                         "acquired_at": "2026-10-18", "checked_at": "2026-09-30"}],
    )])
    assert pois[0]["hours_source"] == "citypass"
    assert pois[0]["hours_source_url"] == "https://example.org/citypass/57"
    assert pois[0]["check_date"] == "2026-09-30"
    assert pois[0]["hours_acquired_at"] == "2026-10-18"


def test_region_name_with_unverified_park_category_is_review_only(tmp_path):
    rows = [record("overture:region", category="park", name="Северный Казахстан, Казахстан",
                   quality_flags=["source_classification_unverified"]),
            record("overture:normal", category="park", name="Парк у дома",
                   quality_flags=["source_classification_unverified"])]
    _, (pois, gazetteer, _) = snapshot(tmp_path, rows)
    assert [p["id"] for p in pois] == ["overture:normal"]
    assert len(gazetteer) == 2
    assert pois[0]["classification_status"] == "unverified"


def test_current_baiterek_and_all_directory_hours_have_field_source():
    from app.team_data import load_team_snapshot
    root = Path(__file__).resolve().parents[2]
    pois, _, _ = load_team_snapshot(root / "data/processed/pois.json", quarantine_path=root / "data/quarantine.json")
    baiterek = next(p for p in pois if p["id"] == "osm:way/230401645")
    assert baiterek["hours_source"] == "citypass"
    assert baiterek["hours_source_id"] == "citypass:57"
    assert baiterek["hours_source_url"] == "https://astana.citypass.kz/ru/attractions/bayterek"
    assert baiterek["check_date"] is None  # cache acquisition is not a source check
    known = [p for p in pois if p.get("opening_hours") and p.get("source") in {"citypass", "dodo"}]
    assert len(known) == 30  # reviewed supplements add one previously unknown branch schedule
    for p in known:
        if p.get("fact_reviews"):
            accepted = [r for r in p["fact_reviews"] if r["field"] == "opening_hours" and r["status"] == "accepted"]
            assert accepted and p["hours_source"] == accepted[-1]["source"]
        elif p["hours_source"] == "reviewed branch source":
            proof = [f for f in p["place_details"]["facts"] if f["field"] == "opening_hours"]
            assert proof and proof[0]["value"] == p["opening_hours"]
            assert p["check_date"] == proof[0]["source"]["checked_at"]
        else:
            assert p["hours_source"] == p["source"]
        assert p["hours_source_url"]
    assert baiterek["opening_hours"] is None  # current source conflict is explicit


def test_accepted_source_review_overlay_updates_runtime_without_rewriting_master(tmp_path):
    from app.team_data import load_team_snapshot
    path, _ = snapshot(tmp_path, [record()])
    before = path.read_bytes()
    review = {"schema_version": 1, "canonical_sha256": hashlib.sha256(before).hexdigest(), "reviews": [
        {"canonical_id": "osm:node/10", "field": "opening_hours", "value": "Mo-Su 09:00-21:00",
         "status": "accepted", "source": "official_venue", "source_id": "official:10",
         "source_url": "https://example.org/venue/hours", "checked_at": "2026-10-19",
         "reviewed_by": "curator", "evidence_excerpt": "Open daily from nine to twenty-one"}]}
    (tmp_path / "fact_reviews.json").write_text(json.dumps(review))
    pois, _, _ = load_team_snapshot(path)
    assert pois[0]["opening_hours"] == "Mo-Su 09:00-21:00"
    assert pois[0]["hours_source"] == "official_venue"
    assert pois[0]["check_date"] == "2026-10-19"
    assert path.read_bytes() == before
    review["canonical_sha256"] = "stale"
    (tmp_path / "fact_reviews.json").write_text(json.dumps(review))
    with pytest.raises(ValueError, match="snapshot hash"):
        load_team_snapshot(path)


def reviewed(field, value, **extra):
    return {"canonical_id": "osm:node/10", "field": field, "value": value, "status": "accepted",
            "source": "official_venue", "source_id": "official:10", "source_url": "https://example.org/venue",
            "checked_at": "2026-10-19", "reviewed_by": "curator", "evidence_excerpt": "Explicit source assertion", **extra}


def write_reviews(path, reviews):
    path.with_name("fact_reviews.json").write_text(json.dumps({"schema_version": 1,
        "canonical_sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "reviews": reviews}))


def test_explicit_wifi_conflict_resolution_clears_only_resolved_flag(tmp_path):
    from app.team_data import load_team_snapshot
    row = record(raw_tags={"internet_access": "no"},
                 quality_flags=["conflicting_internet_access", "source_classification_unverified"],
                 field_conflicts=[{"field": "internet_access", "value": "wlan", "source_id": "source:old"}])
    path, _ = snapshot(tmp_path, [row])
    before = path.read_bytes()
    write_reviews(path, [reviewed("internet_access", "wlan", resolves_conflicts=True,
                                 resolution_reason="Current official page resolves the older source disagreement",
                                 resolved_source_ids=["source:old"])])
    pois, _, _ = load_team_snapshot(path)
    assert pois[0]["features"].get("wifi") is True
    assert pois[0]["quality_flags"] == ["source_classification_unverified"]
    assert "conflicting_internet_access" in pois[0]["canonical_quality_flags"]
    assert path.read_bytes() == before


def test_curator_identity_overlay_exposes_reviewed_category_name_and_aliases(tmp_path):
    from app.team_data import load_team_snapshot
    path, _ = snapshot(tmp_path, [record(category="other", name="Old building name", aliases=["Old alias"])])
    before = path.read_bytes()
    write_reviews(path, [reviewed("category", "museum"), reviewed("name", "Alem.AI"),
                         reviewed("aliases", ["Alem AI", "Әлем AI"])])
    pois, gazetteer, manifest = load_team_snapshot(path)
    assert len(pois) == 1 and pois[0]["category"] == "museum"
    assert pois[0]["name"] == "Alem.AI"
    assert pois[0]["aliases"] == ["Alem AI", "Әлем AI"]
    assert pois[0]["canonical_category"] == "other"
    assert pois[0]["canonical_name"] == "Old building name"
    assert pois[0]["canonical_aliases"] == ["Old alias"]
    assert gazetteer[0]["origin_only"] is False
    assert manifest["preserved_source_ids_count"] == 1
    assert path.read_bytes() == before


@pytest.mark.parametrize("field,value", [("category", "invented_premium_place"), ("category", 7),
                                         ("name", "  "), ("name", "<b>Place</b>"),
                                         ("aliases", "single string"), ("aliases", ["same", "same"]),
                                         ("aliases", [""]), ("aliases", ["valid", 3])])
def test_curator_identity_overlay_rejects_invalid_category_name_and_aliases(tmp_path, field, value):
    from app.team_data import load_team_snapshot
    path, _ = snapshot(tmp_path, [record()])
    write_reviews(path, [reviewed(field, value)])
    with pytest.raises(ValueError):
        load_team_snapshot(path)


def test_wifi_flag_from_amenity_disagreement_requires_every_source_to_resolve(tmp_path):
    from app.team_data import load_team_snapshot
    facts = [{"field": "internet_access", "value": value, "source_id": ident,
              "source_url": "https://example.org/" + ident} for ident, value in (("old:1", "no"), ("old:2", "wlan"))]
    path, _ = snapshot(tmp_path, [record(quality_flags=["conflicting_internet_access"], amenity_facts=facts)])
    write_reviews(path, [reviewed("internet_access", "wlan", resolves_conflicts=True,
                                 resolution_reason="Current venue page checked", resolved_source_ids=["old:1"])])
    with pytest.raises(ValueError, match="every disputed source ID"):
        load_team_snapshot(path)
    write_reviews(path, [reviewed("internet_access", "wlan", resolves_conflicts=True,
                                 resolution_reason="Current venue page checked", resolved_source_ids=["old:1", "old:2"])])
    pois, _, _ = load_team_snapshot(path)
    assert pois[0]["features"].get("wifi") is True
    assert pois[0]["canonical_amenity_facts"] == facts

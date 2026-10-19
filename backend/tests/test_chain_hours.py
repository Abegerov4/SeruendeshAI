"""Chain branch lists may fill opening hours only for a place that unambiguously is that branch."""
from __future__ import annotations

import datetime as dt

import opening_hours as oh
import pytest

from pipeline import chain_hours as ch


@pytest.mark.parametrize("raw, expected", [
    ("Mon-Sun 08:00-24:00", "Mo-Su 08:00-24:00"),
    ("Mon-Sun 08:00-00:00", "Mo-Su 08:00-24:00"),
    ("Mon-Sun 00:00-00:00", None),
    ("Mon-Fri 09:00-18:00", "Mo-Fr 09:00-18:00"),
    ("Mon-Fri 09:00-18:00; Sat 10:00-16:00", "Mo-Fr 09:00-18:00; Sa 10:00-16:00"),
    ("Mon-Sun 22:00-02:00", "Mo-Su 22:00-02:00"),
    ("Ежедневно", None), ("", None), (None, None), ("Mon-Sun 10:00-10:00", None), ("Mon-Sun 25:00-26:00", None),
])
def test_coffeeboom_hours(raw, expected):
    assert ch.coffeeboom_hours(raw) == expected


def shop(ident, lat, lon, work="Mon-Sun 08:00-24:00", status="1", address="Астана", phone=""):
    return {"id": ident, "status": status, "name": f"Shop {ident}", "address": address, "lat": str(lat),
            "lng": str(lon), "work_time": work, "phone": phone, "format": {"code": "CB"}, "update_datetime": "2026-08-06"}


def test_parse_keeps_only_active_astana_branches():
    payload = {"data": {"coffeeshops": {"1": shop("1", 51.13, 71.40), "2": shop("2", 51.13, 71.40, status="0"),
                                        "3": shop("3", 43.24, 76.89), "4": {**shop("4", 51.1, 71.4), "lat": "x"}}}}
    assert [b["branch_id"] for b in ch.parse_coffeeboom(payload)] == ["1"]
    with pytest.raises(ValueError):
        ch.parse_coffeeboom({"data": {"result": 0}})


@pytest.mark.parametrize("address, number", [
    ("Астана, Тұран даңғылы, 43В", "43в"), ("Dostyq St 9", "9"), ("Td Ramstor, микрорайон Самал 11", "11"),
    ("Астана, Анет баба көшесі, 7/2", "7/2"), ("Астана", None), (None, None),
])
def test_house_number(address, number):
    assert ch.house_number(address) == number


def poi(ident, lat, lon, name="Coffee BOOM", hours=None, address=None, phone=None):
    return {"id": ident, "name": name, "brand": None, "lat": lat, "lon": lon, "opening_hours": hours,
            "address": address, "phone": phone, "sources": ["osm"]}


def snap(*branches):
    payload = {"data": {"coffeeshops": {b["id"]: b for b in branches}}}
    return ch.snapshot({"coffeeboom": ch.parse_coffeeboom(payload)}, {"coffeeboom": "2026-10-19"})


def test_close_unique_branch_fills_hours_with_evidence():
    p = poi("osm:1", 51.13, 71.40)
    report = ch.apply([p], snap(shop("1", 51.1301, 71.4001, "Mon-Sun 10:00-22:00"), shop("2", 51.14, 71.42)))
    assert p["opening_hours"] == "Mo-Su 10:00-22:00"
    assert p["hours_source"] == "coffeeboom.kz" and p["hours_source_url"].startswith("https://coffeeboom.kz/")
    assert p["check_date"] == "2026-10-19" and "coffeeboom.kz" in p["sources"]
    assert p["hours_evidence"]["match_method"] == "coordinates" and p["hours_evidence"]["source_updated_at"] == "2026-08-06"
    assert ch.summary(report) == {"branches": 2, "accepted": 1, "filled": 1,
                                 "conflicts": 0, "pending": 0, "unmatched_branches": 1}


def test_distant_branch_needs_phone_or_house_number():
    lat = 51.13 + 100 / 111_000  # ~100 m north
    vague, by_phone = poi("osm:1", 51.13, 71.40), poi("osm:2", 51.13, 71.40, phone="+7 778 978 99 98")
    by_house = poi("osm:3", 51.13, 71.40, address="Turan Ave 22")
    other_house = poi("osm:4", 51.13, 71.40, address="Turan Ave 24")
    report = ch.apply([vague, by_phone, by_house, other_house],
                      snap(shop("1", lat, 71.40, address="Астана, Тұран даңғылы 22 үй", phone="+7(778) 978-9998")))
    assert vague["opening_hours"] is None and other_house["opening_hours"] is None
    assert by_phone["hours_evidence"]["match_method"] == "phone"
    assert by_house["hours_evidence"]["match_method"] == "house_number"
    assert {c["poi"]: c["reason"] for c in report["pending"]} == {"osm:1": "unconfirmed_branch",
                                                                  "osm:4": "house_number_conflict"}


def test_shared_phone_does_not_confirm_a_branch():
    lat = 51.13 + 100 / 111_000
    p = poi("osm:1", 51.13, 71.40, phone="+77774099900")
    ch.apply([p], snap(shop("1", lat, 71.40, phone="+7(777) 409-9900"), shop("2", 51.20, 71.50, phone="+7(777) 409-9900")))
    assert p["opening_hours"] is None


def test_two_counters_with_different_hours_stay_pending():
    p = poi("osm:1", 51.13, 71.40, hours="24/7")
    report = ch.apply([p], snap(shop("1", 51.1301, 71.40, "Mon-Sun 08:00-24:00"),
                                 shop("2", 51.1301, 71.4001, "Mon-Sun 11:00-24:00")))
    assert p["opening_hours"] == "24/7" and "hours_source" not in p
    assert report["pending"][0]["reason"] == "several_branches"
    assert report["pending"][0]["rivals"] == ["2"]


def test_same_hours_twins_are_not_ambiguous():
    p = poi("osm:1", 51.13, 71.40)
    ch.apply([p], snap(shop("1", 51.1301, 71.40), shop("2", 51.1302, 71.40)))
    assert p["opening_hours"] == "Mo-Su 08:00-24:00"


def test_zero_length_hours_are_not_round_the_clock():
    p = poi("osm:1", 51.13, 71.40)
    report = ch.apply([p], snap(shop("1", 51.1301, 71.40, "Mon-Sun 00:00-00:00")))
    assert p["opening_hours"] is None and report["pending"][0]["reason"] == "hours_unclear"


def test_existing_different_hours_become_a_conflict_not_an_overwrite():
    p = poi("osm:1", 51.16, 71.43, name="Кофе бум", hours="Mo-Su 08:00-23:00")
    same = poi("osm:2", 51.20, 71.50, hours="Mo-Su 08:00-24:00")
    report = ch.apply([p, same], snap(shop("1", 51.1601, 71.43), shop("2", 51.2001, 71.50)))
    assert p["opening_hours"] == "Mo-Su 08:00-23:00" and "hours_source" not in p
    assert p["hours_conflict"]["current"] == "Mo-Su 08:00-23:00"
    assert p["hours_conflict"]["candidate"]["value"] == "Mo-Su 08:00-24:00"
    assert [c["poi"] for c in report["conflicts"]] == ["osm:1"]
    assert same["hours_source"] == "coffeeboom.kz" and report["accepted"][0]["filled"] is False


def test_far_branch_and_other_brands():
    far, other = poi("osm:1", 51.13, 71.40), poi("osm:2", 51.16, 71.43, name="Starbucks")
    report = ch.apply([far, other], snap(shop("1", 51.135, 71.40), shop("2", 51.1601, 71.43)))
    assert far["opening_hours"] is None and report["pending"] == [{"poi": "osm:1", "chain": "coffeeboom",
                                                                  "reason": "no_branch_nearby"}]
    assert other["opening_hours"] is None and "hours_source" not in other


def test_conflicting_place_keeps_low_confidence():
    from app.hours import opening_status
    p = poi("osm:1", 51.16, 71.43, hours="Mo-Su 08:00-23:00")
    ch.apply([p], snap(shop("1", 51.1601, 71.43)))
    status = opening_status(p, dt.datetime(2026, 10, 19, 12, 0), 30, "ru", None)
    assert status["status"] == "open" and status["confidence"] == "low"


def test_differently_written_equal_hours_are_not_a_conflict():
    assert ch.same_hours("09:00-24:00", "Mo-Su 09:00-24:00")
    assert not ch.same_hours("08:00-24:00", "Mo-Su 08:00-23:00")
    p = poi("osm:1", 51.13, 71.40, hours="08:00-24:00")
    report = ch.apply([p], snap(shop("1", 51.1301, 71.40)))
    assert not report["conflicts"] and p["hours_source"] == "coffeeboom.kz"


def atp(*features, chain="dodo", checked="2026-10-10"):
    geojson = {"features": [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]},
                             "properties": {"ref": ref, "opening_hours": hours, "addr:street_address": "улица Алматы, 11",
                                            "@source_uri": "https://publicapi.dodois.io/kz/api/v1/unitinfo/all"}}
                            for ref, lat, lon, hours in features]}
    return ch.snapshot({chain: ch.parse_atp(geojson, chain)}, {chain: checked},
                       {chain: "https://alltheplaces-data.openaddresses.io/runs/x/output/s.geojson"})


def test_atp_venue_hours_use_the_crawl_date():
    p = poi("osm:1", 51.13, 71.40, name="Додо Пицца")
    data = atp(("a", 51.1301, 71.40, "Mo-Su 09:00-24:00"), ("b", 43.2, 76.9, "Mo-Su 10:00-22:00"),
               ("c", 51.16, 71.45, "not hours at all"))
    assert [b["branch_id"] for b in data["chains"]["dodo"]["branches"]] == ["a", "c"]
    assert data["chains"]["dodo"]["branches"][1]["opening_hours"] is None
    ch.apply([p], data)
    assert p["opening_hours"] == "Mo-Su 09:00-24:00" and p["check_date"] == "2026-10-10"
    assert p["hours_source_url"].endswith(".geojson") and p["hours_source"] == "alltheplaces.xyz"


def test_hours_of_unknown_scope_stay_pending():
    p = poi("ov:1", 51.13, 71.40, name="Papa John's")
    report = ch.apply([p], atp(("1", 51.13, 71.40, "Mo-Su 00:00-02:45,10:00-24:00"), chain="papajohns"))
    assert p["opening_hours"] is None and report["pending"][0]["reason"] == "hours_scope_unknown"


def test_committed_snapshot_is_parseable():
    data = ch.load()
    assert data["parser_version"] == ch.PARSER_VERSION
    assert len(data["chains"]["coffeeboom"]["branches"]) >= 50 and data["chains"]["dodo"]["branches"]
    for key, chain in data["chains"].items():
        assert chain["checked_at"] and chain["page"].startswith("https://") and chain["hours_scope"] in {"venue", "unknown"}
        for b in chain["branches"]:
            assert b["opening_hours"] is None or oh.OpeningHours(b["opening_hours"])
            assert 50.9 <= b["lat"] <= 51.4 and 71.0 <= b["lon"] <= 71.9

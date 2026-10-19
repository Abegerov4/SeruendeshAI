"""Keep explicit internet facts attributable and avoid unsupported Wi-Fi claims."""
from copy import deepcopy

import pytest

from data.collect.amenities import extract_source_amenities


def test_wlan_preserves_source_provenance_and_adds_wifi_search_tags():
    # Catches lost provenance or a wlan value omitted from searchable metadata.
    facts, tags = extract_source_amenities({
        "id": "osm:node/12",
        "source_url": "https://www.openstreetmap.org/node/12",
        "collected_at": "2026-10-18T17:33:47+00:00",
        "source_updated_at": "2026-10-01T08:00:00Z",
        "raw_tags": {"internet_access": "wlan"},
    })

    assert facts == [{
        "field": "internet_access",
        "value": "wlan",
        "source_id": "osm:node/12",
        "source_url": "https://www.openstreetmap.org/node/12",
        "collected_at": "2026-10-18T17:33:47+00:00",
        "source_updated_at": "2026-10-01T08:00:00Z",
    }]
    assert tags == ["Wi-Fi", "internet_access=wlan", "интернет"]


def test_yes_supports_internet_but_does_not_claim_wifi():
    # Catches broad internet access being upgraded to a specific WLAN claim.
    facts, tags = extract_source_amenities({
        "id": "osm:node/13",
        "source_url": "https://www.openstreetmap.org/node/13",
        "collected_at": "2026-10-18",
        "raw_tags": {"internet_access": "yes"},
    })

    assert facts == [{
        "field": "internet_access", "value": "yes", "source_id": "osm:node/13",
        "source_url": "https://www.openstreetmap.org/node/13",
        "collected_at": "2026-10-18", "source_updated_at": None,
    }]
    assert tags == ["internet_access=yes", "интернет"]


@pytest.mark.parametrize("access", ["no", "unknown", "paid", "WLAN", "wlan;no"])
def test_non_positive_access_values_remain_uninterpreted_facts(access):
    # Catches false positive access for negative, unfamiliar, or conflicting values.
    facts, tags = extract_source_amenities({
        "id": "osm:node/14",
        "source_url": "https://www.openstreetmap.org/node/14",
        "raw_tags": {"internet_access": access},
    })

    assert facts == [{
        "field": "internet_access", "value": access, "source_id": "osm:node/14",
        "source_url": "https://www.openstreetmap.org/node/14",
        "collected_at": None, "source_updated_at": None,
    }]
    assert tags == []


@pytest.mark.parametrize("fee", ["no", "yes", "customers", "paid", "unknown"])
def test_fee_alone_is_preserved_without_inventing_internet_access(fee):
    # Catches a fee field being treated as proof of access or free public access.
    facts, tags = extract_source_amenities({
        "id": "osm:node/15",
        "source_url": "https://www.openstreetmap.org/node/15",
        "raw_tags": {"internet_access:fee": fee},
    })

    assert facts == [{
        "field": "internet_access:fee", "value": fee, "source_id": "osm:node/15",
        "source_url": "https://www.openstreetmap.org/node/15",
        "collected_at": None, "source_updated_at": None,
    }]
    assert tags == []


def test_customers_fee_and_conflicting_other_attributes_do_not_expand_wlan_claims():
    # Catches unsupported free/public/quiet/outlet/speed claims from unrelated tags.
    raw = {
        "id": "osm:node/16",
        "source_url": "https://www.openstreetmap.org/node/16",
        "collected_at": "2026-10-18",
        "raw_tags": {"internet_access": "wlan", "internet_access:fee": "customers",
                     "wifi": "no", "quiet": "yes", "socket": "yes", "speed": "fast"},
        "wifi": False,
    }
    original = deepcopy(raw)

    facts, tags = extract_source_amenities(raw)

    assert facts == [
        {"field": "internet_access", "value": "wlan", "source_id": "osm:node/16",
         "source_url": "https://www.openstreetmap.org/node/16",
         "collected_at": "2026-10-18", "source_updated_at": None},
        {"field": "internet_access:fee", "value": "customers", "source_id": "osm:node/16",
         "source_url": "https://www.openstreetmap.org/node/16",
         "collected_at": "2026-10-18", "source_updated_at": None},
    ]
    assert tags == ["Wi-Fi", "internet_access=wlan", "интернет"]
    assert raw == original


def test_negative_access_is_not_overridden_by_free_fee_or_positive_aliases():
    # Catches fee/alias fields incorrectly winning over an explicit negative source fact.
    facts, tags = extract_source_amenities({
        "id": "osm:node/17",
        "source_url": "https://www.openstreetmap.org/node/17",
        "raw_tags": {"internet_access": "no", "internet_access:fee": "no", "wifi": "yes"},
        "internet_access": "wlan",
    })

    assert facts == [
        {"field": "internet_access", "value": "no", "source_id": "osm:node/17",
         "source_url": "https://www.openstreetmap.org/node/17",
         "collected_at": None, "source_updated_at": None},
        {"field": "internet_access:fee", "value": "no", "source_id": "osm:node/17",
         "source_url": "https://www.openstreetmap.org/node/17",
         "collected_at": None, "source_updated_at": None},
    ]
    assert tags == []


@pytest.mark.parametrize("value", [None, True, False, 1, 0, 1.2, [], {}, "", " \t\n"])
def test_non_string_or_blank_values_are_not_source_facts(value):
    # Catches malformed/blank source values leaking into attributed facts.
    assert extract_source_amenities({
        "id": "osm:node/18",
        "source_url": "https://www.openstreetmap.org/node/18",
        "raw_tags": {"internet_access": value, "internet_access:fee": value},
    }) == ([], [])


@pytest.mark.parametrize("raw_tags", [None, True, False, 1, [], ["wlan"], "wlan"])
def test_malformed_raw_tags_are_ignored_without_claiming_amenities(raw_tags):
    # Catches malformed source containers crashing normalization or supplying claims.
    assert extract_source_amenities({
        "id": "osm:node/19",
        "source_url": "https://www.openstreetmap.org/node/19",
        "raw_tags": raw_tags,
    }) == ([], [])


@pytest.mark.parametrize("source_url", [
    None, True, [], "", "/node/20", "//www.openstreetmap.org/node/20",
    "javascript:alert(1)", "ftp://example.org/20", "https://", "https://[broken",
    "https://exam ple.org/20",
])
def test_facts_without_an_absolute_http_source_url_do_not_become_claims(source_url):
    # Catches unsupported or malformed provenance being treated as sourced access.
    assert extract_source_amenities({
        "id": "osm:node/20", "source_url": source_url,
        "raw_tags": {"internet_access": "wlan", "internet_access:fee": "no"},
    }) == ([], [])


@pytest.mark.parametrize("source_id", [None, True, 1, [], "", " \t"])
def test_facts_without_a_nonempty_source_id_do_not_become_claims(source_id):
    # Catches anonymous facts that cannot retain their original source on merging.
    assert extract_source_amenities({
        "id": source_id, "source_url": "https://www.openstreetmap.org/node/21",
        "raw_tags": {"internet_access": "wlan"},
    }) == ([], [])


def test_malformed_fee_does_not_drop_a_valid_access_fact():
    # Catches validation of one field accidentally rejecting the independent field.
    facts, tags = extract_source_amenities({
        "id": "osm:node/22", "source_url": "http://example.org/node/22",
        "raw_tags": {"internet_access": "yes", "internet_access:fee": True},
    })

    assert facts == [{
        "field": "internet_access", "value": "yes", "source_id": "osm:node/22",
        "source_url": "http://example.org/node/22",
        "collected_at": None, "source_updated_at": None,
    }]
    assert tags == ["internet_access=yes", "интернет"]

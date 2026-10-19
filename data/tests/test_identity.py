"""Conservative address/name comparisons for literal Astana source variants."""

import importlib.util

import pytest


if importlib.util.find_spec("data.collect.identity") is not None:
    from data.collect import identity
else:
    identity = None


@pytest.mark.parametrize(("left", "right", "expected"), [
    ("Тұран даңғылы, 37", "Turan Ave 37", True),
    ("Қабанбай батыр даңғылы, 53", "Kabanbay Batyr Avenue 53", True),
    ("ул. А, 1", "A Street 1", True),
    ("г. Астана, Тұран даңғылы, 37", "Turan Ave 37, Astana", True),
    ("Тұран даңғылы, 37А", "Turan Ave 37A", True),
    ("Туран, 37, офис 2", "Turan 37 unit 2", True),
    ("Туран, 37, 2 этаж", "Turan 37 floor 2", True),
    ("ул. Д, 1", "D Street 1", True),
    (None, "Turan Ave 37", True),
    ("ул. А, 1", "ул. А, 3", False),
    ("Тұран даңғылы, 37", "Сарайшық көшесі, 37", False),
    ("Туран, 37, офис 1", "Turan 37 unit 2", False),
    ("Туран, 37, 1 этаж", "Turan 37 floor 2", False),
    ("Туран, 37 корпус 1", "Turan 37 block 2", False),
    ("Туран, 37/1", "Turan 37/2", False),
    ("Туран, 37, офис 1", "Turan 37", False),
    ("37", "37", False),
    ("Y Street 1", "I Street 1", False),
])
def test_addresses_require_matching_street_and_explicit_subaddress(left, right, expected):
    assert identity is not None, "Identity helper must exist"
    assert identity.addresses_compatible(left, right) is expected
    assert identity.addresses_compatible(right, left) is expected


def poi(name, category="mall", **extra):
    return {"name": name, "category": category, **extra}


@pytest.mark.parametrize(("left", "right", "expected"), [
    (poi("Mega SilkWay Astana"), poi("Mega Silk Way"), True),
    (poi("Мега", aliases=["Mega Silk Way"]), poi("Mega SilkWay"), True),
    (poi("Хан Шатыр", name_en="Khan Shatyr"), poi("Khan Shatyr"), True),
    (poi("Mega SilkWay Astana", "cafe"), poi("Mega Silk Way", "cafe"), False),
    (poi("Резиденция Хан Шатыр"), poi("Khan Shatyr"), False),
    (poi("North Face Mega", "other"), poi("Mega"), False),
    (poi("CoffeeBoom 1", "cafe"), poi("CoffeeBoom 2", "cafe"), False),
    (poi("Astana Mega"), poi("Mega"), False),
])
def test_name_matches_use_complete_explicit_aliases_and_narrow_mall_suffix(left, right, expected):
    assert identity is not None, "Identity helper must exist"
    assert identity.same_name(left, right) is expected
    assert identity.same_name(right, left) is expected

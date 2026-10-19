"""Only current, attributable facts for the same branch reach derived views."""
from copy import deepcopy
import json

import pytest

try:
    from data import place_details
except ImportError:
    place_details = None


def payload():
    return {
        "schema_version": 1, "canonical_sha256": "a" * 64, "as_of": "2026-10-19",
        "records": [{
            "canonical_id": "osm:node/1",
            "identity": {"canonical_name": "Cafe", "canonical_address": "Main 1",
                         "source_name": "Cafe", "source_address": "Main 1, Astana",
                         "source_url": "https://merchant.example/branches/1",
                         "branch_confirmed": True, "match_basis": "name_address"},
            "facts": [{"field": "wifi", "value": False, **evidence()}],
            "menu_items": [{"id": "cutlet-potato", "name": "Котлета с картофельным пюре",
                            "components": ["котлета", "пюре"], "aliases": [],
                            "price": {"amount": 1900, "currency": "KZT", "unit": "portion",
                                      "channel": "delivery", "kind": "item"}, **evidence()}],
            "prices": [{"amount": 3000, "currency": "KZT", "unit": "person",
                        "channel": "dine_in", "kind": "average_check", **evidence()}],
        }],
    }


def evidence():
    return {"status": "accepted", "conflict_status": "none", "branch_scope": "exact",
            "branch_confirmation": {"source_name": "Cafe", "source_address": "Main 1, Astana"},
            "source": {"url": "https://merchant.example/menu/1",
                       "excerpt": "Котлета с картофельным пюре 1900 KZT; Wi-Fi нет; чек 3000 KZT",
                       "checked_at": "2026-10-19"}, "valid_from": None, "valid_to": None}


def load(tmp_path, body=None, **kwargs):
    assert place_details is not None, "Missing source-bound rich place contract"
    path = tmp_path / "details.json"
    path.write_text(json.dumps(payload() if body is None else body, ensure_ascii=False))
    return place_details.load_place_details(path, canonical_sha256="a" * 64, **kwargs)


def test_explicit_false_is_preserved_without_inventing_unknown_facts(tmp_path):
    details = load(tmp_path)
    original = [{"id": "osm:node/1", "name": "Cafe", "address": "Main 1"},
                {"id": "osm:node/2", "name": "Котлета Пюре", "address": "Main 2"}]
    result = place_details.apply_place_details(original, details)
    assert result[0]["place_details"]["facts"][0]["value"] is False
    assert "place_details" not in result[1]
    assert "place_details" not in original[0]
    assert "wheelchair" not in result[0]["place_details"]


def test_menu_price_never_becomes_dine_in_or_average_check(tmp_path):
    item = load(tmp_path)["osm:node/1"]
    assert item["menu_items"][0]["price"] == {
        "amount": 1900, "currency": "KZT", "unit": "portion", "channel": "delivery", "kind": "item"}
    assert item["prices"][0]["amount"] == 3000
    assert item["prices"][0]["kind"] == "average_check"


@pytest.mark.parametrize("change", [
    {"status": "pending"}, {"conflict_status": "unresolved"}, {"branch_scope": "chain"},
    {"source": {"url": "https://merchant.example/menu", "checked_at": "2026-10-19"}},
    {"source": {"url": "javascript:bad", "excerpt": "wifi", "checked_at": "2026-10-19"}},
    {"source": {"url": "https://merchant.example/menu", "excerpt": "wifi", "checked_at": "2026-10-20"}},
    {"source": {"url": "https://merchant.example/menu", "excerpt": "wifi", "checked_at": "2026-01-01"}},
    {"valid_from": "2026-10-20"}, {"valid_to": "2026-10-18"},
    {"branch_confirmation": {"source_name": "Cafe", "source_address": "Main 99, Astana"}},
    {"field": "invented_property"}, {"field": "wifi", "value": "yes"},
])
def test_unusable_fact_is_withheld_while_independent_menu_survives(tmp_path, change):
    body = payload()
    body["records"][0]["facts"][0].update(change)
    details = load(tmp_path, body)
    assert details["osm:node/1"]["facts"] == []
    assert details["osm:node/1"]["menu_items"]


@pytest.mark.parametrize("price", [
    {"amount": -1}, {"amount": True}, {"amount": float("inf")}, {"currency": "тенге"},
    {"channel": "unknown"}, {"kind": "average_check"}, {"unit": ""},
])
def test_untyped_menu_prices_are_withheld(tmp_path, price):
    body = payload()
    body["records"][0]["menu_items"][0]["price"].update(price)
    assert load(tmp_path, body)["osm:node/1"]["menu_items"] == []


def test_old_menu_is_withheld_even_when_general_fact_is_recent_enough(tmp_path):
    body = payload()
    for key in ("facts", "menu_items"):
        body["records"][0][key][0]["source"]["checked_at"] = "2026-09-01"
    details = load(tmp_path, body)["osm:node/1"]
    assert details["facts"]
    assert details["menu_items"] == []


@pytest.mark.parametrize("change", [{"schema_version": 2}, {"canonical_sha256": "b" * 64},
                                  {"as_of": "2026-10-20"}])
def test_wrong_snapshot_or_future_sidecar_is_rejected(tmp_path, change):
    body = payload()
    body.update(change)
    with pytest.raises(ValueError):
        load(tmp_path, body, as_of="2026-10-19")


def test_record_without_confirmed_branch_or_with_duplicate_id_is_rejected(tmp_path):
    body = payload()
    body["records"][0]["identity"]["branch_confirmed"] = False
    assert load(tmp_path, body) == {}
    body = payload()
    body["records"].append(deepcopy(body["records"][0]))
    with pytest.raises(ValueError, match="Duplicate"):
        load(tmp_path, body)


def test_kitchen_facts_do_not_replace_venue_opening_hours(tmp_path):
    body = payload()
    body["records"][0]["facts"] += [
        {**evidence(), "field": "kitchen_hours", "value": "Mo-Su 10:00-21:00"},
        {**evidence(), "field": "kitchen_closes_at", "value": "21:00"}]
    facts = load(tmp_path, body)["osm:node/1"]["facts"]
    assert {f["field"] for f in facts} >= {"kitchen_hours", "kitchen_closes_at"}
    assert not any(f["field"] == "opening_hours" for f in facts)


@pytest.mark.parametrize("cost_change", [
    {"service_percent": True}, {"mandatory_fixed_amount": -1},
    {"branch_confirmation": {"source_name": "Cafe", "source_address": "Other 2"}},
    {"source": {"url": "https://merchant.example/fees", "checked_at": "2026-08-01", "excerpt": "Old service"}},
])
def test_invalid_cost_is_withheld_without_losing_base_menu_price(tmp_path, cost_change):
    body = payload()
    menu = body["records"][0]["menu_items"][0]
    menu["cost"] = {**evidence(), "scope": "one_offering", "complete": True, "service_percent": 10,
                    "mandatory_fixed_amount": 0, "minimum_payable_amount": 0, **cost_change}
    kept = load(tmp_path, body)["osm:node/1"]["menu_items"][0]
    assert kept["price"]["amount"] == 1900
    assert "cost" not in kept


def test_unparseable_serving_constraint_withholds_the_affected_offering(tmp_path):
    body = payload()
    body["records"][0]["menu_items"][0]["serving_hours"] = "lunchtime whenever"
    assert load(tmp_path, body)["osm:node/1"]["menu_items"] == []


def test_conflicting_serving_windows_withhold_a_duplicate_offering(tmp_path):
    body = payload()
    first = body["records"][0]["menu_items"][0]
    first["serving_hours"] = "Mo-Fr 12:00-15:00"
    second = deepcopy(first)
    second["serving_hours"] = "Mo-Fr 10:00-12:00"
    body["records"][0]["menu_items"].append(second)
    assert load(tmp_path, body)["osm:node/1"]["menu_items"] == []


def test_equal_cost_terms_from_two_sources_are_not_a_price_conflict(tmp_path):
    body = payload()
    first = body["records"][0]["menu_items"][0]
    first["cost"] = {**evidence(), "scope":"one_offering", "complete":False, "service_percent":10,
                     "mandatory_fixed_amount":None, "minimum_payable_amount":None}
    second = deepcopy(first)
    second["cost"]["source"]["url"] = "https://merchant.example/another-fee-statement"
    body["records"][0]["menu_items"].append(second)
    assert load(tmp_path, body)["osm:node/1"]["menu_items"]


def test_details_cannot_be_reused_for_a_renamed_or_relocated_branch(tmp_path):
    details = load(tmp_path)
    changed = [{"id": "osm:node/1", "name": "Cafe", "address": "Main 99"}]
    assert "place_details" not in place_details.apply_place_details(changed, details)[0]
    changed[0].update(name="Other", address="Main 1")
    assert "place_details" not in place_details.apply_place_details(changed, details)[0]


def test_one_conflicting_value_withholds_all_values_for_that_field(tmp_path):
    body = payload()
    conflict = deepcopy(body["records"][0]["facts"][0])
    conflict["value"] = True
    body["records"][0]["facts"].append(conflict)
    assert load(tmp_path, body)["osm:node/1"]["facts"] == []


def test_confirmed_menu_without_known_price_remains_usable(tmp_path):
    body = payload()
    body["records"][0]["menu_items"][0]["price"] = None
    assert load(tmp_path, body)["osm:node/1"]["menu_items"][0]["price"] is None


def test_coordinate_branch_binding_requires_real_close_source_coordinates(tmp_path):
    body = payload()
    identity = body["records"][0]["identity"]
    identity.update(match_basis="name_coordinates", canonical_address=None)
    assert load(tmp_path, body) == {}
    identity.update(canonical_lat=51.129526, canonical_lon=71.428587,
                    source_lat=51.129588, source_lon=71.428472)
    details = load(tmp_path, body)
    row = {"id": "osm:node/1", "name": "Cafe", "address": None,
           "lat": 51.129526, "lon": 71.428587}
    assert place_details.apply_place_details([row], details)[0]["place_details"]
    row["lat"] = 51.1
    assert "place_details" not in place_details.apply_place_details([row], details)[0]
    identity["source_lat"] = 51.15
    assert load(tmp_path, body) == {}


@pytest.mark.parametrize("field,value", [("indoor", True), ("quiet", False), ("changing_table", False),
    ("laptop_allowed", True), ("step_free", False), ("wheelchair", "limited"),
    ("seasonality", "summer"), ("access_policy", "ticket required"), ("group_policy", "booking required")])
def test_explicit_user_requested_general_details_have_typed_support(tmp_path, field, value):
    body = payload()
    body["records"][0]["facts"] = [{"field": field, "value": value, **evidence()}]
    assert load(tmp_path, body)["osm:node/1"]["facts"][0]["value"] == value


def test_menu_role_is_explicit_and_unknown_by_default(tmp_path):
    assert load(tmp_path)["osm:node/1"]["menu_items"][0]["role"] == "unknown"
    body = payload()
    body["records"][0]["menu_items"][0]["role"] = "meal"
    assert load(tmp_path, body)["osm:node/1"]["menu_items"][0]["role"] == "meal"
    body["records"][0]["menu_items"][0]["role"] = "cheap"
    assert load(tmp_path, body)["osm:node/1"]["menu_items"] == []


def test_menu_component_or_alias_not_in_the_source_is_withheld(tmp_path):
    body = payload()
    body["records"][0]["menu_items"][0]["components"].append("стейк")
    assert load(tmp_path, body)["osm:node/1"]["menu_items"] == []
    body = payload()
    body["records"][0]["menu_items"][0]["aliases"] = ["котлета по-киевски"]
    assert load(tmp_path, body)["osm:node/1"]["menu_items"] == []


def test_delivery_platform_hours_never_become_onsite_opening_hours(tmp_path):
    body = payload()
    fact = body["records"][0]["facts"][0]
    fact.update(field="opening_hours", value="Mo-Su 08:00-22:00")
    fact["source"].update(url="https://wolt.com/en/kaz/nur-sultan/restaurant/cafe", channel="delivery")
    assert load(tmp_path, body)["osm:node/1"]["facts"] == []
    fact["field"] = "delivery_hours"
    assert load(tmp_path, body)["osm:node/1"]["facts"][0]["field"] == "delivery_hours"


@pytest.mark.parametrize("change", [{"field": []}, {"field": "wheelchair", "value": []},
    {"source": {"url": "https://[broken", "excerpt": "wifi", "checked_at": "2026-10-19"}}])
def test_malformed_fact_does_not_hide_independent_evidence(tmp_path, change):
    body = payload()
    body["records"][0]["facts"][0].update(change)
    assert load(tmp_path, body)["osm:node/1"]["facts"] == []


def test_competing_same_basis_prices_and_menu_ids_are_withheld(tmp_path):
    body = payload()
    rec = body["records"][0]
    price = deepcopy(rec["prices"][0]);price["amount"] = 4500
    rec["prices"].append(price)
    menu = deepcopy(rec["menu_items"][0]);menu["price"]["amount"] = 2100
    rec["menu_items"].append(menu)
    details = load(tmp_path, body)["osm:node/1"]
    assert details["prices"] == []
    assert details["menu_items"] == []


def test_up_to_capacity_is_preserved_as_an_upper_bound(tmp_path):
    body = payload()
    body["records"][0]["facts"] = [{"field": "seating_capacity_max", "value": 70, **evidence()}]
    assert load(tmp_path, body)["osm:node/1"]["facts"][0]["field"] == "seating_capacity_max"


def test_address_binding_requires_a_canonical_address(tmp_path):
    body = payload()
    body["records"][0]["identity"]["canonical_address"] = None
    assert load(tmp_path, body) == {}

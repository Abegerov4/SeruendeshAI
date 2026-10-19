from copy import deepcopy

import pytest


def source(identity="exact"):
    return {"schema_version":1,"canonical_sha256":"a"*64,"as_of":"2026-10-19","records":[{
        "canonical_id":"place:1","identity":{"source_name":identity},
        "facts":[{"field":"format","value":"canteen"}],"menu_items":[{"id":"meal"}],"prices":[]}]}


def merge(base, extra):
    from data.place_detail_merge import merge_detail_sources
    return merge_detail_sources(base, extra)


def test_same_identity_adds_kitchen_fact_without_dropping_menu_or_mutating_input():
    base = source()
    before = deepcopy(base)
    extra = source()
    extra["records"][0]["facts"] = [{"field":"kitchen_hours","value":"Mo-Su 08:00-21:30"}]
    extra["records"][0]["menu_items"] = []
    result, held = merge(base,extra)
    assert base == before
    assert result["records"][0]["menu_items"] == [{"id":"meal"}]
    assert {f["field"] for f in result["records"][0]["facts"]} == {"format","kitchen_hours"}
    assert not held


def test_different_identity_is_held_without_rewriting_branch_confirmations():
    base = source()
    result, held = merge(base, source("different"))
    assert result == base
    assert held == ["place:1"]


def test_new_branch_and_exact_duplicate_assertions_are_retained_once():
    base = source()
    extra = source()
    new = deepcopy(extra["records"][0]); new["canonical_id"] = "place:2"
    extra["records"].append(new)
    result, held = merge(base, extra)
    assert len(result["records"]) == 2
    assert len(result["records"][0]["facts"]) == 1
    assert len(result["records"][0]["menu_items"]) == 1
    assert not held


def test_another_master_or_duplicate_records_cannot_enter_merge():
    extra = source();extra["canonical_sha256"] = "b"*64
    with pytest.raises(ValueError): merge(source(),extra)
    extra = source();extra["records"].append(deepcopy(extra["records"][0]))
    with pytest.raises(ValueError): merge(source(),extra)

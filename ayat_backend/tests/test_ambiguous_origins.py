"""Never replace an ambiguous chain name with a different or arbitrary venue."""
import pytest

from ayat_backend.app.query import find_landmark_in_text, resolve_landmark, split_mentions


@pytest.fixture
def places():
    return [
        {"name": "Coffee Boom A", "kind": "poi", "keys": [], "ambiguous_keys": ["coffee boom"]},
        {"name": "Coffee Boom B", "kind": "poi", "keys": [], "ambiguous_keys": ["coffee boom"]},
        {"name": "Coffee", "kind": "poi", "keys": ["coffee"]},
        {"name": "Coffee Boom на Кенесары", "kind": "poi", "keys": ["coffee boom на кенесары"]},
        {"name": "Байтерек", "kind": "landmark", "keys": ["байтерек"], "landmark_key": "baiterek"},
    ]


def test_ambiguous_chain_does_not_resolve_to_shorter_name_or_fuzzy_branch(places):
    assert split_mentions("Я у Coffee Boom, хочу кофе", places) == (None, [])
    assert find_landmark_in_text("Coffee Boom", places) is None
    assert resolve_landmark("Coffee Boom", places) is None


def test_explicit_branch_can_resolve_despite_ambiguous_chain_prefix(places):
    origin, _ = split_mentions("Я у Coffee Boom на Кенесары, хочу кофе", places)
    assert origin["name"] == "Coffee Boom на Кенесары"


def test_non_landmark_name_requires_both_word_boundaries(places):
    assert find_landmark_in_text("Coffeeshop", places) is None


def test_curated_landmark_keeps_inflected_name_and_ui_key(places):
    assert split_mentions("Я возле Байтерека, хочу кофе", places)[0]["landmark_key"] == "baiterek"
    assert resolve_landmark("baiterek", places)["name"] == "Байтерек"

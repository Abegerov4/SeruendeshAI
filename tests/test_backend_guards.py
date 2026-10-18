"""Exercise the planned real mask_pii(query) guard without calling any model."""

import re

import pytest

pytestmark = pytest.mark.live_backend


@pytest.mark.parametrize("pii,canonical", [
    ("qa-user@example.com", "qa-user@example.com"),
    ("qa.user+walk@example.com", "qa.user+walk@example.com"),
    ("000000000000", "000000000000"),
    ("+7 000 000-00-00", "70000000000"),
    ("+70000000000", "70000000000"),
    ("+7 (000) 000-00-00", "70000000000"),
])
def test_mask_pii_removes_synthetic_identifiers_without_losing_intent(backend_guards, pii, canonical):
    result = backend_guards.mask_pii(f"Синтетический контакт {pii}; хочу парк рядом")
    assert isinstance(result, str)
    assert "парк" in result.lower()
    if "@" in canonical:
        assert canonical.lower() not in result.lower()
    else:
        assert canonical not in re.sub(r"\D", "", result)


@pytest.mark.parametrize("query,retained", [
    ("Я возле Mega Silk Way, хочу погулять 60 минут", "Mega Silk Way"),
    ("У меня 2 часа перед вылетом", "2 часа"),
    ("Бәйтерек маңында серуендегім келеді", "Бәйтерек"),
    ("I want a quiet cafe nearby", "quiet cafe"),
])
def test_mask_pii_preserves_benign_location_and_preferences(backend_guards, query, retained):
    result = backend_guards.mask_pii(query)
    assert isinstance(result, str) and retained in result


def test_mask_pii_is_idempotent(backend_guards):
    query = "Тест: qa-user@example.com; хочу парк рядом"
    once = backend_guards.mask_pii(query)
    assert backend_guards.mask_pii(once) == once

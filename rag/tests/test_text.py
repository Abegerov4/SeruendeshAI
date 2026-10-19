"""Search source names and explicit Wi-Fi variants without inventing facts."""
from rag.text import document, tokens


def test_merged_source_alias_is_part_of_search_document():
    poi = {"name": "MEGA Silk Way", "category": "mall", "tags": [], "aliases": ["Мега Силк Вей"]}
    assert "вей" in tokens(document(poi))


def test_wifi_hyphen_variants_share_one_search_token():
    for value in ("Wi-Fi", "wifi", "Wi‑Fi", "WI FI"):
        assert tokens(value) == ["wifi"]
    assert tokens("wifi cafe") == ["wifi", "cafe"]

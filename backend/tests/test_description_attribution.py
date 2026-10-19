"""A primary OSM place URL cannot substitute for its Wikipedia text attribution."""
from copy import deepcopy

from app.retrieval import Cand, Plan
from app.schemas import Recommendation
from app.service import _item


import pytest as _pytest


@_pytest.fixture(scope="module", autouse=True)
def canonical_snapshot_mode():
    """These tests cover the team catalogue runtime (opt-in in production)."""
    with _pytest.MonkeyPatch.context() as mp:
        mp.setenv("DATA_SNAPSHOT_MODE", "canonical")
        yield

ARTICLE = "https://ru.wikipedia.org/wiki/Байтерек"
LICENSE = "https://creativecommons.org/licenses/by-sa/4.0/"


def place(**fields):
    return {"id": "osm:way/10", "name": "Байтерек", "category": "monument", "lat": 51.128, "lon": 71.43,
            "source_url": "https://www.openstreetmap.org/way/10", "sources": ["osm", "wikipedia"],
            "features": {}, "description": "An article excerpt. " * 30, "description_source": "wikipedia",
            "description_kind": "source", "description_license": "CC-BY-SA-4.0", "description_url": ARTICLE,
            "source_refs": [{"source": "wikipedia", "url": ARTICLE, "license": "CC-BY-SA-4.0"}], **fields}


def render(row):
    cand = Cand(0, row, 100, 2, 15, (15, 30), {"status": "unknown", "confidence": "low", "label": "Unknown"})
    plan = Plan((51.128, 71.43), "walk", 75, 60, 20, 1000)
    return _item(cand, "Nearby", "Look around", 15, 1, plan, "en", "walk")


def test_licensed_wikipedia_excerpt_carries_article_license_and_shortening_notice():
    item = render(place())
    assert item["source_url"] == "https://www.openstreetmap.org/way/10"
    attribution = item["description_attribution"][0]
    assert attribution["url"] == ARTICLE
    assert attribution["license"] == "CC-BY-SA-4.0" and attribution["license_url"] == LICENSE
    assert attribution["attribution"] == "Wikipedia contributors"
    assert "shorten" in attribution["notice"].lower()
    assert len(item["description"]) <= 300
    assert Recommendation.model_validate(item).description_attribution[0].url == ARTICLE
    assert item["return_min"] == 0


def test_source_excerpt_is_withheld_without_complete_matching_attribution():
    for fields in ({"source_refs": []},
                   {"source_refs": [{"source": "wikipedia", "url": ARTICLE}]},
                   {"description_url": "https://ru.wikipedia.org/wiki/Other_article"},
                   {"source_refs": [{"source": "wikipedia", "url": "javascript:alert(1)", "license": "CC-BY-SA-4.0"}]}):
        original = place(**fields)
        before = deepcopy(original)
        item = render(original)
        assert item["description"] is None
        assert item["description_attribution"] == []
        assert original == before


def test_structured_fact_template_does_not_require_wikipedia_attribution():
    item = render(place(description="Monument in Astana.", description_source="osm", description_kind="structured_template",
                        description_license=None, source_refs=[]))
    assert item["description"] == "Monument in Astana."
    assert item["description_attribution"] == []

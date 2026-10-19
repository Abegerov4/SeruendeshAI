"""Direct origin lookup must initialize matching state for each bound catalog."""
from rag.geo import resolve_landmark


def test_direct_landmark_lookup_resolves_named_origin_from_bound_catalog(monkeypatch):
    monkeypatch.setattr("rag.retriever.catalog", lambda: {"pois": [
        {"id": "origin:1", "name": "Other place", "lat": 51.11, "lon": 71.41},
        {"id": "origin:2", "name": "Station origin", "lat": 51.12, "lon": 71.42,
         "origin_only": True},
    ]})
    assert resolve_landmark("Station origin") == {"lat": 51.12, "lon": 71.42, "label": "Station origin"}


def test_direct_landmark_lookup_with_empty_catalog_can_use_builtin_origin(monkeypatch):
    monkeypatch.setattr("rag.retriever.catalog", lambda: {"pois": []})
    assert resolve_landmark("Байтерек")["label"] == "Байтерек"

import json
from pathlib import Path

from rag import retriever

ROOT = Path(__file__).resolve().parents[2]


def test_real_review_exclusions_are_not_retrievable(monkeypatch):
    monkeypatch.setenv("RAG_SEARCH_MODE", "bm25")
    rows = json.loads((ROOT / "data/processed/pois.json").read_bytes())
    excluded = {"osm:way/230409020", "osm:node/4529345494", "overture:3dda9f68-24a5-4047-a0a0-101ce0a047fc",
                "overture:5b26880c-5614-4d74-a83d-06d45ed76b94", "overture:67740c18-c915-4b60-871a-3199c23aebe8"}
    for row in rows:
        if row["id"] in excluded:
            assert row["id"] not in {p["id"] for p in retriever.search(row["name"], row["lat"], row["lon"], 100)}


def test_conflicting_hours_remain_unknown_in_retrieved_facts(monkeypatch):
    monkeypatch.setenv("RAG_SEARCH_MODE", "bm25")
    rows = retriever.search("Мизам", 51.1828559, 71.3766565, 100)
    row = next(p for p in rows if p["id"] == "osm:node/4519246690")
    assert row["opening_hours"] is None
    assert row["canonical_opening_hours"] == "Mo-Su 08:00-23:00"
    assert row["field_conflicts"]


def test_search_and_lookup_hold_same_version_during_promotion(tmp_path, monkeypatch):
    from data.snapshot import publish_snapshot
    from backend.app import rag_adapter
    processed = tmp_path / "data/processed"
    def bundle(ids):
        rows = [{"id": ident, "name": "Coffee " + ident, "category": "cafe", "lat": 51.12, "lon": 71.43,
                 "source": "osm", "tags": [], "source_records": [{"id": ident}], "opening_hours": None} for ident in ids]
        return {"pois.json": rows, "pois_leisure.json": rows,
                "source_manifest.json": {"status": "ok", "sources": {}}, "stats.json": {"output_count": len(rows)}}
    publish_snapshot(processed, bundle(["old"]))
    monkeypatch.setattr(retriever, "ROOT", tmp_path)
    monkeypatch.setattr(rag_adapter, "_retriever", retriever)
    monkeypatch.setattr(rag_adapter, "_backend", "real")
    monkeypatch.setenv("RAG_SEARCH_MODE", "bm25")
    rag_adapter._load_processed.cache_clear()
    assert [p["id"] for p in rag_adapter.all_pois()] == ["old"]
    publish_snapshot(processed, bundle(["old", "new"]))
    assert {p["id"] for p in retriever.search("Coffee", None, None)} == {"old"}
    assert {p["id"] for p in rag_adapter.all_pois()} == {"old"}
    # Explicit restart/rebind adopts the new generation for both APIs.
    retriever._catalog.cache_clear()
    rag_adapter._load_processed.cache_clear()
    assert {p["id"] for p in retriever.search("Coffee", None, None)} == {"old", "new"}
    assert {p["id"] for p in rag_adapter.all_pois()} == {"old", "new"}
    rag_adapter._load_processed.cache_clear()

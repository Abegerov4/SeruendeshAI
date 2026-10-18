import json
import hashlib
from pathlib import Path

import pytest

from data.run_pipeline import run_pipeline
from data import run_pipeline as pipeline


BOUNDARY = {"type": "Polygon", "coordinates": [[[71.2, 50.85], [71.8, 50.85], [71.8, 51.35], [71.2, 51.35], [71.2, 50.85]]]}


def seed(raw, source, rows):
    folder = raw / source
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "candidates.json").write_text(json.dumps(rows))
    (folder / "report.json").write_text(json.dumps({"status": "ok", "count": len(rows)}))


def row(ident, name="Place", **kw):
    return {"id": ident, "name": name, "lat": 51.12, "lon": 71.43, "category": "cafe", "source": ident.split(":")[0], "source_url": "https://example.org/poi", **kw}


def description_cache(raw, *ids):
    rows = [{"id": ident, "slug": "museum-" + str(ident), "title": "Place " + str(ident),
             "latitude": "51.12", "longitude": "71.43", "tags": [],
             "description": "<p>Музей Астаны.</p>"} for ident in ids]
    chunk = '5:' + json.dumps(["$", "Component", None, {"initialItems": rows}])
    html = '<script>self.__next_f.push(' + json.dumps([1, chunk]) + ')</script>'
    folder = raw / "web"
    folder.mkdir(exist_ok=True)
    filename = hashlib.sha256(b"https://astana.citypass.kz/ru/attractions").hexdigest() + ".txt"
    (folder / filename).write_text(html)


def enrichment_cache(raw, candidates, enriched):
    digest = hashlib.sha256(json.dumps(candidates, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    (raw / "enrichment_input.json").write_text(json.dumps({"sha256": digest}))
    (raw / "enriched_candidates.json").write_text(json.dumps(enriched))


def test_offline_descriptions_and_post_review_preserve_exact_wiki_cache_reuse(tmp_path, monkeypatch):
    raw, out = tmp_path / "raw", tmp_path / "processed"
    primary = row("osm:1", "Place", address="Street 1", opening_hours="Mo-Fr 09:00-18:00")
    directory = row("citypass:7", "Other source label", address="Different address 2", lat=51.12001)
    seed(raw, "osm", [primary, row("osm:bad", "Invalid source")])
    seed(raw, "web", [directory])
    (raw / "osm/boundary.geojson").write_text(json.dumps(BOUNDARY))
    enrichment_cache(raw, [primary, directory], [{**primary, "name_en": "Cached English name"}, directory])
    description_cache(raw, 7, 8)
    (tmp_path / "data").mkdir()
    (tmp_path / "data/quality_overrides.json").write_text(json.dumps({
        "osm:bad": {"action": "quarantine", "reason": "Reviewed source error"},
        "citypass:7": {"phase": "after_enrichment", "action": "verified_same_place", "target_id": "osm:1",
                       "reason": "Reviewed identical place"}}))
    monkeypatch.setattr(pipeline, "ROOT", tmp_path)
    before = {p.relative_to(raw): p.read_bytes() for p in raw.rglob("*") if p.is_file()}
    result = run_pipeline(raw, out, sources=("osm", "web"), offline=True)
    pois = json.loads((out / "pois.json").read_text())
    assert len(pois) == 1
    assert pois[0]["name_en"] == "Cached English name"
    assert pois[0]["description"] == "Музей Астаны."
    assert pois[0]["description_attribution"]["source_id"] == "citypass:7"
    assert pois[0]["opening_hours"] == "Mo-Fr 09:00-18:00"
    assert pois[0]["lat"] == 51.12
    assert {record["id"] for record in pois[0]["source_records"]} == {"osm:1", "citypass:7"}
    assert result["quality"]["quarantine_count"] == 1
    assert {rule["id"] for rule in result["quality"]["applied_overrides"]} == {"osm:bad", "citypass:7"}
    assert result["sources"]["cached_descriptions"]["applied_source_ids"] == ["citypass:7"]
    assert result["sources"]["cached_descriptions"]["unmatched_source_ids"] == ["citypass:8"]
    assert before == {p.relative_to(raw): p.read_bytes() for p in raw.rglob("*") if p.is_file()}


def test_offline_cache_mismatch_keeps_new_candidates_without_stale_wiki_fields(tmp_path):
    raw, out = tmp_path / "raw", tmp_path / "processed"
    original = row("osm:1")
    newer = row("osm:2", "New place", lat=51.2)
    seed(raw, "osm", [original, newer])
    (raw / "osm/boundary.geojson").write_text(json.dumps(BOUNDARY))
    enrichment_cache(raw, [original], [{**original, "name_en": "Stale enrichment"}])
    run_pipeline(raw, out, sources=("osm",), offline=True)
    pois = json.loads((out / "pois.json").read_text())
    assert {poi["id"] for poi in pois} == {"osm:1", "osm:2"}
    assert all(poi["name_en"] is None for poi in pois)


def test_description_patch_rejects_coordinate_or_hours_rewrites(tmp_path, monkeypatch):
    raw, out = tmp_path / "raw", tmp_path / "processed"
    seed(raw, "osm", [row("osm:1")])
    (raw / "osm/boundary.geojson").write_text(json.dumps(BOUNDARY))
    monkeypatch.setattr(pipeline, "cached_descriptions", lambda path: (
        [{"id": "osm:1", "description": "Text.", "lat": 52.0, "opening_hours": "24/7"}], {}), raising=False)
    with pytest.raises(ValueError, match="description patch"):
        run_pipeline(raw, out, sources=("osm",), offline=True)
    assert not (out / "pois.json").exists()


def test_pending_description_review_is_preserved_on_candidate_before_normalization(tmp_path, monkeypatch):
    raw, out = tmp_path / "raw", tmp_path / "processed"
    seed(raw, "web", [row("citypass:121")])
    seed(raw, "osm", [])
    (raw / "osm/boundary.geojson").write_text(json.dumps(BOUNDARY))
    description_cache(raw, 121)
    observed = []
    normalize = pipeline.normalize_candidates

    def capture(candidates, boundary):
        observed.append(candidates)
        return normalize(candidates, boundary)

    monkeypatch.setattr(pipeline, "normalize_candidates", capture)
    run_pipeline(raw, out, sources=("web",), offline=True)
    held = observed[-1][0]
    assert held["held_description"] == "Музей Астаны."
    assert held["description"] is None
    assert held["description_review_status"] == "pending"
    assert held["description_review_reason"]
    assert held["description_review_evidence"]["source_id"] == "citypass:121"


def test_offline_rebuild_deduplicates_sources_and_preserves_southern_city(tmp_path):
    raw, out = tmp_path / "raw", tmp_path / "processed"
    seed(raw, "osm", [row("osm:node/1"), row("osm:node/2", "Airport site", lat=50.88)])
    seed(raw, "overture", [row("overture:1"), row("overture:3", lat=51.12001), row("overture:2", "Outside", lon=71.85)])
    (raw / "osm/boundary.geojson").write_text(json.dumps(BOUNDARY))
    result = run_pipeline(raw, out, sources=("osm", "overture"), offline=True)
    pois = json.loads((out / "pois.json").read_text())
    assert len(pois) == 2
    assert len(next(p for p in pois if p["name"] == "Place")["source_records"]) == 3
    assert json.loads((out / "stats.json").read_text())["source_participation"]["overture"] == 1
    assert result["quality"]["rejections"]["outside_city_boundary"] == 1
    assert (out.parent / "stats.md").exists()
    before = (out / "pois.json").read_bytes()
    run_pipeline(raw, out, sources=("osm", "overture"), offline=True)
    assert before == (out / "pois.json").read_bytes()


def test_missing_source_is_explicit_and_does_not_discard_available_cache(tmp_path):
    raw, out = tmp_path / "raw", tmp_path / "out"
    seed(raw, "osm", [row("osm:1")])
    (raw / "osm/boundary.geojson").write_text(json.dumps(BOUNDARY))
    result = run_pipeline(raw, out, sources=("osm", "overture"), offline=True)
    assert result["sources"]["overture"]["status"] == "unavailable"
    assert result["status"] == "partial"
    assert result["quality"]["output_count"] == 1


def test_empty_run_never_overwrites_previous_export(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    previous = '[{"id":"previous"}]'
    (out / "pois.json").write_text(previous)
    with pytest.raises(RuntimeError):
        run_pipeline(tmp_path / "raw", out, sources=("osm",), offline=True)
    assert (out / "pois.json").read_text() == previous


def test_missing_boundary_requires_explicit_fallback(tmp_path):
    raw, out = tmp_path / "raw", tmp_path / "out"
    seed(raw, "osm", [row("osm:1")])
    with pytest.raises(RuntimeError, match="boundary"):
        run_pipeline(raw, out, sources=("osm",), offline=True)
    result = run_pipeline(raw, out, sources=("osm",), offline=True, allow_bbox=True)
    assert result["quality"]["boundary_mode"] == "broad_bbox_only"

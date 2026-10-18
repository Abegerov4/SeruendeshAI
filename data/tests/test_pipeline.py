import json
from pathlib import Path

import pytest

from data.run_pipeline import run_pipeline


BOUNDARY = {"type": "Polygon", "coordinates": [[[71.2, 50.85], [71.8, 50.85], [71.8, 51.35], [71.2, 51.35], [71.2, 50.85]]]}


def seed(raw, source, rows):
    folder = raw / source
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "candidates.json").write_text(json.dumps(rows))
    (folder / "report.json").write_text(json.dumps({"status": "ok", "count": len(rows)}))


def row(ident, name="Place", **kw):
    return {"id": ident, "name": name, "lat": 51.12, "lon": 71.43, "category": "cafe", "source": ident.split(":")[0], "source_url": "https://example.org/poi", **kw}


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

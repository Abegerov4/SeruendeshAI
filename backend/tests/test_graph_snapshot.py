"""Graph loading must honor a selected snapshot, including an absent graph."""
import numpy as np

from app import geo


def write_graph(path, weight):
    np.savez(path, lat=[51.128, 51.1281], lon=[71.43, 71.43], indptr=[0, 1, 2],
             indices=[1, 0], weights=[weight, weight], gptr=[0, 0, 0], glat=[], glon=[],
             bbox=[71.42, 51.12, 71.44, 51.14])


def test_graph_loader_reads_selected_version_instead_of_legacy(tmp_path, monkeypatch):
    legacy, version = tmp_path / "legacy.npz", tmp_path / "version.npz"
    write_graph(legacy, 999)
    write_graph(version, 123)
    monkeypatch.setattr(geo, "GRAPH_FILE", legacy)
    graph = geo.load_graph(version)
    assert graph is not None
    distances, _, _ = graph.from_source(51.128, 71.43, 2000)
    assert distances[1] == 123


def test_missing_selected_graph_uses_honest_fallback_even_if_legacy_exists(tmp_path, monkeypatch):
    legacy = tmp_path / "legacy.npz"
    write_graph(legacy, 999)
    monkeypatch.setattr(geo, "GRAPH_FILE", legacy)
    assert geo.load_graph(tmp_path / "missing-version-graph.npz") is None

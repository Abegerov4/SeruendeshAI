"""Build the Astana walking and driving graphs once (osmnx) and export them as plain numpy arrays.

The API never imports osmnx/networkx: it loads CSR arrays and runs scipy Dijkstra
(~3 ms per route, ~250 MB RSS in total).
"""
from __future__ import annotations

import logging

import numpy as np

from app.paths import DRIVE_GRAPH_FILE, GRAPH_FILE, RAW_DIR

log = logging.getLogger("pipeline.graph")

# core city: Left & Right bank, EXPO / Mega Silk Way / NU in the south, Nurly Zhol in the east.
# The airport (51.02) is outside: trips there use the car formula.
BBOX = (71.33, 51.05, 71.57, 51.22)  # (west, south, east, north)


def build_graph(from_pickle: str | None = None, network: str = "walk") -> dict:
    """Download the walk or drive network with osmnx (Overpass), or load a previously built osmnx graph pickle.
    drive: directed (one-way streets), reduced to the strongly connected part so every node can reach every other."""
    if from_pickle:
        import pickle
        with open(from_pickle, "rb") as f:
            G = pickle.load(f)
        bbox = (min(d["x"] for _, d in G.nodes(data=True)), min(d["y"] for _, d in G.nodes(data=True)),
                max(d["x"] for _, d in G.nodes(data=True)), max(d["y"] for _, d in G.nodes(data=True)))
    else:
        import osmnx as ox
        ox.settings.use_cache = True
        ox.settings.cache_folder = str(RAW_DIR / "osmnx_cache")
        ox.settings.requests_timeout = 300
        ox.settings.http_user_agent = "SeruendeshAI/0.1 (hackathon; https://github.com/Abegerov4/SeruendeshAI)"
        # drive_service adds service roads and parking aisles: places in parks get a road within a short walk
        G = ox.graph_from_bbox(BBOX, network_type="drive_service" if network == "drive" else network, simplify=True,
                               retain_all=False)
        if network == "drive":
            G = ox.truncate.largest_component(G, strongly=True)
        bbox = BBOX
    log.info("%s graph: %d nodes, %d edges", network, G.number_of_nodes(), G.number_of_edges())
    return export(G, bbox, DRIVE_GRAPH_FILE if network == "drive" else GRAPH_FILE, directed=network == "drive")


def export(G, bbox, path=GRAPH_FILE, directed: bool = False) -> dict:

    nodes = list(G.nodes)
    ix = {n: i for i, n in enumerate(nodes)}
    lat = np.array([G.nodes[n]["y"] for n in nodes], dtype=np.float64)
    lon = np.array([G.nodes[n]["x"] for n in nodes], dtype=np.float64)

    best: dict[tuple[int, int], tuple[float, list]] = {}
    for u, v, d in G.edges(data=True):
        k = (ix[u], ix[v])
        length = float(d.get("length", 0.0))
        if k not in best or length < best[k][0]:
            geom = list(d["geometry"].coords) if "geometry" in d else []
            if geom and (abs(geom[0][0] - lon[k[0]]) + abs(geom[0][1] - lat[k[0]])) > 1e-7:
                geom = geom[::-1]  # orient from u to v
            best[k] = (length, geom[1:-1])  # interior points only
    # undirected walking: make sure both directions exist (a drive graph keeps one-way streets one-way)
    for (u, v), (length, geom) in list(best.items()):
        if not directed and (v, u) not in best:
            best[(v, u)] = (length, geom[::-1])

    keys = sorted(best)
    rows = np.array([k[0] for k in keys], dtype=np.int32)
    cols = np.array([k[1] for k in keys], dtype=np.int32)
    w = np.array([best[k][0] for k in keys], dtype=np.float32)
    indptr = np.zeros(len(nodes) + 1, dtype=np.int64)
    np.add.at(indptr, rows + 1, 1)
    indptr = np.cumsum(indptr)
    gptr = np.zeros(len(keys) + 1, dtype=np.int64)
    glat, glon = [], []
    for i, k in enumerate(keys):
        pts = best[k][1]
        gptr[i + 1] = gptr[i] + len(pts)
        glon.extend(p[0] for p in pts)
        glat.extend(p[1] for p in pts)
    np.savez_compressed(
        path, lat=lat, lon=lon, indptr=indptr, indices=cols, weights=w, gptr=gptr,
        glat=np.array(glat, dtype=np.float32), glon=np.array(glon, dtype=np.float32), bbox=np.array(bbox))
    info = {"nodes": len(nodes), "edges": len(keys), "file_mb": round(path.stat().st_size / 1e6, 1)}
    log.info("saved %s: %s", path.name, info)
    return info

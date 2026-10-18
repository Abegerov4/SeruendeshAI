"""Distances, travel times and walking routes.

Primary: shortest paths on a prebuilt OSM walking graph (scipy Dijkstra on CSR arrays).
Fallback: straight line x calibrated detour factor, with an extra penalty when the
straight segment crosses the Yesil river (measured: 3x for 0.5–1 km, 2x for 1–2 km).
"""
from __future__ import annotations

import logging
import math

import numpy as np

from app.paths import GRAPH_FILE

log = logging.getLogger("app.geo")

R_EARTH = 6371008.8
ASTANA_BBOX = (50.857, 71.217, 51.352, 71.786)  # S, W, N, E
WALK_M_PER_MIN = 75.0  # 4.5 km/h, matches OSRM/Valhalla foot profiles
SLOW_WALK_M_PER_MIN = 60.0  # with small children / reduced mobility
DETOUR_WALK = 1.28  # median network/straight ratio on Astana POI pairs
DETOUR_CAR = 1.35
CAR_KMH = 41.0  # free-flow; multiplied by traffic factor below
PARKING_MIN = 5
KX = 111320 * math.cos(math.radians(51.14))
KY = 110540.0


def round_coord(x: float, nd: int = 3) -> float:
    return round(float(x), nd)


def in_astana(lat: float, lon: float) -> bool:
    s, w, n, e = ASTANA_BBOX
    return s <= lat <= n and w <= lon <= e


def hav_m(lat1, lon1, lat2, lon2):
    """Great-circle distance in metres; works on scalars and numpy arrays."""
    p1, p2 = np.radians(lat1), np.radians(lat2)
    a = np.sin((p2 - p1) / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(np.radians(lon2 - lon1) / 2) ** 2
    return 2 * R_EARTH * np.arcsin(np.sqrt(a))


def _seg_intersect(a, b, c, d) -> bool:
    def orient(p, q, r):
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
    return (orient(a, b, c) * orient(a, b, d) < 0) and (orient(c, d, a) * orient(c, d, b) < 0)


def crosses_river(river: list, lat1: float, lon1: float, lat2: float, lon2: float) -> bool:
    a, b = (lon1 * KX, lat1 * KY), (lon2 * KX, lat2 * KY)
    lo_lat, hi_lat = min(lat1, lat2) - 0.01, max(lat1, lat2) + 0.01
    for line in river:
        for (la1, lo1), (la2, lo2) in zip(line[:-1], line[1:]):
            if (la1 < lo_lat and la2 < lo_lat) or (la1 > hi_lat and la2 > hi_lat):
                continue
            if _seg_intersect(a, b, (lo1 * KX, la1 * KY), (lo2 * KX, la2 * KY)):
                return True
    return False


def fallback_walk_m(river: list, lat1, lon1, lat2, lon2) -> float:
    d = float(hav_m(lat1, lon1, lat2, lon2))
    f = DETOUR_WALK
    if river and crosses_river(river, lat1, lon1, lat2, lon2):
        f = 2.6 if d < 1000 else 1.9 if d < 2000 else 1.35
    return d * f


def car_minutes(straight_m: float, hour: int, snowing: bool = False, transit: bool = False) -> tuple[int, int]:
    """(road distance m, minutes incl. parking) — heuristic, no live traffic.
    transit=True: public transport estimate (~18 km/h door-to-door speed + 10 min walking/waiting)."""
    road = straight_m * DETOUR_CAR
    if transit:
        return int(road), int(math.ceil(road / 1000 / 18 * 60 * (1.2 if snowing else 1.0) + 10))
    peak = 8 <= hour < 10 or 17 <= hour < 20
    traffic = 1.8 if peak else 1.3
    if snowing:
        traffic *= 1.3
    return int(road), int(math.ceil(road / 1000 / CAR_KMH * 60 * traffic + PARKING_MIN))


class WalkGraph:
    """OSM walking network as CSR arrays + per-edge interior geometry."""

    def __init__(self, path=GRAPH_FILE):
        from scipy.sparse import csr_matrix
        from scipy.spatial import cKDTree

        z = np.load(path)
        self.lat, self.lon = z["lat"], z["lon"]
        self.indptr, self.indices, self.w = z["indptr"], z["indices"], z["weights"].astype(np.float64)
        self.gptr, self.glat, self.glon = z["gptr"], z["glat"], z["glon"]
        west, south, east, north = z["bbox"]
        self.bbox = (south, west, north, east)
        n = len(self.lat)
        self.A = csr_matrix((self.w, self.indices, self.indptr), shape=(n, n))
        self.tree = cKDTree(np.c_[self.lon * KX, self.lat * KY])
        log.info("walk graph: %d nodes, %d edges", n, len(self.w))

    def covers(self, lat: float, lon: float) -> bool:
        s, w, n, e = self.bbox
        return s <= lat <= n and w <= lon <= e

    def snap(self, lat, lon):
        d, i = self.tree.query(np.c_[np.atleast_1d(lon) * KX, np.atleast_1d(lat) * KY])
        return d, i

    def from_source(self, lat: float, lon: float, limit_m: float):
        """One-to-all distances (metres) and predecessors from the node nearest to (lat, lon)."""
        from scipy.sparse.csgraph import dijkstra

        d0, i0 = self.snap(lat, lon)
        D, P = dijkstra(self.A, indices=int(i0[0]), limit=limit_m, return_predecessors=True)
        return D + float(d0[0]), P, int(i0[0])

    def path_polyline(self, P: np.ndarray, src: int, dst: int) -> list[tuple[float, float]]:
        nodes = [dst]
        while nodes[-1] != src and P[nodes[-1]] >= 0 and len(nodes) < 20000:
            nodes.append(int(P[nodes[-1]]))
        nodes.reverse()
        out: list[tuple[float, float]] = []
        for u, v in zip(nodes[:-1], nodes[1:]):
            out.append((round(float(self.lat[u]), 6), round(float(self.lon[u]), 6)))
            row = slice(self.indptr[u], self.indptr[u + 1])
            hits = np.nonzero(self.indices[row] == v)[0]
            if len(hits):
                e = self.indptr[u] + int(hits[0])
                for k in range(self.gptr[e], self.gptr[e + 1]):
                    out.append((round(float(self.glat[k]), 6), round(float(self.glon[k]), 6)))
        if nodes:
            out.append((round(float(self.lat[nodes[-1]]), 6), round(float(self.lon[nodes[-1]]), 6)))
        return _thin(out)


def _thin(pts: list[tuple[float, float]], min_step_m: float = 8.0) -> list[tuple[float, float]]:
    if len(pts) < 3:
        return pts
    out = [pts[0]]
    for p in pts[1:-1]:
        if abs(p[0] - out[-1][0]) * KY + abs(p[1] - out[-1][1]) * KX >= min_step_m:
            out.append(p)
    out.append(pts[-1])
    return out


def load_graph() -> WalkGraph | None:
    if not GRAPH_FILE.exists():
        log.warning("no walk graph at %s: using straight-line fallback", GRAPH_FILE)
        return None
    try:
        return WalkGraph()
    except Exception as e:
        log.warning("walk graph failed to load (%s): fallback mode", e)
        return None

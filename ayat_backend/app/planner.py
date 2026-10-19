"""Mini-route: choose and order 2–3 stops under the time budget (small orienteering problem).

Brute force over ordered subsets of the top candidates (8P3 = 336 orders, < 10 ms), checking
opening hours at the actual arrival time of every stop. Code decides the order; the LLM
only explains it.
"""
from __future__ import annotations

import datetime as dt
from itertools import permutations

import numpy as np

from ayat_backend.app.categories import CATEGORIES
from ayat_backend.app.context import Context
from ayat_backend.app.config import get_settings
from ayat_backend.app.geo import WalkGraph, car_minutes, fallback_walk_m, hav_m
from ayat_backend.app.hours import opening_status
from ayat_backend.app.retrieval import Cand, Plan


def _matrix(cands: list[Cand], plan: Plan, ctx: Context, graph: WalkGraph | None, river: list):
    """Travel minutes / metres between origin (index 0) and candidates (1..n), plus path data."""
    pts = [plan.origin] + [(c.poi["lat"], c.poi["lon"]) for c in cands]
    n = len(pts)
    T = np.zeros((n, n))
    Dm = np.zeros((n, n))
    preds: dict[int, tuple] = {}
    use_graph = plan.mode == "walk" and graph is not None and all(graph.covers(*p) for p in pts)
    if use_graph:
        snaps, idx = graph.snap(np.array([p[0] for p in pts]), np.array([p[1] for p in pts]))
        max_snap = getattr(get_settings(), "route_max_snap_m", 500)
        limit = plan.budget * plan.m_per_min + max_snap
        for a in range(n):
            D, P, src = graph.from_source(pts[a][0], pts[a][1], limit)
            network_destinations = set()
            preds[a] = (P, src, network_destinations)
            for b in range(n):
                if a != b:
                    d = D[int(idx[b])] + snaps[b]  # from_source already includes the source approach
                    if not np.isfinite(d) or snaps[a] > max_snap or snaps[b] > max_snap:
                        d = fallback_walk_m(river, *pts[a], *pts[b])
                        plan.outside_graph = True
                    else:
                        network_destinations.add(b)
                    Dm[a, b] = d
                    T[a, b] = np.ceil(d / plan.m_per_min)
        return T, Dm, preds, idx, True
    for a in range(n):
        for b in range(n):
            if a == b:
                continue
            if plan.mode == "car":
                road, mins = car_minutes(float(hav_m(*pts[a], *pts[b])), ctx.now.hour, ctx.snowing, plan.transit)
                Dm[a, b], T[a, b] = road, mins
            else:
                d = fallback_walk_m(river, *pts[a], *pts[b])
                Dm[a, b], T[a, b] = d, np.ceil(d / plan.m_per_min)
    return T, Dm, preds, None, False


def plan_route(cands: list[Cand], plan: Plan, ctx: Context, graph: WalkGraph | None, river: list, lang: str,
               returns: bool, max_stops: int = 3, top_n: int = 8) -> dict | None:
    pool = cands[:top_n]
    if len(pool) < 2:
        return None
    T, Dm, preds, idx, on_graph = _matrix(pool, plan, ctx, graph, river)
    budget = plan.budget
    if plan.deadline_min is not None:
        budget = min(budget, plan.deadline_min - plan.deadline_buffer)
    now = ctx.local_naive
    cache: dict[tuple[int, float, int], bool] = {}

    def open_ok(i: int, arrive_min: float, visit: int) -> bool:
        key = (i, float(arrive_min), visit)
        if key not in cache:
            c = pool[i - 1]
            cache[key] = opening_status(c.poi, now + dt.timedelta(minutes=arrive_min), visit, lang, ctx.holiday)["ok"]
        return cache[key]

    best = None
    for k in range(min(max_stops, len(pool)), 1, -1):
        for perm in permutations(range(1, len(pool) + 1), k):
            t_acc, prev, val, cats, timeline, ok = 0.0, 0, 0.0, [], [], True
            for i in perm:
                c = pool[i - 1]
                t_acc += T[prev, i]
                if plan.mode == "walk" and ctx.max_outdoor_min < 60 and T[prev, i] > ctx.max_outdoor_min + 5:
                    ok = False
                    break
                v = c.visit_range[0] if budget < 90 else c.visit_min
                if not open_ok(i, t_acc, v):
                    ok = False
                    break
                timeline.append((i, int(t_acc), v))
                t_acc += v
                cat = c.poi["category"]
                val += c.score * (0.55 if cat in cats else 1.0)
                cats.append(cat)
                prev = i
            if not ok:
                continue
            total = t_acc + (T[prev, 0] if returns else 0)
            if plan.deadline_back_target is not None and pool[prev - 1].return_min is not None:
                total = t_acc + pool[prev - 1].return_min
            if total > budget:
                continue
            val += 0.06 * k - 0.0015 * total
            if best is None or val > best[0]:
                best = (val, perm, timeline, int(total), int(t_acc))
        if best and best[1] and len(best[1]) == k:
            break  # prefer the largest feasible number of stops
    if not best:
        return None
    _, perm, timeline, total, _ = best
    legs, prev = [], 0
    seq = list(perm) + ([0] if returns else [])
    for i in seq:
        if on_graph and prev in preds and i in preds[prev][2]:
            P, src, _ = preds[prev]
            poly = graph.path_polyline(P, src, int(idx[i]))
            pts = [(plan.origin if prev == 0 else (pool[prev - 1].poi["lat"], pool[prev - 1].poi["lon"]))]
            poly = [tuple(map(float, pts[0]))] + poly + [tuple(map(float, plan.origin if i == 0 else (pool[i - 1].poi["lat"], pool[i - 1].poi["lon"])))]
            geom = "network"
        else:
            a = plan.origin if prev == 0 else (pool[prev - 1].poi["lat"], pool[prev - 1].poi["lon"])
            b = plan.origin if i == 0 else (pool[i - 1].poi["lat"], pool[i - 1].poi["lon"])
            poly, geom = [a, b], "straight"
        legs.append({"from": prev, "to": i, "distance_m": int(Dm[prev, i]), "travel_min": int(T[prev, i]),
                     "polyline": [(round(p[0], 6), round(p[1], 6)) for p in poly], "geometry": geom})
        prev = i
    travel = sum(leg["travel_min"] for leg in legs)
    visit = sum(v for _, _, v in timeline)
    back = total - travel - visit if plan.deadline_back_target is not None else 0
    return {"stops": [pool[i - 1] for i in perm], "timeline": timeline, "legs": legs, "total_min": total, "back_min": max(0, back),
            "travel_min": travel, "visit_min": visit, "fits_budget": total <= plan.budget,
            "returns_to_start": returns, "pool": pool, "on_graph": on_graph}


def route_wanted(parsed, req_want: bool | None, plan: Plan, n_cands: int) -> bool:
    if req_want is not None:
        return req_want and n_cands >= 2
    if parsed.wants_route:
        return n_cands >= 2
    if n_cands < 2 or plan.budget < 45:
        return False
    return bool(parsed.walk_intent or plan.tourist or (plan.deadline_min and plan.deadline_min >= 120))


_ = CATEGORIES

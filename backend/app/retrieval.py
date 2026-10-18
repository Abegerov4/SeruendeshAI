"""Candidate generation and ranking ("structured-first hybrid RAG").

1. reachability: network walking distance (Dijkstra on the OSM graph) or car estimate,
   one-way time cap derived from the user's time budget;
2. hard filters in code: opening hours at arrival, children, accessibility, darkness, cold;
3. relevance: requested categories + BM25 (Russian-stemmed, on the LLM's Russian rewrite)
   fused with dense e5 similarity (RRF);
4. weighted score + MMR diversification -> up to 10 candidate cards for the LLM.
"""
from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass, field

import numpy as np
from rapidfuzz import fuzz

from app.categories import CATEGORIES, label
from app.context import Context
from app.geo import (SLOW_WALK_M_PER_MIN, WALK_M_PER_MIN, WalkGraph, car_minutes, fallback_walk_m, hav_m)
from app.hours import opening_status
from app.i18n import t
from app.query import Parsed
from app.store import Store, stem_tokens
from app.textnorm import fold

# default pool when the user did not ask for specific place types
DEFAULT_GROUPS = {"sight", "culture", "nature", "food", "shopping", "quiet", "entertainment"}
OUTDOOR_CATS = {"park", "garden", "playground", "monument", "artwork", "theme_park"}
NEED_LABEL = {"wifi": "Wi-Fi", "power_outlets": "розетки", "quiet": "тишина", "outdoor_seating": "веранда",
              "wheelchair": "доступность", "kids": "для детей", "free": "бесплатно"}
WEIGHTS = {"rel": 0.35, "dist": 0.20, "attr": 0.15, "open": 0.10, "ctx": 0.10, "pop": 0.10}


@dataclass
class Plan:
    """Everything the ranking decided, for explanations and used_context."""
    origin: tuple[float, float]
    mode: str
    m_per_min: float
    budget: int
    t_max: int
    radius_m: int
    deadline_min: int | None = None
    deadline_back_target: tuple[float, float] | None = None
    deadline_buffer: int = 0
    with_child: bool = False
    accessibility: bool = False
    tourist: bool = False
    relaxations: list[str] = field(default_factory=list)
    filters: list[str] = field(default_factory=list)
    funnel: dict[str, int] = field(default_factory=dict)
    graph_used: bool = False
    outside_graph: bool = False
    transit: bool = False


@dataclass
class Cand:
    idx: int
    poi: dict
    distance_m: int
    travel_min: int
    visit_min: int
    visit_range: tuple[int, int]
    opening: dict
    score: float = 0.0
    parts: dict = field(default_factory=dict)
    need_state: dict = field(default_factory=dict)
    event: dict | None = None
    leave_by: str | None = None
    return_min: int | None = None


def visit_minutes(cat: str, budget: int, mode: str) -> tuple[int, tuple[int, int]]:
    lo, typ = CATEGORIES[cat].visit
    v = typ if budget >= 90 else lo
    if mode == "car":
        v += 0
    return v, (lo, max(typ, lo))


def _need_state(p: dict, need: str, ctx: Context) -> float:
    c = CATEGORIES[p["category"]]
    f = p.get("features", {})
    if need == "wifi":
        return 1.0 if f.get("wifi") is True or c.key == "coworking" else 0.0 if f.get("wifi") is False else 0.5
    if need == "power_outlets":
        return 1.0 if f.get("power_outlets") else 0.75 if c.key in ("coworking", "library") else 0.5 if c.group == "food" else 0.2
    if need == "quiet":
        return 1.0 if c.quiet else 0.6 if c.key in ("cafe", "museum", "park") else 0.0 if c.group == "night" or c.key in ("mall", "fast_food") else 0.4
    if need == "outdoor_seating":
        return 1.0 if f.get("outdoor_seating") else 0.4
    if need == "wheelchair":
        w = f.get("wheelchair")
        return {"yes": 1.0, "limited": 0.6, "no": 0.0}.get(w, 0.4)
    if need == "kids":
        return 0.0 if c.adult_only else 1.0 if c.kids or f.get("kids_area") else 0.4
    if need in ("indoor", "warm"):
        ind = p.get("indoor") if p.get("indoor") is not None else c.indoor
        return 1.0 if ind else 0.5 if ind is None else 0.0
    if need == "free":
        return 1.0 if f.get("free") is True or p["category"] in ("park", "garden", "monument", "artwork", "playground") else 0.0 if f.get("free") is False else 0.5
    if need == "view":
        return 1.0 if c.key == "viewpoint" else 0.7 if c.key == "landmark" else 0.3
    if need == "open_late":
        return 1.0 if f.get("open_24_7") or c.night else 0.5
    return 0.5


def _is_outdoor(p: dict) -> bool:
    c = CATEGORIES[p["category"]]
    ind = p.get("indoor") if p.get("indoor") is not None else c.indoor
    return ind is False


def compute_reach(store: Store, graph: WalkGraph | None, poi_nodes: np.ndarray | None, poi_snap: np.ndarray | None,
                  plan: Plan, limit_min: float, ctx: Context) -> tuple[np.ndarray, np.ndarray]:
    """Returns (distance_m, travel_min) arrays for all POIs (inf where unreachable)."""
    lat0, lon0 = plan.origin
    straight = hav_m(lat0, lon0, store.lat, store.lon)
    if plan.mode == "car":
        hour = ctx.now.hour
        road = straight * 1.35
        mins = np.array([car_minutes(float(s), hour, ctx.snowing, plan.transit)[1] for s in straight], dtype=np.float64)
        return road, mins
    limit_m = limit_min * plan.m_per_min
    dist = np.full(store.size, np.inf)
    cand = straight <= limit_m * 1.05
    if graph is not None and graph.covers(lat0, lon0) and poi_nodes is not None:
        D, _, _ = graph.from_source(lat0, lon0, limit_m + 200)
        d = D[poi_nodes] + poi_snap
        dist = np.where(cand & np.isfinite(d), d, np.inf)
        plan.graph_used = True
        # POIs outside the graph area (or on disconnected bits) fall back to the estimate
        miss = cand & ~np.isfinite(dist) & (poi_snap > 150)
    else:
        miss = cand
        plan.outside_graph = True
    for i in np.nonzero(miss)[0]:
        dist[i] = fallback_walk_m(store.river, lat0, lon0, store.lat[i], store.lon[i])
    mins = np.ceil(dist / plan.m_per_min)
    return dist, mins


def rank(store: Store, graph: WalkGraph | None, poi_nodes, poi_snap, parsed: Parsed, plan: Plan, ctx: Context,
         lang: str, qvec: np.ndarray | None, k: int = 10, exclude_keys: set[str] | None = None,
         target_ids: set[str] | None = None) -> tuple[list[Cand], list[dict]]:
    """Return (top-k candidate cards, considered/rejected list)."""
    req_cats = [c for c in parsed.categories if c in CATEGORIES]
    req_groups = {CATEGORIES[c].group for c in req_cats}
    needs = set(parsed.needs)
    now = ctx.local_naive
    considered: list[dict] = []
    dist, mins = compute_reach(store, graph, poi_nodes, poi_snap, plan, plan.t_max * 2, ctx)
    plan.funnel["total"] = store.size

    # --- text relevance (BM25 + dense, fused with RRF) over the whole store, cheap at this size
    qtext = " ".join([parsed.search_text, *parsed.keywords])
    bm = np.asarray(store.bm25.get_scores(stem_tokens(qtext)), dtype=np.float64) if qtext.strip() else np.zeros(store.size)
    rrf = np.zeros(store.size)
    for scores in ([bm] + ([store.emb @ qvec] if (store.emb is not None and qvec is not None) else [])):
        order = np.argsort(-scores)
        ranks = np.empty(store.size)
        ranks[order] = np.arange(store.size)
        rrf += 1.0 / (60 + ranks + 1)

    exclude_keys = exclude_keys or set()
    target_ids = target_ids or set()
    target_idx = {store.by_id[t_] for t_ in target_ids if t_ in store.by_id}
    exact_cnt = {"n": 0}
    ev_by_poi = _events_by_poi(store, ctx, plan)

    def eligible(i: int, t_max: float, relaxed_needs: bool) -> tuple[bool, str | None, dict | None]:
        p = store.pois[i]
        c = CATEGORIES[p["category"]]
        is_target = i in target_idx
        if not np.isfinite(mins[i]) or mins[i] > (plan.budget if is_target else t_max):
            return False, None, None
        if is_target:  # the place the user named as a destination: only hours/safety rules apply
            v, vr = visit_minutes(p["category"], plan.budget, plan.mode)
            op = opening_status(p, now + dt.timedelta(minutes=float(mins[i])), v, lang, ctx.holiday)
            if plan.with_child and c.adult_only:
                return False, t("rej_kids", lang), None
            return (True, None, op) if op["ok"] else (False, t("rej_closed", lang), op)
        if parsed.avoid and p["category"] in parsed.avoid:
            return False, None, None
        if exclude_keys and mins[i] <= 8 and _is_origin(p["name"], exclude_keys):
            return False, None, None  # the landmark the user is standing at is not a recommendation
        has_event = p["id"] in ev_by_poi
        if req_cats and not (has_event and parsed.wants_event):
            if p["category"] not in req_cats:
                # widen to the same group only when exact matches are scarce, never into adult/fast-food places
                if exact_cnt["n"] >= 5 or c.group not in req_groups or c.adult_only or p["category"] == "fast_food":
                    return False, None, None
                if plan.with_child and not c.kids:
                    return False, None, None
        elif not has_event:
            if c.group not in DEFAULT_GROUPS and not (parsed.night and c.night) and not (plan.with_child and c.kids):
                return False, None, None
            if p["category"] in ("fast_food",) or (p["category"] == "playground" and not plan.with_child):
                return False, None, None
            if c.adult_only and not parsed.night:
                return False, None, None
            if p["category"] in ("karaoke", "hookah") and not parsed.night:
                return False, None, None
            if p["category"] == "restaurant" and not (parsed.night or plan.budget >= 90):
                return False, None, None
            if parsed.walk_intent and c.group == "food" and ctx.max_outdoor_min >= 60 and plan.budget < 120:
                return False, None, None  # "a walk" means walking places, not a café (unless it's cold or long)
        if plan.with_child and c.adult_only:
            return False, t("rej_kids", lang), None
        if plan.accessibility and p.get("features", {}).get("wheelchair") == "no":
            return False, t("rej_access", lang), None
        if ctx.is_dark and p["category"] in ("park", "garden", "playground") and p.get("features", {}).get("lit") is not True:
            return False, t("rej_dark", lang), None
        if ctx.max_outdoor_min == 0 and _is_outdoor(p):
            return False, t("rej_cold", lang), None
        if "indoor_only" in plan.filters and _is_outdoor(p):
            return False, None, None
        if plan.mode == "walk" and ctx.max_outdoor_min < 60 and mins[i] > ctx.max_outdoor_min + 5 and not relaxed_needs:
            return False, t("rej_cold", lang), None
        v, vr = visit_minutes(p["category"], plan.budget, plan.mode)
        arrive = now + dt.timedelta(minutes=float(mins[i]))
        op = opening_status(p, arrive, v, lang, ctx.holiday)
        if not op["ok"]:
            return False, t("rej_closed", lang), op
        if parsed.night and ctx.is_dark and op["status"] in ("unknown",) and c.group in ("food", "shopping", "culture"):
            return False, t("rej_closed", lang), op
        late = arrive.hour >= 21 or arrive.hour < 8
        if late and op["status"] == "unknown" and c.group in ("culture", "shopping", "quiet") and not c.night:
            return False, t("rej_closed", lang), op  # museums/galleries/shops with unknown hours are almost surely closed
        return True, None, op

    def collect(t_max: float, relaxed: bool):
        out, rej = [], []
        within = np.isfinite(mins) & (mins <= t_max)
        exact_cnt["n"] = int(np.sum(within & np.isin(store.cats, req_cats))) if req_cats else 0
        for i in sorted(set(np.nonzero(np.isfinite(mins) & (mins <= t_max))[0].tolist()) | target_idx):
            ok, why, op = eligible(int(i), t_max, relaxed)
            if ok:
                out.append((int(i), op))
            elif why:
                rej.append((int(i), why))
        return out, rej

    t_max = plan.t_max
    pool, rejected = collect(t_max, False)
    if not pool and req_cats:
        # nothing of the requested type is available now: say so and show what is open instead
        closed_n = sum(1 for i, why in rejected if store.pois[i]["category"] in req_cats)
        plan.relaxations.append(t("note_requested_closed", lang, what=label(req_cats[0], lang), n=closed_n))
        parsed.soft_categories = list(dict.fromkeys(parsed.soft_categories + req_cats))
        req_cats, req_groups = [], set()
        pool, rejected2 = collect(t_max, False)
        rejected += rejected2
    plan.funnel["within_reach"] = int(np.sum(np.isfinite(mins) & (mins <= t_max)))
    if len(pool) < 3:
        for factor in (1.5, 2.0):
            t2 = min(plan.t_max * factor, plan.budget * 0.6 if not plan.deadline_min else plan.t_max * factor)
            if t2 <= t_max:
                continue
            pool, rejected = collect(t2, True)
            t_max = t2
            plan.relaxations.append(t("note_relaxed_radius", lang, r=round(t_max * plan.m_per_min / 1000 / 1.28, 1)))
            if len(pool) >= 3:
                break
    if plan.accessibility:
        confirmed = [(i, op) for i, op in pool if store.pois[i].get("features", {}).get("wheelchair") in ("yes", "limited")]
        if len(confirmed) >= 2:  # enough places with confirmed step-free access: show only those
            pool = confirmed
            plan.filters.append("wheelchair_confirmed")
    plan.funnel["after_filters"] = len(pool)
    plan.t_max = int(t_max)
    plan.radius_m = int(t_max * plan.m_per_min / 1.28) if plan.mode == "walk" else int(max(t_max - 5, 3) * 41000 / 60 / 1.3 / 1.35)

    # --- deadline (flight/train): the place must leave enough time to get back
    cands: list[Cand] = []
    for i, op in pool:
        p = store.pois[i]
        v, vr = visit_minutes(p["category"], plan.budget, plan.mode)
        c = Cand(idx=i, poi=p, distance_m=int(dist[i]), travel_min=int(mins[i]), visit_min=v, visit_range=vr, opening=op)
        if plan.deadline_min is None:
            room = plan.budget - c.travel_min
            if room < max(5, min(vr[0], 10)) and room < vr[0]:
                rejected.append((i, t("rej_far", lang, m=c.travel_min)))
                continue
            if room < c.visit_min:
                c.visit_min = int(max(5, room))
            c.visit_range = (min(vr[0], max(5, room)), min(vr[1], max(5, room)))
        if plan.deadline_min is not None and plan.deadline_back_target is not None:
            back_straight = float(hav_m(p["lat"], p["lon"], *plan.deadline_back_target))
            back = car_minutes(back_straight, ctx.now.hour, ctx.snowing)[1]
            free = plan.deadline_min - plan.deadline_buffer
            if c.travel_min + c.visit_min + back > free:
                if c.travel_min + vr[0] + back <= free:
                    c.visit_min = vr[0]
                else:
                    rejected.append((i, t("rej_far", lang, m=c.travel_min + back)))
                    continue
            c.return_min = back
            leave = ctx.now + dt.timedelta(minutes=free - back)
            c.leave_by = leave.strftime("%H:%M")
        cands.append(c)

    if req_cats:
        closed_req = [i for i, why in rejected if why == t("rej_closed", lang) and store.pois[i]["category"] in req_cats]
        if closed_req and not any(c.poi["category"] in req_cats for c in cands) and not plan.relaxations:
            plan.relaxations.append(t("note_requested_closed", lang, what=label(req_cats[0], lang), n=len(closed_req)))
    if not cands:
        for i, why in sorted(rejected, key=lambda x: x[0] not in target_idx)[:4]:
            considered.append({"name": store.pois[i]["name"], "reason": why})
        return [], considered

    # --- scoring
    rrf_vals = np.array([rrf[c.idx] for c in cands])
    rrf_n = (rrf_vals - rrf_vals.min()) / (np.ptp(rrf_vals) or 1.0)
    for c, rt in zip(cands, rrf_n):
        p, cat = c.poi, CATEGORIES[c.poi["category"]]
        if req_cats:
            tag = 1.0 if p["category"] in req_cats else 0.6
            # the first requested category is usually the main intent
            if p["category"] == req_cats[0]:
                tag = 1.0
            elif p["category"] in req_cats:
                tag = 0.85
        else:
            tag = _default_prior(p["category"], parsed, plan, ctx)
            soft = parsed.soft_categories
            if soft:
                if p["category"] in soft:
                    tag = max(tag, 1.0)
                elif cat.group in {CATEGORIES[c].group for c in soft}:
                    tag = max(tag * 0.9, 0.7)
                else:
                    tag *= 0.8
        if parsed.wants_event and p["id"] in ev_by_poi:
            tag = 1.0
        if c.idx in target_idx:
            tag, rt = 1.0, 1.0
        rel = 0.5 * tag + 0.5 * float(rt)
        if p.get("name_auto") and p["category"] != "playground":
            rel *= 0.6  # unnamed squares are fine fillers but rarely the answer
        half = max(plan.t_max / 2, 4)
        dscore = math.exp(-math.log(2) * c.travel_min / half)
        ns = {n: _need_state(p, n, ctx) for n in needs if n not in ("kids",) or plan.with_child}
        attr = float(np.mean(list(ns.values()))) if ns else 0.5
        st = c.opening["status"]
        oscore = {"open": 1.0, "always": 0.85, "closing_soon": 0.45, "unknown": 0.5}.get(st, 0.3)
        if ctx.is_dark and st == "unknown":
            oscore = 0.25
        ctxs = 0.5
        if ctx.max_outdoor_min < 60:
            ctxs += 0.35 if not _is_outdoor(p) else -0.35
        elif _is_outdoor(p) and not ctx.is_dark and ctx.weather:
            ctxs += 0.15
        if ctx.is_dark:
            ctxs += 0.2 if (cat.night or not _is_outdoor(p) or p.get("features", {}).get("lit")) else -0.2
        if plan.tourist and cat.group in ("sight", "culture"):
            ctxs += 0.25
        if plan.with_child and (cat.kids or p.get("features", {}).get("kids_area")):
            ctxs += 0.25
        if parsed.night and cat.night:
            ctxs += 0.2
        if p["category"] == "playground" and p.get("name_auto"):
            ctxs -= 0.1
        ev = ev_by_poi.get(p["id"])
        if ev:
            ctxs += 0.25
            c.event = ev
        ctxs = min(max(ctxs, 0.0), 1.0)
        pop = float(p.get("popularity", 0.0))
        if parsed.surprise:
            pop = 0.6 * (1 - pop) if pop < 0.5 else 0.1
        parts = {"rel": rel, "dist": dscore, "attr": attr, "open": oscore, "ctx": ctxs, "pop": pop}
        w = dict(WEIGHTS)
        if parsed.night:
            w["open"], w["rel"] = 0.2, 0.3
        if plan.deadline_min is not None:
            w["dist"] = 0.3
        if plan.tourist:
            w["pop"], w["dist"] = 0.25, 0.15
        if plan.accessibility:
            w["attr"] = 0.3
        if plan.t_max <= 12:
            w["dist"] = max(w["dist"], 0.3)  # "closer" refinement / tiny budgets  # first-time visitors: iconic places matter more than the nearest ones
        c.score = sum(w[k] * parts[k] for k in parts) / sum(w.values())
        parts["cold"] = ctx.max_outdoor_min < 60
        c.parts, c.need_state = parts, ns

    cands.sort(key=lambda c: -c.score)
    chosen = _mmr(cands, k, single_cat=len(set(req_cats)) == 1)
    for i, why in sorted(rejected, key=lambda x: (x[0] not in target_idx, -rrf[x[0]]))[:4]:  # requested places first
        considered.append({"name": store.pois[i]["name"], "reason": why})
    plan.funnel["shown"] = 0
    return chosen, considered


def _is_origin(name: str, keys: set[str]) -> bool:
    n = fold(name)
    return any(k == n or (len(k) >= 6 and (k in n or n in k)) or fuzz.ratio(k, n) >= 85 for k in keys)


def _default_prior(cat: str, parsed: Parsed, plan: Plan, ctx: Context) -> float:
    g = CATEGORIES[cat].group
    if parsed.walk_intent:
        base = {"nature": 1.0, "sight": 0.95, "culture": 0.7, "food": 0.45, "shopping": 0.4, "quiet": 0.4}.get(g, 0.3)
    elif plan.tourist:
        base = {"sight": 1.0, "culture": 0.95, "nature": 0.7, "shopping": 0.5, "food": 0.5}.get(g, 0.3)
    elif parsed.surprise:
        base = {"culture": 0.9, "sight": 0.9, "entertainment": 0.8, "nature": 0.7, "night": 0.8, "active": 0.8}.get(g, 0.5)
    else:
        base = {"sight": 0.85, "culture": 0.85, "nature": 0.8, "food": 0.6, "shopping": 0.5, "quiet": 0.5}.get(g, 0.4)
    if ctx.max_outdoor_min < 60 and g == "nature":
        base -= 0.3
    return max(base, 0.1)


def _mmr(cands: list[Cand], k: int, single_cat: bool, lam: float = 0.7) -> list[Cand]:
    chosen: list[Cand] = []
    rest = cands[:60]
    while rest and len(chosen) < k:
        best, best_v = None, -1e9
        for c in rest:
            sim = 0.0
            for s in chosen:
                same_brand = c.poi.get("brand") and c.poi.get("brand") == s.poi.get("brand")
                if same_brand or c.poi["name"] == s.poi["name"]:
                    sim = max(sim, 1.0)
                elif not single_cat:
                    if c.poi["category"] == s.poi["category"]:
                        sim = max(sim, 0.8)
                    elif CATEGORIES[c.poi["category"]].group == CATEGORIES[s.poi["category"]].group:
                        sim = max(sim, 0.4)
                if hav_m(c.poi["lat"], c.poi["lon"], s.poi["lat"], s.poi["lon"]) < 40:
                    sim = max(sim, 0.9)
            v = lam * c.score - (1 - lam) * sim
            if v > best_v:
                best, best_v = c, v
        chosen.append(best)
        rest.remove(best)
    return chosen


def _events_by_poi(store: Store, ctx: Context, plan: Plan) -> dict[str, dict]:
    """Upcoming event sessions at a POI that start within the user's time window."""
    if not store.events:
        return {}
    out: dict[str, dict] = {}
    start = ctx.now
    end = ctx.now + dt.timedelta(minutes=max(plan.budget, 60) + 30)
    for e in store.events:
        pid = e.get("poi_id")
        if not pid:
            continue
        for s in e.get("sessions") or []:
            try:
                d = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
            except ValueError:
                continue
            if d.tzinfo is None:
                d = d.replace(tzinfo=ctx.now.tzinfo)
            if start <= d <= end:
                if pid not in out or d < out[pid]["_dt"]:
                    out[pid] = {"title": e["title"], "starts_at": d.astimezone(ctx.now.tzinfo).strftime("%H:%M"),
                                "url": e.get("url"), "source": e["source"],
                                "price_from": str(e["price_from"]) if e.get("price_from") not in (None, "") else None, "_dt": d}
                break
    return out


def needs_summary(needs: set[str]) -> list[str]:
    return [NEED_LABEL[n] for n in needs if n in NEED_LABEL]


_ = (WALK_M_PER_MIN, SLOW_WALK_M_PER_MIN)

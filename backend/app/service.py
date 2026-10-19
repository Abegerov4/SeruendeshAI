"""Request orchestration: parse -> context -> retrieve/rank -> route -> generate -> validate -> respond."""
from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import json
import logging
import time
import uuid
from dataclasses import dataclass

import httpx
import numpy as np

from app.categories import CATEGORIES, CONTRACT_CATEGORY, label
from app.config import get_settings
from app.context import Context, build_context, fetch_weather, parse_now, weather_out
from app.embedder import Embedder
from app.features import cuisine_labels, describe, feature_labels
from app.generate import GenOut, generate, template_todo, template_why, validate
from app.geo import WalkGraph, hav_m, in_astana, round_coord
from app.i18n import t, weekday
from app.llm import client as llm_client
from app.llm import parse as llm_parse
from app.llm import usage_begin, usage_summary
from app.planner import plan_route, route_wanted
from app.guards import mask_pii, strip_injection
from app.query import (PARSE_SYSTEM, LLMParsed, Parsed, deadline_minutes, is_off_topic, merge_llm, parse_rules,
                       resolve_landmark, split_mentions)
from app.retrieval import Cand, Plan, rank
from app.schemas import RecommendRequest
from app.store import Store
from app.textnorm import fold

log = logging.getLogger("app.service")
DEFAULT_ORIGIN = ("baiterek", 51.128288, 71.430455)
DEADLINE_BUFFER = {"flight": 30, "train": 15, "meeting": 5}  # safety margin on top of the computed trip back


@dataclass
class Runtime:
    store: Store
    graph: WalkGraph | None
    poi_nodes: np.ndarray | None
    poi_snap: np.ndarray | None
    embedder: Embedder | None
    http: httpx.AsyncClient
    cache: dict


def snap_pois(store: Store, graph: WalkGraph | None):
    if graph is None:
        return None, None
    d, i = graph.snap(store.lat, store.lon)
    return i.astype(np.int64), d.astype(np.float64)


def _landmark_by_key(store: Store, key: str) -> dict | None:
    return next((g for g in store.gazetteer if g.get("landmark_key") == key), None)


def _strip_terms(text: str, keys: list[str]) -> str:
    s = fold(text)
    for k in sorted(keys, key=len, reverse=True):
        if len(k) >= 3:
            s = s.replace(k, " ")
    return " ".join(s.split())


def _resolve_origin(req: RecommendRequest, parsed: Parsed, store: Store, notes: list[str], lang: str, hit=None):
    """Rounded GPS (inside Astana) > where the text says the user is > LLM landmark > UI landmark."""
    if req.location:
        lat, lon = round_coord(req.location.lat), round_coord(req.location.lon)
        if in_astana(lat, lon):
            near = min(store.gazetteer, key=lambda g: (g["lat"] - lat) ** 2 + (g["lon"] - lon) ** 2 if g["kind"] in ("landmark", "place") else 9)
            dist = float(hav_m(lat, lon, near["lat"], near["lon"]))
            lbl = {"ru": f"~ район «{near['name']}» (округлено)", "kk": f"~ «{near['name']}» маңы (дөңгелектенген)",
                   "en": f"~ near «{near['name']}» (rounded)"}[lang] if dist < 1500 else {"ru": "~ ваша локация (округлено до 100 м)",
                   "kk": "~ сіздің орналасуыңыз (100 м-ге дейін)", "en": "~ your location (rounded to 100 m)"}[lang]
            return (lat, lon), {"source": "gps_rounded", "label": lbl, "precision_m": 100}, None
        notes.append(t("note_outside_city", lang))
    if not hit and parsed.landmark_text:
        hit = resolve_landmark(parsed.landmark_text, store.gazetteer)
    if hit:
        return (hit["lat"], hit["lon"]), {"source": "text_landmark", "label": hit["name"], "precision_m": 50}, hit
    if req.landmark:
        g = resolve_landmark(req.landmark, store.gazetteer)
        if g:
            return (g["lat"], g["lon"]), {"source": "landmark", "label": g["name"], "precision_m": 50}, g
    return None, {"source": "none", "label": None, "precision_m": 0}, None


def _target_ids(store: Store, dests: list[dict]) -> set[str]:
    """POIs the user explicitly wants to go to ("хочу в Хан Шатыр"): always considered, never dropped as origin."""
    out: set[str] = set()
    for g in dests:
        if g.get("poi_id"):
            out.add(g["poi_id"])
            continue
        d = hav_m(g["lat"], g["lon"], store.lat, store.lon)
        for i in np.argsort(d)[:5]:
            if d[i] <= 250 and any(k in fold(store.pois[i]["name"]) or fold(store.pois[i]["name"]) in k for k in g["keys"] if len(k) >= 4):
                out.add(store.pois[i]["id"])
    return out


def _cache_key(req: RecommendRequest, now: dt.datetime) -> str:
    d = req.model_dump()
    if d.get("location"):
        d["location"] = {k: round(v, 3) for k, v in d["location"].items()}
    d["query"] = " ".join((d.get("query") or "").lower().split())
    d["now"] = now.strftime("%Y-%m-%d %H") + str(now.minute // 15)
    return hashlib.sha1(json.dumps(d, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


async def recommend(rt: Runtime, req: RecommendRequest) -> dict:
    s = get_settings()
    t0 = time.perf_counter()
    meter, mark = usage_begin()  # tokens of every LLM call made below (parse + generation)
    now = parse_now(req.now)
    key = _cache_key(req, now)
    hit = rt.cache.get(key)
    if hit and time.time() - hit[0] < s.response_cache_ttl_s:
        out = json.loads(hit[1])
        out["request_id"] = uuid.uuid4().hex[:12]
        out["llm"]["usage"] = usage_summary([])  # served from cache: nothing spent
        log.info("recommend id=%s cached tokens_in=0 tokens_out=0 cost_usd=0", out["request_id"])
        return out

    raw_query = req.query or ""
    safe_query, had_pii = mask_pii(raw_query)          # phones/emails/IINs never reach the LLM or logs
    safe_query, had_injection = strip_injection(safe_query)
    req = req.model_copy(update={"query": safe_query})
    rules = parse_rules(req.query)
    text_hit, dest_entries = split_mentions(req.query, rt.store.gazetteer) if req.query else (None, [])
    query_wo_landmark = _strip_terms(req.query, text_hit["keys"] + [fold(text_hit["name"])]) if text_hit else req.query
    # parse (LLM), weather and query embedding run concurrently
    llm_task = None
    if req.query.strip() and llm_client() is not None:
        llm_task = asyncio.create_task(llm_parse(LLMParsed, PARSE_SYSTEM, req.query.strip()[:500],
                                                 models=[s.llm_parse_model], timeout_s=s.parse_timeout_s,
                                                 max_output_tokens=500))
    wx_task = asyncio.create_task(fetch_weather(rt.http)) if s.weather_enabled and not req.now else None
    emb_task = None
    if rt.embedder is not None and rt.store.emb is not None and req.query.strip():
        emb_task = asyncio.get_running_loop().run_in_executor(None, rt.embedder.query, query_wo_landmark[:300] or req.query[:300])
    llm_parsed, parse_model = None, None
    if llm_task:
        llm_parsed, parse_model, _ = await llm_task
    parsed = merge_llm(rules, llm_parsed)
    weather = await wx_task if wx_task else None
    if req.weather is not None:
        w = req.weather
        weather = {"temperature_2m": w.temperature_c, "apparent_temperature": w.feels_like_c, "wind_speed_10m": w.wind_ms,
                   "wind_gusts_10m": w.wind_ms * 1.4, "precipitation": 1.0 if w.precipitation else 0.0,
                   "snowfall": 1.0 if (w.precipitation and w.temperature_c < 0) else 0.0, "override": True}
    qvec = await emb_task if emb_task else None

    has_text = sum(ch.isalpha() for ch in (req.query or "")) >= 3
    lang = req.lang or (parsed.lang if has_text else "ru")  # explicit UI language wins (team contract)
    if lang not in ("ru", "kk", "en"):
        lang = "ru"
    notes: list[str] = []
    if had_pii:
        notes.append(t("note_pii", lang))
    if had_injection:
        notes.append(t("note_injection", lang))

    # not about going somewhere in the city ("напиши код", "кто президент США"): say what Seru does instead
    place_signal = bool(rules.categories or rules.walk_intent or rules.wants_event or text_hit or dest_entries)
    off_topic = (llm_parsed.off_topic and not place_signal) if llm_parsed is not None else is_off_topic(req.query, place_signal)
    if off_topic:
        return _empty_response(rt, req, parsed, now, lang, t0, notes, t("off_topic", lang), meter[mark:], parse_model,
                               off_topic=True)

    origin, origin_info, hit = _resolve_origin(req, parsed, rt.store, notes, lang, text_hit)
    exclude_keys: set[str] = set()
    target_ids = _target_ids(rt.store, dest_entries)
    if hit and origin_info["source"] in ("text_landmark", "landmark"):
        exclude_keys = set(hit["keys"]) | {fold(hit["name"])}
        parsed.search_text = _strip_terms(parsed.search_text, list(exclude_keys))
        parsed.keywords = [k for k in parsed.keywords if not any(e in fold(k) for e in exclude_keys if len(e) >= 4)]
    prof = req.profile
    with_child = req.with_child if req.with_child is not None else (
        (prof is not None and prof.with_kids) or "kids" in parsed.needs or parsed.party == "family_kids")
    if with_child:
        parsed.needs.add("kids")
    accessibility = req.accessibility if req.accessibility is not None else (
        (prof is not None and prof.accessibility) or "wheelchair" in parsed.needs)
    if accessibility:
        parsed.needs.add("wheelchair")
    tourist = req.tourist if req.tourist is not None else (
        (prof is not None and prof.tourist) or parsed.tourist or parsed.deadline_kind == "flight")
    if parsed.group_size is None and (req.group_size or (prof.group_size if prof and prof.group_size > 1 else None)):
        parsed.group_size = req.group_size or prof.group_size
    ctx: Context = build_context(now, weather, with_child)

    # --- plan: mode, speed, budget, deadline, reach
    req_mode = req.travel_mode or req.mode
    out_mode = req_mode or parsed.travel_mode or "walk"
    mode = "car" if out_mode == "transit" else out_mode
    airport = _landmark_by_key(rt.store, "airport")
    dl = deadline_minutes(parsed, now) if parsed.deadline_kind else None
    if origin is None:
        return _empty_response(rt, req, parsed, now, lang, t0, notes, t("ask_location", lang), meter[mark:], parse_model)
    if dl is not None and parsed.deadline_kind == "flight" and airport and \
            float(hav_m(origin[0], origin[1], airport["lat"], airport["lon"])) < 4000 and req_mode is None:
        mode = out_mode = "car"  # nothing is walkable from the terminal
    if ctx.max_outdoor_min == 0 and mode == "walk" and req_mode is None:
        mode = out_mode = "car"  # too cold/windy to walk: plan by taxi
        notes.append(t("note_taxi_cold", lang))
    m_per_min = 60.0 if (with_child or accessibility) else 75.0
    if ctx.winter or ctx.snowing:
        m_per_min /= 1.1
    budget = req.time_budget_min or parsed.time_budget_min or 60
    plan = Plan(origin=origin, mode=mode, m_per_min=m_per_min, budget=budget, t_max=0, radius_m=0,
                with_child=with_child, accessibility=accessibility, tourist=tourist, transit=out_mode == "transit")
    if dl is not None:
        buf = DEADLINE_BUFFER.get(parsed.deadline_kind or "meeting", 30)
        back = airport if parsed.deadline_kind == "flight" else _landmark_by_key(rt.store, "nurly_zhol") \
            if parsed.deadline_kind == "train" else None
        plan.deadline_min, plan.deadline_buffer = dl, buf
        plan.deadline_back_target = (back["lat"], back["lon"]) if back else origin
        plan.budget = budget = max(15, min(req.time_budget_min or 10 ** 6, dl - buf))
        notes.append(t("note_deadline", lang, t=(now + dt.timedelta(minutes=dl - buf)).strftime("%H:%M")))
        if parsed.deadline_kind == "flight":
            notes.append(t("note_flight_assumption", lang, m=dl))
        if mode == "walk" and back and float(hav_m(origin[0], origin[1], back["lat"], back["lon"])) > 6000:
            notes.append(t("note_taxi_back", lang))
    refine = set(req.refine or [])
    if "no_coffee" in refine:
        parsed.avoid = list(dict.fromkeys(parsed.avoid + ["cafe", "sweets"]))
        parsed.categories = [c for c in parsed.categories if c not in ("cafe", "sweets")]
        parsed.soft_categories = [c for c in parsed.soft_categories if c not in ("cafe", "sweets")]
    if "indoor" in refine:
        parsed.needs.add("indoor")
        plan.filters.append("indoor_only")
    share = 0.5 if (parsed.walk_intent or parsed.wants_route) else 0.4
    if mode == "walk":
        plan.t_max = int(min(max(share * budget, 8), 35))
        if ctx.max_outdoor_min < 60:
            plan.t_max = max(6, min(plan.t_max, ctx.max_outdoor_min + 5))
    else:
        plan.t_max = int(min(max(0.35 * budget, 10), 45))
    if "closer" in refine:
        plan.t_max = max(5, int(plan.t_max * 0.5))
    plan.radius_m = int(plan.t_max * m_per_min / 1.28) if mode == "walk" else int(max(plan.t_max - 5, 3) * 41000 / 60 / 1.3 / 1.35)

    cands, considered = [], []
    if dl is not None and dl - plan.deadline_buffer < 30:
        notes.append(t("note_deadline_tight", lang))
    else:
        cands, considered = rank(rt.store, rt.graph, rt.poi_nodes, rt.poi_snap, parsed, plan, ctx, lang, qvec,
                                 exclude_keys=exclude_keys, target_ids=target_ids)

    route = None
    if route_wanted(parsed, req.want_route, plan, len(cands)):
        returns = parsed.walk_intent and mode == "walk" and dl is None
        route = plan_route(cands, plan, ctx, rt.graph, rt.store.river, lang, returns=returns)

    # --- generation (LLM) with validation, else templates
    gen: GenOut | None = None
    model, gen_ms, cmap = None, 0, {}
    route_stops = route["stops"] if route else None
    if cands and llm_client() is not None:
        out, model, gen_ms, cmap = await generate(cands, route_stops, ctx, plan, parsed, req.query or "", lang)
        gen = validate(out, cmap, route_stops, lang) if out else None
        if gen is None:
            model = None
    if cands and gen is None:
        chosen = route_stops or cands[:3]
        cmap = {f"c{i + 1}": c for i, c in enumerate(cands[:10])}
        inv = {id(c): k for k, c in cmap.items()}
        from app.generate import GenPick
        gen = GenOut(summary="", picks=[GenPick(cand=inv[id(c)], why=template_why(c, lang), what_to_do=template_todo(c, lang),
                                                visit_min=c.visit_min) for c in chosen], idea=None)
        if llm_client() is not None or s.llm_enabled:
            notes.append(t("note_template", lang))

    items, ideas, missed = [], [], []
    if gen:
        for rank_i, pk in enumerate(gen.picks, 1):
            items.append(_item(cmap[pk.cand], pk.why, pk.what_to_do, pk.visit_min, rank_i, plan, lang, out_mode))
        if gen.idea and gen.idea.text and gen.idea.near in cmap:
            ideas.append(_idea_item(gen.idea, cmap[gen.idea.near], len(items) + 1, plan, lang, out_mode))

    # route output (ids must match item ids)
    route_out = None
    if route:
        ids = [c.poi["id"] for c in route["stops"]]
        id_of = {0: "start"} | {i + 1: c.poi["id"] for i, c in enumerate(route["pool"])}
        legs = [{"from_id": id_of[leg["from"]], "to_id": id_of[leg["to"]], "distance_m": leg["distance_m"],
                 "travel_min": leg["travel_min"], "polyline": leg["polyline"], "geometry": leg["geometry"]} for leg in route["legs"]]
        names = " → ".join(c.poi["name"] for c in route["stops"])
        back_txt = t("route_back", lang, m=route["back_min"]) if route.get("back_min") else ""
        summ = t("route_summary", lang, stops=names, total=route["total_min"], travel=route["travel_min"],
                 visit=route["visit_min"], back=back_txt)
        if route["returns_to_start"]:
            summ += t("route_return", lang)
        route_out = {"order": ids, "legs": legs, "total_min": route["total_min"], "fits_budget": route["fits_budget"],
                     "returns_to_start": route["returns_to_start"], "summary": summ}

    # --- notes (transparency)
    if ctx.weather and ctx.max_outdoor_min < 60:
        notes.append(t("note_cold", lang, t=round(ctx.weather["apparent_temperature"]), w=round(ctx.weather["wind_speed_10m"]), m=ctx.max_outdoor_min))
    if ctx.is_dark and (parsed.walk_intent or "park" in parsed.categories or with_child):
        notes.append(t("note_dark", lang))
    if ctx.holiday:
        notes.append(t("note_holiday", lang, h=ctx.holiday))
    if with_child and now.hour >= 21:
        notes.append(t("note_child_night", lang))
    if "power_outlets" in parsed.needs:
        notes.append(t("note_power", lang))
    if "quiet" in parsed.needs:
        notes.append(t("note_quiet", lang))
    if any(it["event"] for it in items):
        notes.append(t("note_event_source", lang))
    if plan.outside_graph and mode == "walk":
        notes.append(t("note_outside_graph", lang))
    if out_mode == "transit":
        notes.append(t("note_transit", lang))
    notes.extend(plan.relaxations)

    # a place the user named but we could not include (closed, too far): say so instead of silently dropping it
    shown_ids = {it["poi_id"] for it in items}
    for g in dest_entries:
        ids = _target_ids(rt.store, [g])
        if ids and not ids & shown_ids:
            names = {fold(rt.store.pois[rt.store.by_id[i]]["name"]) for i in ids if i in rt.store.by_id}
            reason = next((c["reason"] for c in considered if fold(c["name"]) in names), t("rej_unreachable", lang))
            missed.append(t("note_target_missing", lang, name=g["name"], reason=reason))
    notes[:0] = missed

    poi_items = [it for it in items if it["source"] == "poi_data"]
    shown = {fold(it["name"]) for it in items}
    considered = [c for c in considered if fold(c["name"]) not in shown]
    if poi_items:
        nm = ", ".join(it["name"] for it in poi_items)
        summary = (gen.summary if gen and gen.summary else
                   t("summary", lang, n=len(poi_items), places=t("place_1" if len(poi_items) == 1 else "place_2", lang), names=nm))
    else:
        summary = t("summary_none", lang)
    if missed:
        summary = f"{missed[0]} {summary}"
    plan.funnel["shown"] = len(poi_items)

    filters = []
    if with_child:
        filters.append({"ru": "с ребёнком", "kk": "баламен", "en": "with kids"}[lang])
    if accessibility:
        filters.append({"ru": "без ступенек", "kk": "баспалдақсыз", "en": "step-free"}[lang])
    if tourist:
        filters.append({"ru": "турист", "kk": "турист", "en": "tourist"}[lang])
    if parsed.night:
        filters.append({"ru": "вечер/ночь", "kk": "кеш/түн", "en": "evening/night"}[lang])
    filters += [label(c, lang) for c in parsed.categories[:4]]
    rl = {"closer": {"ru": "ближе", "kk": "жақынырақ", "en": "closer"},
          "no_coffee": {"ru": "без кофе", "kk": "кофесіз", "en": "no coffee"},
          "indoor": {"ru": "в помещении", "kk": "жабық орында", "en": "indoors"}}
    filters += [rl[r][lang] for r in sorted(refine)]

    ds = ["OpenStreetMap (ODbL)", "Wikidata (CC0)", "Wikipedia (CC BY-SA)"]
    if "overture" in rt.store.manifest.get("sources", {}):
        ds.append("Overture Maps (CDLA)")
    if "team_bigdata" in rt.store.manifest.get("sources", {}):
        ds.append("CityPass Astana (факты со ссылкой)")
    if rt.store.events:
        ds.append("Ticketon / Sxodim")
    if ctx.weather:
        ds.append("Open-Meteo (CC BY 4.0)")
    used = {
        "location_source": "gps_rounded" if origin_info["source"] == "gps_rounded" else "landmark",
        "location_label": origin_info["label"], "radius_m": plan.radius_m, "time_budget_min": plan.budget,
        "mode": out_mode, "filters": filters, "now": now.isoformat(timespec="seconds"),
        "location": {**origin_info, "lat": round(origin[0], 3), "lon": round(origin[1], 3)},
        "local_time": now.strftime("%H:%M"), "weekday": weekday(now.weekday(), lang), "is_holiday": ctx.holiday,
        "is_dark": ctx.is_dark, "weather": weather_out(ctx, lang),
        "speed_kmh": round(m_per_min * 60 / 1000, 1) if mode == "walk" else (18.0 if out_mode == "transit" else 25.0),
        "party": "family_kids" if with_child else (parsed.party or ("tourist" if tourist else "solo")),
        "parsed_from_query": {"categories": parsed.categories, "preferences": parsed.soft_categories,
                              "needs": sorted(parsed.needs), "time_budget_min": parsed.time_budget_min,
                              "deadline": parsed.deadline_kind, "deadline_in_min": dl, "landmark": parsed.landmark_text,
                              "night": parsed.night, "surprise": parsed.surprise,
                              "parser": parsed.source + (f" ({parse_model})" if parse_model else "")},
        "relaxations": plan.relaxations, "funnel": plan.funnel, "data_sources": ds,
        "data_built_at": rt.store.manifest.get("built_at"), "privacy": t("privacy", lang),
    }
    resp = {
        "api_version": "1.0", "request_id": uuid.uuid4().hex[:12], "lang": lang, "summary": summary,
        "recommendations": items, "ideas": ideas, "route": route_out, "used_context": used, "considered": considered[:4],
        "notes": list(dict.fromkeys(notes)), "disclaimer": t("disclaimer", lang), "ai_generated": True,
        "llm": {"mode": "llm" if model else "template", "model": model, "latency_ms": int((time.perf_counter() - t0) * 1000),
                "usage": usage_summary(meter[mark:])},
        "off_topic": False,
    }
    if model or llm_client() is None:
        rt.cache[key] = (time.time(), json.dumps(resp, ensure_ascii=False))
    if len(rt.cache) > 500:
        for k in sorted(rt.cache, key=lambda k: rt.cache[k][0])[:100]:
            rt.cache.pop(k, None)
    u = resp["llm"]["usage"]  # one line per request: no query text, no coordinates
    log.info("recommend id=%s lang=%s mode=%s budget=%s items=%d route=%s llm=%s %dms tokens_in=%d tokens_out=%d cost_usd=%s",
             resp["request_id"], lang, mode, plan.budget, len(items), bool(route_out), model or "template",
             resp["llm"]["latency_ms"], u["input_tokens"], u["output_tokens"], u["cost_usd"])
    return resp


def _badges(c: Cand, plan: Plan) -> list[str]:
    p, cat = c.poi, CATEGORIES[c.poi["category"]]
    ind = p.get("indoor") if p.get("indoor") is not None else cat.indoor
    b = ["indoor"] if ind else ["outdoor"] if ind is False else []
    if cat.kids or p.get("features", {}).get("kids_area"):
        b.append("kids")
    if p.get("popularity", 0) > 0.5:
        b.append("popular")
    elif c.parts.get("pop", 0) > 0.35 and p.get("popularity", 0) < 0.2 and p.get("description_source") != "template":
        b.append("hidden_gem")
    if cat.night:
        b.append("night")
    if p.get("features", {}).get("free") or p["category"] in ("park", "garden", "monument", "artwork", "playground"):
        b.append("free")
    if c.event:
        b.append("event")
    return b


def _contract_open(op: dict) -> tuple[str, str]:
    """Our 5-state hours model -> team contract (open|closed|unknown, high|low|none)."""
    st, conf = op["status"], op["confidence"]
    if st in ("open", "closing_soon"):
        return "open", "high" if conf in ("high", "medium") else "low"
    if st == "always":
        return "unknown", "none"  # public space without listed hours: we don't claim it is open
    if st == "closed":
        return "closed", "high" if conf in ("high", "medium") else "low"
    return "unknown", "none"


def _item(c: Cand, why: str, todo: str, visit: int, rank_i: int, plan: Plan, lang: str, out_mode: str) -> dict:
    p = c.poi
    srcs = list(p.get("sources", []))
    url = p.get("source_url")  # exactly the dataset value (team contract), website is a separate field
    if c.event:
        srcs.append(c.event["source"])
    w = p.get("features", {}).get("wheelchair")
    lo, hi = c.visit_range
    room = plan.budget - c.travel_min - (c.return_min or 0)  # time left for the visit itself
    visit = int(max(5, min(visit, room)))
    vmin = [max(5, min(visit, lo)), max(visit, min(hi, max(room, visit)))]
    ost, oconf = _contract_open(c.opening)
    straight = int(round(float(hav_m(plan.origin[0], plan.origin[1], p["lat"], p["lon"]))))
    return {
        # team contract §3.3
        "poi_id": p["id"], "name": p.get("names", {}).get(lang) or p["name"],
        "category": CONTRACT_CATEGORY.get(p["category"], "other"), "lat": p["lat"], "lon": p["lon"],
        "distance_m": straight, "travel_min": max(1, c.travel_min), "why": why, "visit_min": vmin, "what_to_do": todo,
        "open_status": ost, "open_confidence": oconf, "source": "poi_data",
        "source_url": url if (url or "").startswith("http") else None, "rating": None,
        "website": p.get("website") if (p.get("website") or "").startswith("http") else None,
        # extensions
        "rank": rank_i, "category_detail": p["category"], "category_label": label(p["category"], lang),
        "icon": CATEGORIES[p["category"]].icon, "walk_distance_m": int(round(c.distance_m / 10) * 10),
        "travel_mode": out_mode, "visit_suggested_min": visit, "leave_by": c.leave_by,
        "opening": {k: c.opening.get(k) for k in ("status", "confidence", "label", "raw", "next_change")},
        "source_label": t("src_poi", lang), "data_sources": srcs, "popularity": p.get("popularity"),
        "features": feature_labels(p.get("features", {}), lang),
        "accessibility": w if w in ("yes", "limited", "no") else "unknown", "badges": _badges(c, plan),
        "event": ({k: c.event[k] for k in ("title", "starts_at", "url", "source", "price_from")} if c.event else None),
        "address": p.get("address"), "description": (describe(p, lang) or "")[:400] or None,
        "description_source": p.get("description_source"), "description_url": p.get("description_url"),
        "phone": p.get("phone"), "instagram": p.get("instagram"), "cuisine": cuisine_labels(p.get("cuisine"), lang) or None,
        "photo": p.get("photo"),  # Wikimedia Commons photo with author and licence, or null (UI shows a category cover)
    }


def _idea_item(idea, anchor: Cand, rank_i: int, plan: Plan, lang: str, out_mode: str) -> dict:
    """An AI idea is anchored to one of the picked places; it carries no facts of its own."""
    p = anchor.poi
    return {
        "poi_id": f"idea-{rank_i}", "name": idea.title or t("src_generated", lang),
        "category": CONTRACT_CATEGORY.get(p["category"], "other"), "lat": p["lat"], "lon": p["lon"],
        "distance_m": int(round(float(hav_m(plan.origin[0], plan.origin[1], p["lat"], p["lon"])))),
        "travel_min": max(1, anchor.travel_min), "why": idea.text, "visit_min": [5, 20], "what_to_do": idea.text,
        "open_status": "unknown", "open_confidence": "none", "source": "generated", "source_url": None, "rating": None,
        "website": None,
        "rank": rank_i, "category_detail": "idea", "category_label": t("src_generated", lang), "icon": "sparkles",
        "walk_distance_m": None, "travel_mode": out_mode, "visit_suggested_min": 10, "leave_by": None,
        "opening": {"status": "unknown", "confidence": "low", "label": t("oh_unknown", lang), "raw": None, "next_change": None},
        "source_label": t("src_generated", lang), "data_sources": ["llm"], "popularity": None, "features": [],
        "accessibility": "unknown", "badges": ["ai_idea"], "event": None,
        "address": f"{t('idea_near', lang)} {p.get('names', {}).get(lang) or p['name']}",
        "description": None, "description_source": "generated",
    }


def _empty_response(rt: Runtime, req: RecommendRequest, parsed: Parsed, now: dt.datetime, lang: str, t0: float,
                    notes: list[str], message: str, calls: list[dict], parse_model: str | None,
                    off_topic: bool = False) -> dict:
    """200 with empty recommendations + a clear message: no GPS / landmark (team contract) or an off-topic query."""
    usage = usage_summary(calls)
    resp = {
        "api_version": "1.0", "request_id": uuid.uuid4().hex[:12], "lang": lang, "summary": message,
        "recommendations": [], "route": None,
        "used_context": {
            "location_source": "none", "location_label": None, "radius_m": None,
            "time_budget_min": req.time_budget_min or parsed.time_budget_min or 60,
            "mode": req.travel_mode or req.mode or parsed.travel_mode or "walk", "filters": [],
            "now": now.isoformat(timespec="seconds"), "location": None, "local_time": now.strftime("%H:%M"),
            "weekday": weekday(now.weekday(), lang), "is_holiday": None, "is_dark": False, "weather": None,
            "speed_kmh": 4.5, "party": parsed.party or "solo",
            "parsed_from_query": {"categories": parsed.categories, "preferences": parsed.soft_categories,
                                  "needs": sorted(parsed.needs),
                                  "parser": parsed.source + (f" ({parse_model})" if parse_model else "")},
            "relaxations": [], "funnel": {"total": rt.store.size}, "data_sources": [],
            "data_built_at": rt.store.manifest.get("built_at"), "privacy": t("privacy", lang)},
        "ideas": [], "considered": [], "notes": list(dict.fromkeys(notes + [message])), "disclaimer": t("disclaimer", lang),
        "ai_generated": True,
        "llm": {"mode": "template", "model": None, "latency_ms": int((time.perf_counter() - t0) * 1000), "usage": usage},
        "off_topic": off_topic,
    }
    log.info("recommend id=%s lang=%s empty=%s tokens_in=%d tokens_out=%d cost_usd=%s", resp["request_id"], lang,
             "off_topic" if off_topic else "no_location", usage["input_tokens"], usage["output_tokens"], usage["cost_usd"])
    return resp

"""Request orchestration: parse -> context -> retrieve/rank -> route -> generate -> validate -> respond."""
from __future__ import annotations

import asyncio
import copy
import dataclasses
import datetime as dt
import hashlib
import json
import re
import logging
import time
import uuid
from dataclasses import dataclass

import httpx
import numpy as np

from app import decisions as judge
from app import tracing
from app.categories import CATEGORIES, CONTRACT_CATEGORY, label
from app.config import get_settings
from app.context import Context, build_context, fetch_weather, holiday_name, parse_now, weather_out
from app.embedder import Embedder
from app.evidence import accepted_details
from app.features import cuisine_labels, describe, feature_labels
from app.generate import GenOut, card, context_block, generate, strip_itinerary, template_todo, template_why, validate
from app.geo import WalkGraph, hav_m, in_astana, round_coord
from app.i18n import t, weekday
from app.hours import opening_status
from app.llm import client as llm_client
from app.llm import parse as llm_parse
from app.llm import usage_begin, usage_summary
from app.planner import plan_route, route_wanted
from app.guards import mask_location, mask_pii, strip_injection
from app.query import (HOME_CUE, NAV_INTENT, PARSE_SYSTEM, LLMParsed, Parsed, deadline_minutes, is_off_topic, merge_llm, parse_rules,
                       resolve_landmark, split_mentions, WALK_STOPS)
from app.retrieval import Cand, Plan, rank
from app.schemas import RecommendRequest
from app.service_answers import select_services, answer_services
from app.store import Store, display_name
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
    drive_graph: WalkGraph | None = None  # roads for car legs (one-way streets), None: car legs are estimates


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


# a summary that strings separate choices into one walk («сначала …, затем …», «one after another»)
_ITINERARY_SUMMARY = re.compile(r"\bзатем\b|\bпотом\b|по очереди|одно за другим|\bthen\b|one after another|after that|"
                                r"содан кейін|одан соң", re.IGNORECASE)


def entry_name(store: Store, g: dict, lang: str) -> str:
    """A gazetteer entry's name in the user's language: a curated landmark's own names, else its map place."""
    if g.get("names"):
        return display_name(g, lang)
    i = store.by_id.get(g.get("poi_id")) if g.get("poi_id") else None
    return display_name(store.pois[i], lang) if i is not None else g["name"]


def _resolve_origin(req: RecommendRequest, parsed: Parsed, store: Store, notes: list[str], lang: str, hit=None, dests=()):
    """Where the text says the user is > LLM landmark > rounded GPS (inside Astana) > UI landmark.
    «Я возле Хан Шатыра» wins over GPS: the user said it explicitly (and may be planning ahead)."""
    home_ref = bool(HOME_CUE.search(fold(req.query or "")))
    if not hit and req.home and (req.use_home or home_ref):  # «от дома» with a saved home; a named place still wins
        lat, lon = round_coord(req.home.lat), round_coord(req.home.lon)
        if in_astana(lat, lon):
            return (lat, lon), {"source": "home", "label": t("home_label", lang), "precision_m": 100}, None
    if home_ref and not req.home and not hit:
        notes.append(t("note_home_missing", lang))
    if not hit and parsed.landmark_text and not (home_ref and fold(parsed.landmark_text).startswith("дом")):
        hit = resolve_landmark(parsed.landmark_text, store.gazetteer)
        if hit is not None and any(hit["name"] == g["name"] for g in dests):
            hit = None  # the LLM read the place the user wants to go to as where they are
    if hit:
        name = entry_name(store, hit, lang)
        if req.location:
            notes.append(t("note_text_origin", lang, name=name))
        return (hit["lat"], hit["lon"]), {"source": "text_landmark", "label": name, "precision_m": 50}, hit
    if req.location:
        lat, lon = round_coord(req.location.lat), round_coord(req.location.lon)
        if in_astana(lat, lon) and req.location_label and req.location_label.strip():  # an address the client geocoded
            return (lat, lon), {"source": "gps_rounded", "label": "~ " + req.location_label.strip()[:120], "precision_m": 100}, None
        if in_astana(lat, lon):
            near = min(store.gazetteer, key=lambda g: (g["lat"] - lat) ** 2 + (g["lon"] - lon) ** 2 if g["kind"] in ("landmark", "place") else 9)
            dist = float(hav_m(lat, lon, near["lat"], near["lon"]))
            nn = entry_name(store, near, lang)  # the landmark in the answer's language, not as mapped
            lbl = {"ru": f"~ район «{nn}» (округлено)", "kk": f"~ «{nn}» маңы (шамамен)",
                   "en": f"~ near «{nn}» (rounded)"}[lang] if dist < 700 else {"ru": "~ ваша локация (округлено до 100 м)",
                   "kk": "~ сіздің орныңыз (шамамен 100 м)", "en": "~ your location (rounded to 100 m)"}[lang]
            return (lat, lon), {"source": "gps_rounded", "label": lbl, "precision_m": 100}, None
        notes.append(t("note_outside_city", lang))
    if req.landmark:
        g = resolve_landmark(req.landmark, store.gazetteer)
        if g:
            return (g["lat"], g["lon"]), {"source": "landmark", "label": entry_name(store, g, lang), "precision_m": 50}, g
    return None, {"source": "none", "label": None, "precision_m": 0}, None


VIEW_DECKS = ("baiterek", "nur_alem", "pyramid")


def _target_ids(store: Store, dests: list[dict]) -> set[str]:
    """POIs the user explicitly wants to go to ("хочу в Хан Шатыр"): always considered, never dropped as origin."""
    out: set[str] = set()
    for g in dests:
        if g.get("poi_id"):
            out.add(g["poi_id"])
            continue
        d = hav_m(g["lat"], g["lon"], store.lat, store.lon)
        for i in np.argsort(d)[:5]:
            p = store.pois[i]
            names = [fold(n) for n in (p["name"], *p.get("names", {}).values()) if n]  # «Ұлттық Мұражайы» is also «Национальный музей»
            if d[i] <= 250 and any(k in n or n in k for n in names for k in g["keys"] if len(k) >= 4):
                out.add(p["id"])
    return out


def _cache_key(req: RecommendRequest, now: dt.datetime) -> str:
    d = req.model_dump()
    if d.get("location"):
        d["location"] = {k: round(v, 3) for k, v in d["location"].items()}
    d["query"] = " ".join((d.get("query") or "").lower().split())
    # live requests share an answer within a 5-minute slot (an explicit `now` stays exact)
    d["now"] = now.isoformat() if req.now else now.replace(minute=now.minute - now.minute % 5, second=0, microsecond=0).isoformat()
    return hashlib.sha1(json.dumps(d, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _trace_request(req: RecommendRequest) -> tuple[dict, dict, list[str]]:
    """(input, metadata, tags) of the trace: the masked query and settings; never the position or home."""
    query = mask_location(mask_pii(req.query or "")[0])  # the same masking as before the LLM: no house numbers either
    settings = {k: v for k, v in req.model_dump(mode="json", exclude={"query", "location", "location_label", "home", "now",
                                                                       "weather"}).items()
                if v not in (None, [], {}, False)}
    settings["origin"] = "gps" if req.location else "landmark" if req.landmark else "home" if req.home else "none"
    return {"query": query}, settings, ["recommend", f"channel:{req.channel or 'web'}"]


def _trace_answer(out: dict) -> dict:
    return {"summary": out.get("summary"), "off_topic": out.get("off_topic", False),
            "recommendations": [{"poi_id": r["poi_id"], "name": r["name"], "category": r["category"],
                                 "travel_min": r["travel_min"], "why": r["why"]} for r in out.get("recommendations", [])],
            "route_stops": len((out.get("route") or {}).get("stops") or []), "notes": out.get("notes", []),
            "llm": out.get("llm")}


async def recommend(rt: Runtime, req: RecommendRequest, *, llm_parse_enabled: bool = True,
                    extra_targets: tuple[str, ...] = ()) -> dict:
    """One recommendation request, traced to Langfuse when it is configured (app/tracing.py)."""
    inp, meta, tags = _trace_request(req)
    with tracing.request("recommend", input=inp, metadata=meta, tags=tags) as root:
        out = await _recommend(rt, req, llm_parse_enabled=llm_parse_enabled, extra_targets=extra_targets)
        root.update(output=_trace_answer(out), metadata={"request_id": out.get("request_id")})
        return out


async def _recommend(rt: Runtime, req: RecommendRequest, *, llm_parse_enabled: bool = True,
                     extra_targets: tuple[str, ...] = ()) -> dict:
    """llm_parse_enabled=False: our own fixed queries (route ideas) are fully understood by the rules.
    extra_targets: landmark keys a themed walk should lead to (they still pass hours, darkness and the budget)."""
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
        tracing.update_current(metadata={"cache": "hit"})
        log.info("recommend id=%s cached tokens_in=0 tokens_out=0 cost_usd=0", out["request_id"])
        return out

    raw_query = req.query or ""
    safe_query, had_pii = mask_pii(raw_query)          # phones/emails/IINs never reach the LLM or logs
    safe_query = mask_location(safe_query)             # nor coordinates or house/flat numbers (the street stays)
    safe_query, had_injection = strip_injection(safe_query)
    req = req.model_copy(update={"query": safe_query})
    rules = parse_rules(req.query)
    selected_services = select_services(req.query, rt.store.services, req.service_id)
    if selected_services:
        lang = req.lang or rules.lang
        notes = ([t("note_pii",lang)] if had_pii else []) + ([t("note_injection",lang)] if had_injection else [])
        out = _empty_response(rt, req, rules, now, lang, t0, notes, t("ask_location", lang), [], None)
        services, summary, warnings = answer_services(selected_services,req.query,now,lang)
        out.update(service_results=services,summary=summary,notes=notes+warnings)
        origin, info, _ = _resolve_origin(req,rules,rt.store,[],lang)
        if origin:
            out["used_context"].update(location_source="gps_rounded" if info["source"] == "gps_rounded" else "landmark",
                location_label=info["label"],location={**info,"lat":round(origin[0],3),"lon":round(origin[1],3)})
        out["used_context"]["data_sources"] = sorted({e["source_url"] for s in services for e in s.get("evidence",[])})
        return out
    # with a real position a place named without «я у / возле» is where to go, not a silent new start
    has_position = bool(req.location and in_astana(round_coord(req.location.lat), round_coord(req.location.lon))
                        or req.home and (req.use_home or HOME_CUE.search(fold(req.query or ""))))
    text_hit, dest_entries = split_mentions(req.query, rt.store.gazetteer, has_position,
                                            asks_kind=lambda rest: bool(parse_rules(rest).categories)) if req.query else (None, [])
    query_wo_landmark = _strip_terms(req.query, text_hit["keys"] + [fold(text_hit["name"])]) if text_hit else req.query
    from app.food import is_food_refinement, parse_food_requirements
    nonfood_topic = any(CATEGORIES[c].group != "food" for c in rules.categories if c in CATEGORIES) or bool(
        re.search(r"такси|taxi|билет|ticket|рейс|flight",fold(req.query)))
    relax_food = bool(re.search(r"просто.*(?:поесть|покушать|кофе)|без\s+(?:этих\s+)?условий|забуд|any\s+food|just\s+(?:eat|food)|forget",fold(req.query)))
    if req.food_context and not nonfood_topic and not relax_food:
        # Context makes a standalone amount/diet phrase a food refinement.
        # Replace an explicitly revised dish or budget; retain the other wishes.
        fresh = parse_food_requirements("поесть "+req.query)
        if fresh or req.refine or is_food_refinement(query_wo_landmark):
            replaced = {r.kind for r in fresh if r.kind in {"menu","price"}}
            inherited = [r for r in req.food_context if r.kind not in replaced]
            rules.food_requirements = list({(r.kind,fold(r.text)):r for r in inherited+fresh}.values())
            rules.categories = ["restaurant", "cafe"]
    # parse (LLM), weather and query embedding run concurrently
    llm_task = None
    if req.query.strip() and llm_client() is not None and llm_parse_enabled:
        llm_task = asyncio.create_task(llm_parse(LLMParsed, PARSE_SYSTEM, req.query.strip()[:500],
                                                 models=[s.llm_parse_model], timeout_s=s.parse_timeout_s,
                                                 max_output_tokens=500, name="parse-query"))
    # the Decisions API's yes/no questions about the request run alongside the parse: no extra waiting
    intent_task = asyncio.create_task(judge.intent(req.query)) if req.query.strip() and llm_parse_enabled and judge.enabled() else None
    wx_task = asyncio.create_task(fetch_weather(rt.http)) if s.weather_enabled and not req.now else None
    emb_task = None
    if rt.embedder is not None and rt.store.emb is not None and req.query.strip():
        emb_task = asyncio.get_running_loop().run_in_executor(None, rt.embedder.query, query_wo_landmark[:300] or req.query[:300])
    llm_parsed, parse_model = None, None
    if llm_task:
        llm_parsed, parse_model, _ = await llm_task
    parsed = merge_llm(rules, llm_parsed)
    intent_p = await intent_task if intent_task else None
    intent_applied = apply_intent(parsed, intent_p, parse_answered=llm_parsed is not None)
    weather = await wx_task if wx_task else None
    if req.weather is not None:
        w = req.weather
        weather = {"temperature_2m": w.temperature_c, "apparent_temperature": w.feels_like_c, "wind_speed_10m": w.wind_ms,
                   "wind_gusts_10m": w.wind_ms * 1.4, "precipitation": 1.0 if w.precipitation else 0.0,
                   "snowfall": 1.0 if (w.precipitation and w.temperature_c < 0) else 0.0, "override": True,
                   "us_aqi": w.us_aqi, "pm2_5": None}
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
    if intent_p and "about_city" in intent_p:
        if off_topic and intent_p["about_city"] >= 0.9:  # the judge is sure it is about the city: answer, do not refuse
            off_topic = False
        elif llm_parsed is None and not place_signal and intent_p["about_city"] < 0.1:
            off_topic = True  # the parse did not answer in time; the judge is sure it is not about going anywhere
    if off_topic:
        return _empty_response(rt, req, parsed, now, lang, t0, notes, t("off_topic", lang), meter[mark:], parse_model,
                               off_topic=True)

    origin, origin_info, hit = _resolve_origin(req, parsed, rt.store, notes, lang, text_hit, dest_entries)
    exclude_keys: set[str] = set()
    target_ids = _target_ids(rt.store, dest_entries)
    view_decks = "view" in parsed.needs and not dest_entries
    if view_decks:
        # Astana's observation decks: Bayterek (97 m), the EXPO sphere and the top of the Pyramid
        target_ids |= _target_ids(rt.store, [g for k in VIEW_DECKS if (g := _landmark_by_key(rt.store, k))])
    navigate = bool(target_ids) and bool(NAV_INTENT.search(fold(req.query or "")))  # directions to a named place
    if extra_targets:
        target_ids |= _target_ids(rt.store, [g for k in extra_targets if (g := _landmark_by_key(rt.store, k))])
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
        (prof is not None and prof.tourist) or parsed.tourist or parsed.deadline_kind in ("flight", "airport_arrival"))
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
        outside = t("note_outside_city", lang)  # the position came, it is just not in Astana: say that, once
        return _empty_response(rt, req, parsed, now, lang, t0, [n for n in notes if n != outside],
                               outside if outside in notes else t("ask_location", lang), meter[mark:], parse_model)
    if dl is not None and parsed.deadline_kind in ("flight", "airport_arrival") and airport and \
            float(hav_m(origin[0], origin[1], airport["lat"], airport["lon"])) < 4000 and req_mode is None:
        mode = out_mode = "car"  # nothing is walkable from the terminal
    if ctx.max_outdoor_min == 0 and mode == "walk" and req_mode is None:
        mode = out_mode = "car"  # too cold/windy to walk: plan by taxi
        notes.append(t("note_taxi_cold", lang))
    m_per_min = 60.0 if (with_child or accessibility) else 75.0
    if ctx.winter or ctx.snowing:
        m_per_min /= 1.1
    free_budget = req.time_budget_min if req.time_budget_min is not None else parsed.time_budget_min
    budget = free_budget if free_budget is not None else 60
    plan = Plan(origin=origin, mode=mode, m_per_min=m_per_min, budget=budget, t_max=0, radius_m=0,
                with_child=with_child, accessibility=accessibility, tourist=tourist, transit=out_mode == "transit", evidence_date=ctx.now.date())
    if dl is not None:
        road_buffer = getattr(s, "deadline_road_uncertainty_min", 15)
        predeparture = (getattr(s, f"flight_{parsed.flight_type}_buffer_min", 180)
                        if parsed.deadline_kind == "flight" else 0)
        buf = predeparture + road_buffer if parsed.deadline_kind in ("flight", "airport_arrival") else DEADLINE_BUFFER.get(parsed.deadline_kind or "meeting", 30)
        back = airport if parsed.deadline_kind in ("flight", "airport_arrival") else _landmark_by_key(rt.store, "nurly_zhol") \
            if parsed.deadline_kind == "train" else None
        plan.deadline_min, plan.deadline_buffer = dl, buf
        plan.deadline_back_target = (back["lat"], back["lon"]) if back else origin
        plan.budget = budget = max(0, min(free_budget if free_budget is not None else 10 ** 6, dl - buf))
        by = (now + dt.timedelta(minutes=dl - buf)).strftime("%H:%M")
        if parsed.deadline_kind == "flight" and not predeparture:  # flight type unknown: one note says how the time is read
            notes.append(t("note_flight_free_time", lang, t=by, m=buf))
        else:
            notes.append(t("note_deadline", lang, t=by, m=buf))
            if parsed.deadline_kind == "flight":
                notes.append(t("note_flight_assumption", lang, m=predeparture, kind=parsed.flight_type))
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
    mixed = False
    if dl is not None and dl - plan.deadline_buffer < 30:
        notes.append(t("note_deadline_tight", lang))
    else:
        if navigate:
            plan.budget = max(plan.budget, 240)  # the trip itself is the goal; distance is shown, not used to filter
            plan.t_max = max(plan.t_max, 120)  # the street search reaches 2 × t_max: the whole city on foot
            plan.directions = True
        walk_cands = []
        if parsed.walk_mix and not navigate:
            # «кофе и прогулка»: places to walk, ranked on their own (a copy of the plan: ranking writes into it)
            walk_q = dataclasses.replace(parsed, categories=list(WALK_STOPS), soft_categories=[], food_requirements=[],
                                         meal_intent=False, search_text="прогулка парк сквер набережная вид", keywords=[])
            with tracing.observe("rank-walk-stops", as_type="retriever",
                                 input={"categories": list(WALK_STOPS), "mode": plan.mode, "budget_min": plan.budget}) as step:
                walk_cands, _ = rank(rt.store, rt.graph, rt.poi_nodes, rt.poi_snap, walk_q, copy.deepcopy(plan), ctx, lang,
                                     None, k=6, exclude_keys=exclude_keys)
                step.update(output=[{"poi_id": c.poi["id"], "name": c.poi.get("name"), "category": c.poi.get("category"),
                                     "travel_min": c.travel_min} for c in walk_cands])
        with tracing.observe("rank-candidates", as_type="retriever",
                             input={"search_text": parsed.search_text, "categories": parsed.categories,
                                    "needs": sorted(parsed.needs), "mode": plan.mode, "budget_min": plan.budget,
                                    "t_max_min": plan.t_max, "radius_m": plan.radius_m}) as step:
            cands, considered = rank(rt.store, rt.graph, rt.poi_nodes, rt.poi_snap, parsed, plan, ctx, lang, qvec,
                                     exclude_keys=exclude_keys, target_ids=target_ids)
            step.update(output=[{"poi_id": c.poi["id"], "name": c.poi.get("name"), "category": c.poi.get("category"),
                                 "travel_min": c.travel_min, "score": round(c.score, 3)} for c in cands[:10]],
                        metadata={"candidates": len(cands), "relaxations": list(plan.relaxations)})
        if walk_cands:
            mixed = True
            food = [c for c in cands if CATEGORIES[c.poi["category"]].group == "food"]
            seen = {c.poi["id"] for c in food}
            cands = food[:2] + [c for c in walk_cands if c.poi["id"] not in seen] + food[2:]
            plan.max_food_stops = 1
        if navigate:
            cands = [c for c in cands if c.poi["id"] in target_ids][:1] or cands
        elif dest_entries and target_ids and not any(c.poi["id"] in target_ids for c in cands):
            # the place the user wants to go to is past a walk's reach: show the way there with its honest time
            # instead of dropping it for whatever is near («хочу в Хан Шатыр» from across the river)
            short = plan.budget, plan.t_max, plan.radius_m, list(plan.relaxations)
            plan.budget, plan.t_max, plan.directions = max(plan.budget, 240), max(plan.t_max, 120), True
            with tracing.observe("rank-destination", as_type="retriever",
                                 input={"targets": sorted(target_ids), "mode": plan.mode, "budget_min": plan.budget}) as step:
                far, far_considered = rank(rt.store, rt.graph, rt.poi_nodes, rt.poi_snap, parsed, plan, ctx, lang, qvec,
                                           exclude_keys=exclude_keys, target_ids=target_ids)
                step.update(output=[{"poi_id": c.poi["id"], "name": c.poi.get("name"), "travel_min": c.travel_min}
                                    for c in far[:5]])
            far = [c for c in far if c.poi["id"] in target_ids][:1]
            if far:
                cands, considered, navigate = far, far_considered, True
                if mode == "walk" and far[0].travel_min > 60:
                    notes.append(t("note_far_walk", lang, m=int(far[0].travel_min)))
            else:
                plan.budget, plan.t_max, plan.radius_m, plan.relaxations = short
                plan.directions = False

    # the Decisions API checks every card against the request before the route and the text are made
    fit_info = {"checked": 0, "dropped": [], "ms": 0}
    if cands and not navigate and judge.enabled():
        cands, fit_info = await check_fit(cands, req.query or "", ctx, plan, parsed, lang, keep_ids=target_ids, keep_order=mixed)
        for c in fit_info["dropped"]:
            considered.insert(0, {"name": display_name(c.poi, lang), "reason": t("rej_fit", lang, p=round(c.match * 100))})

    route = None
    if not navigate and not (view_decks and req.want_route is None) and route_wanted(parsed, req.want_route, plan, len(cands)):
        returns = parsed.walk_intent and mode == "walk" and dl is None
        route_graph = rt.drive_graph if plan.mode == "car" else rt.graph
        route = plan_route(cands, plan, ctx, route_graph, rt.store.river, lang, returns=returns)
        if route is None and returns:  # a loop does not fit the time: a one-way walk does, and the answer says so
            route = plan_route(cands, plan, ctx, route_graph, rt.store.river, lang, returns=False)
            if route is not None:
                notes.append(t("note_route_one_way", lang))

    # --- generation (LLM) with validation, else templates
    gen: GenOut | None = None
    model, gen_ms, cmap = None, 0, {}
    route_stops = route["stops"] if route else None
    if cands and llm_client() is not None:
        out, model, gen_ms, cmap = await generate(cands, route_stops, ctx, plan, parsed, req.query or "", lang, req.channel)
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
        if route:
            # Route order, intervals and durations belong to the deterministic planner.
            picks = {cmap[pk.cand].poi["id"]: pk for pk in gen.picks if pk.cand in cmap}
            for rank_i, (i, arrive_min, visit) in enumerate(route["timeline"], 1):
                c = route["pool"][i - 1]
                pk = picks.get(c.poi["id"])
                opening = opening_status(c.poi, ctx.local_naive + dt.timedelta(minutes=arrive_min), visit, lang, ctx.holiday)
                item = _item(c, pk.why if pk else template_why(c, lang),
                             pk.what_to_do if pk else template_todo(c, lang), visit, rank_i, plan, lang, out_mode,
                             available_visit_min=visit)
                if item is None:
                    continue
                item["arrival_at"] = (ctx.now + dt.timedelta(minutes=arrive_min)).isoformat(timespec="seconds")
                item["departure_at"] = (ctx.now + dt.timedelta(minutes=arrive_min + visit)).isoformat(timespec="seconds")
                item["visit_min"] = [visit, visit]
                item["visit_suggested_min"] = visit
                item["opening"].update({k: opening.get(k) for k in ("status", "confidence", "label", "raw", "next_change")})
                item["open_status"], item["open_confidence"] = _contract_open(opening)
                items.append(item)
        else:
            for rank_i, pk in enumerate(gen.picks, 1):
                c = cmap[pk.cand]
                # A model may choose a duration within a range; revalidate its full interval.
                visit = max(c.visit_range[0], min(pk.visit_min, c.visit_range[1]))
                opening = opening_status(c.poi, ctx.local_naive + dt.timedelta(minutes=c.travel_min), visit, lang, ctx.holiday)
                if not opening["ok"]:
                    visit = c.visit_min
                item = _item(c, pk.why, pk.what_to_do, visit, rank_i, plan, lang, out_mode)
                if item is None:
                    continue
                # The advertised range must also fit, even when the suggestion is shorter.
                upper_opening = opening_status(c.poi, ctx.local_naive + dt.timedelta(minutes=c.travel_min),
                                               item["visit_min"][1], lang, ctx.holiday)
                if not upper_opening["ok"]:
                    item["visit_min"][1] = item["visit_suggested_min"]
                items.append(item)
        if gen.idea and gen.idea.text and gen.idea.near in cmap:
            ideas.append(_idea_item(gen.idea, cmap[gen.idea.near], len(items) + 1, plan, lang, out_mode))

    # route output (ids must match item ids)
    route_out = None
    if route:
        ids = [c.poi["id"] for c in route["stops"]]
        id_of = {0: "start"} | {i + 1: c.poi["id"] for i, c in enumerate(route["pool"])}
        legs = [{"from_id": id_of[leg["from"]], "to_id": id_of[leg["to"]], "distance_m": leg["distance_m"],
                 "travel_min": leg["travel_min"], "polyline": leg["polyline"], "geometry": leg["geometry"]} for leg in route["legs"]]
        names = " → ".join(display_name(c.poi, lang) for c in route["stops"])
        back_txt = t("route_back", lang, m=route["back_min"]) if route.get("back_min") else ""
        summ = t("route_summary", lang, stops=names, total=route["total_min"], travel=route["travel_min"],
                 visit=route["visit_min"], back=back_txt)
        if route["returns_to_start"]:
            summ += t("route_return", lang)
        route_out = {"order": ids, "legs": legs, "total_min": route["total_min"], "fits_budget": route["fits_budget"],
                     "returns_to_start": route["returns_to_start"], "back_min": route["back_min"], "summary": summ}

    # Without a scheduled route, every recommendation is a separate choice. Use
    # on-site actions only: model prose must not invent an unbudgeted multi-stop walk.
    if route_out is None:
        # separate choices, not a walk: the model's own words stay, minus any «затем направляйтесь к …»
        by_id = {c.poi["id"]: c for c in cmap.values()}
        for item in items:
            c = by_id.get(item["poi_id"])
            if c:
                others = [x["name"] for x in items if x is not item] + [display_name(o.poi, "ru") for o in cmap.values() if o is not c]
                item["why"] = strip_itinerary(item["why"], others) or template_why(c, lang)
                item["what_to_do"] = strip_itinerary(item["what_to_do"], others) or template_todo(c, lang)

    if route_out is not None and not route.get("returns_to_start"):
        # a one-way walk: the model must not promise «затем вернитесь к старту»
        for item in items:
            for f in ("why", "what_to_do"):
                if item.get(f):
                    item[f] = _BACK_TO_START.sub("", item[f]).strip(" ,;") or item[f]
                    if item[f] and item[f][-1] not in ".!?…":
                        item[f] += "."

    # --- notes (transparency)
    aqi = (ctx.weather or {}).get("us_aqi") or 0
    if aqi >= 101:
        notes.append(t("note_air", lang, a=round(aqi), p=round(ctx.weather.get("pm2_5") or 0)))
    if ctx.weather and ctx.max_outdoor_min < 60 and not (aqi >= 101 and (ctx.weather.get("apparent_temperature") or 0) > -10):
        notes.append(t("note_cold" if ctx.max_outdoor_min else "note_cold_0", lang, t=round(ctx.weather["apparent_temperature"]),
                       w=round(ctx.weather["wind_speed_10m"]), m=ctx.max_outdoor_min))
    if ctx.is_dark and (parsed.walk_intent or "park" in parsed.categories or with_child):
        notes.append(t("note_dark", lang))
    if ctx.holiday:
        notes.append(t("note_holiday", lang, h=holiday_name(ctx.now.date(), ctx.holiday, lang)))
    if with_child and now.hour >= 21:
        notes.append(t("note_child_night", lang))
    if "power_outlets" in parsed.needs:
        notes.append(t("note_power", lang))
    if "quiet" in parsed.needs:
        notes.append(t("note_quiet", lang))
    if any(it["event"] for it in items):
        notes.append(t("note_event_source", lang))
    # only when a place we actually show (or a leg we draw) used the straight-line estimate
    estimated = any(it["poi_id"] in plan.estimated_ids for it in items) or \
        any(leg["geometry"] == "straight" for leg in (route["legs"] if route else []))
    if plan.outside_graph and estimated and mode == "walk":
        notes.append(t("note_outside_graph", lang))
    if out_mode == "transit":
        notes.append(t("note_transit", lang))
    notes.extend(plan.relaxations)

    # a place the user named but we could not include (closed, too far): say so instead of silently dropping it
    shown_ids = {it["poi_id"] for it in items}
    for g in dest_entries:
        ids = _target_ids(rt.store, [g])
        if ids and not ids & shown_ids:
            names = {fold(display_name(rt.store.pois[rt.store.by_id[i]], lang)) for i in ids if i in rt.store.by_id}
            reason = next((c["reason"] for c in considered if fold(c["name"]) in names), t("rej_unreachable", lang))
            missed.append(t("note_target_missing", lang, name=entry_name(rt.store, g, lang), reason=reason))
    notes[:0] = missed

    poi_items = [it for it in items if it["source"] == "poi_data"]
    shown = {fold(it["name"]) for it in items}
    considered = [c for c in considered if fold(c["name"]) not in shown]
    if poi_items:
        nm = ", ".join(it["name"] for it in poi_items)
        model_summary = gen.summary if gen and gen.summary and not _ITINERARY_SUMMARY.search(gen.summary) else None
        summary = (route_out["summary"] if route_out else model_summary or
                   t("summary", lang, n=len(poi_items), places=t("place_1" if len(poi_items) == 1 else "place_2", lang), names=nm))
        if navigate and poi_items[0]["poi_id"] in target_ids and origin_info.get("label"):
            it = poi_items[0]  # «маршрут с AITU до ботсада»: say where from, where to and how far
            dm = it.get("walk_distance_m") or it.get("distance_m") or 0  # along the streets, like the card
            d = f"{dm / 1000:.1f} км".replace(".", ",") if lang != "en" and dm >= 1000 else f"{dm / 1000:.1f} km" if dm >= 1000 else f"{dm} м" if lang != "en" else f"{dm} m"
            summary = t("summary_nav", lang, a=origin_info["label"], b=it["name"], d=d, m=it.get("travel_min"),
                        how=t("how_car" if mode == "car" else "how_walk", lang))
            considered = []
    elif parsed.food_requirements:
        summary = t("summary_food_unverified", lang)
        notes.insert(0, summary)
    else:
        summary = t("summary_none", lang)
    if missed:
        summary = f"{missed[0]} {summary}"
    if parsed.deadline_kind == "flight" and dl is not None and plan.budget == 0 and not poi_items:
        summary = {"ru": "До вылета слишком мало времени для прогулки с запасом на дорогу и аэропорт. Лучше направиться в аэропорт. Уточни тип рейса и время вылета, если я понял их неверно.",
                   "kk": "Жол мен әуежайға арналған уақыт қорын ескерсек, ұшуға дейін серуендеуге уақыт аз. Әуежайға барған дұрыс. Рейс түрі мен ұшу уақытын нақтылаңыз.",
                   "en": "There is too little time before departure for a walk plus travel and the airport buffer. Head to the airport. Clarify your flight type and departure time if I misunderstood."}[lang]
        notes.insert(0, summary)
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
    if any("sxodim" in (c.poi.get("sources") or []) or "sxodim" in (c.poi.get("hours_source") or "") for c in cands):
        ds.append("Sxodim (места и часы, со ссылкой на карточку)")
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
                              "avoid": parsed.avoid, "avoid_labels": [label(c, lang) for c in parsed.avoid],
                              "category_labels": [label(c, lang) for c in parsed.categories],
                              "needs": sorted(parsed.needs), "time_budget_min": parsed.time_budget_min,
                              "food_requirements": [r.model_dump() for r in parsed.food_requirements],
                              "deadline": parsed.deadline_kind, "deadline_in_min": dl, "flight_type": parsed.flight_type,
                              "deadline_buffer_min": plan.deadline_buffer, "landmark": parsed.landmark_text,
                              "night": parsed.night, "surprise": parsed.surprise,
                              "parser": parsed.source + (f" ({parse_model})" if parse_model else "")},
        "relaxations": plan.relaxations, "funnel": plan.funnel, "data_sources": ds,
        "data_built_at": rt.store.manifest.get("built_at"), "privacy": t("privacy", lang),
        "ai_check": ({"engine": f"OpenAI Decisions API · {s.decisions_model}",
                      "intent": {k: round(v, 2) for k, v in (intent_p or {}).items()}, "intent_applied": intent_applied,
                      "checked": fit_info["checked"], "latency_ms": fit_info["ms"],
                      "dropped": [{"poi_id": c.poi["id"], "name": display_name(c.poi, lang), "match": round(c.match, 2)}
                                  for c in fit_info["dropped"]]} if intent_p or fit_info["checked"] else None),
    }
    resp = {
        "api_version": "1.0", "request_id": uuid.uuid4().hex[:12], "lang": lang, "summary": summary,
        "recommendations": items, "ideas": ideas, "navigate_to": (items[0]["poi_id"] if navigate and items and items[0]["poi_id"] in target_ids else None), "route": route_out, "used_context": used, "considered": considered[:4],
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


# --- the Decisions API as the auxiliary judge (app/decisions.py) -----------------------------------------

INTENT_STRONG = 0.92  # the parse answered: the judge only adds what it is nearly sure the parse missed
INTENT_ALONE = 0.8    # the parse did not answer in time: the judge's answers stand in for it
FIT_DROP = 0.12       # «подходит на 8%»: not shown while enough other places remain
FIT_STRONG = 0.7


def apply_intent(parsed: Parsed, probs: dict[str, float] | None, *, parse_answered: bool) -> list[str]:
    """Add the needs the judge is sure of and the parse missed. Never removes anything the user or the parse said;
    night and «something unusual» change the search a lot, so they are taken only when the parse did not answer."""
    if not probs:
        return []
    bar = INTENT_STRONG if parse_answered else INTENT_ALONE
    added = []
    for key, need in (("with_kids", "kids"), ("indoor", "indoor"), ("quiet", "quiet")):
        if probs.get(key, 0) >= bar and need not in parsed.needs and not (need == "kids" and parsed.party == "family_kids"):
            parsed.needs.add(need)
            added.append(key)
    if not parse_answered:
        if probs.get("night", 0) >= bar and not parsed.night:
            parsed.night = True
            added.append("night")
        if probs.get("unusual", 0) >= bar and not parsed.surprise:
            parsed.surprise = True
            added.append("unusual")
    return added


async def check_fit(cands: list[Cand], query: str, ctx: Context, plan: Plan, parsed: Parsed, lang: str, *,
                    keep_ids: set[str], keep_order: bool) -> tuple[list[Cand], dict]:
    """One yes/no question per card: «does this place fit the request right now?». Clear misfits are dropped while at
    least three places remain (a place the user named is never dropped); strong fits move ahead of the rest, the
    retrieval's diverse order is kept inside each group. Without an answer the cards stay as they were."""
    top = {f"c{i + 1}": c for i, c in enumerate(cands[:get_settings().decisions_fit_n])}
    cards = []
    for cid, c in top.items():
        d = card(c, cid, "ru")
        d["desc"] = d.get("desc", "")[:140]
        for k in ("desc_source", "popularity", "note"):
            d.pop(k, None)
        cards.append(d)
    situation = "; ".join(context_block(ctx, plan, parsed, "ru").splitlines()[1:])
    t1 = time.perf_counter()
    probs = await judge.fit(query, situation, cards)
    info = {"checked": 0, "dropped": [], "ms": int((time.perf_counter() - t1) * 1000)}
    if not probs:
        return cands, info
    for cid, c in top.items():
        c.match = probs.get(cid)
    info["checked"] = sum(c.match is not None for c in top.values())
    misfits = sorted((c for c in cands if c.match is not None and c.match < FIT_DROP and c.poi["id"] not in keep_ids),
                     key=lambda c: c.match)
    spare = len(cands) - min(3, len(cands))  # how many may go
    dropped = misfits[:max(0, spare)]
    kept = [c for c in cands if c not in dropped]
    if not keep_order:
        kept = [c for c in kept if (c.match or 0) >= FIT_STRONG] + [c for c in kept if (c.match or 0) < FIT_STRONG]
    info["dropped"] = dropped
    log.info("fit check: %d cards, dropped %d, %dms", info["checked"], len(dropped), info["ms"])
    return kept, info


def _badges(c: Cand, plan: Plan) -> list[str]:
    p, cat = c.poi, CATEGORIES[c.poi["category"]]
    ind = p.get("indoor") if p.get("indoor") is not None else p.get("features", {}).get("indoor")
    b = ["indoor"] if ind else ["outdoor"] if ind is False else []
    if p.get("kid_friendly") is True or p.get("features", {}).get("kids_area") is True:
        b.append("kids")
    if cat.night:
        b.append("night")
    if p.get("features", {}).get("free") is True:
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


_BACK_TO_START = re.compile(r"[,;]?\s*(?:\bа\s+)?(?:\b(?:затем|потом|после этого|и)\s+)?(?:\b(?:можно|стоит)\s+)?\b(?:вернуться|вернитесь|"
                            r"возвращайтесь|вернёмся|идите обратно|обратно)\b[^.!?]*|[,;]?\s*(?:then\s+)?(?:head|walk|go)\s+back\b[^.!?]*|"
                            r"[,;]?\s*(?:then\s+)?return\s+to\b[^.!?]*|[,;]?\s*кейін\s+[^.!?]*қайт\w*[^.!?]*", re.I)


def _clip(text: str, n: int) -> str:
    """Cut at a sentence end (or else a word boundary) instead of mid-word: «…в которых входит ря»."""
    text = text.strip()
    if len(text) <= n:
        return text
    head = text[:n]
    end = max(head.rfind(". "), head.rfind("! "), head.rfind("? "))
    return head[:end + 1] if end >= n // 2 else head[:head.rfind(" ")].rstrip(",;:—- ") + "…"


def _description_publication(p: dict, lang: str) -> tuple[str | None, list[dict]]:
    """Publish source narrative only with its own matching article attribution."""
    from urllib.parse import unquote, urlsplit
    text = _clip(p.get("description") or "", 300) or None
    if not text:
        return None, []
    if p.get("description_kind") == "research":  # our own words from a cited source (pipeline.place_facts)
        return (p.get(f"description_{lang}") if lang in ("en", "kk") and p.get(f"description_{lang}") else text), []
    # records from our own pipeline (data/processed/pois.jsonl): facts rebuilt per language, Wikipedia with its article
    if not p.get("description_kind") and p.get("description_source") in ("template", "osm"):
        return (describe(p, lang) or "")[:400] or None, []
    if not p.get("description_kind") and p.get("description_source") == "wikipedia":
        url = p.get("description_url") or ""
        if not str(p.get("description_license", "")).startswith("CC BY-SA 4.0") or ".wikipedia.org/" not in url:
            return None, []
        notice = {"ru": "Сокращённый отрывок; исходный текст и авторы — в статье.",
                  "kk": "Қысқартылған үзінді; түпнұсқа мәтін мен авторлар мақалада көрсетілген.",
                  "en": "Shortened excerpt; see the article for the original text and authors."}
        return text, [{"source": "wikipedia", "title": str(p.get("description_title") or p["name"])[:300], "url": url,
                       "license": "CC-BY-SA-4.0", "license_url": "https://creativecommons.org/licenses/by-sa/4.0/",
                       "attribution": "Wikipedia contributors", "notice": notice.get(lang, notice["ru"])}]
    if p.get("description_kind") == "structured_template":
        return text, []
    if p.get("description_source") != "wikipedia" or p.get("description_license") != "CC-BY-SA-4.0":
        return None, []
    def article_key(url):
        if not isinstance(url, str):
            return None
        try:
            parsed = urlsplit(url)
            if (parsed.scheme != "https" or not parsed.hostname or not parsed.hostname.endswith(".wikipedia.org")
                    or parsed.username or parsed.password or not parsed.path.startswith("/wiki/") or len(parsed.path) <= 6):
                return None
            return parsed.hostname.casefold(), unquote(parsed.path).replace(" ", "_"), parsed.query
        except ValueError:
            return None
    details = p.get("description_attribution") or {}
    expected_url = p.get("description_url") or details.get("url")
    expected = article_key(expected_url)
    if expected_url and expected is None:
        return None, []
    refs = [ref for ref in p.get("source_refs", []) if ref.get("source") == "wikipedia"
            and ref.get("license") == "CC-BY-SA-4.0" and article_key(ref.get("url"))
            and (expected is None or article_key(ref["url"]) == expected)]
    if len({article_key(ref["url"]) for ref in refs}) != 1:
        return None, []
    ref = refs[0]
    title = details.get("title") or unquote(urlsplit(ref["url"]).path.removeprefix("/wiki/")).replace("_", " ")
    notices = {"ru": "Сокращённый отрывок; исходный текст и авторы — в статье.",
               "kk": "Қысқартылған үзінді; түпнұсқа мәтін мен авторлар мақалада көрсетілген.",
               "en": "Shortened excerpt; see the article for the original text and authors."}
    return text, [{"source": "wikipedia", "title": str(title)[:300], "url": ref["url"],
                   "license": "CC-BY-SA-4.0", "license_url": "https://creativecommons.org/licenses/by-sa/4.0/",
                   "attribution": details.get("attribution") or "Wikipedia contributors",
                   "notice": notices.get(lang, notices["ru"])}]


def _item(c: Cand, why: str, todo: str, visit: int, rank_i: int, plan: Plan, lang: str, out_mode: str,
          *, available_visit_min: int | None = None) -> dict | None:
    p = c.poi
    srcs = list(p.get("sources", []))
    url = p.get("source_url")  # exactly the dataset value (team contract), website is a separate field
    if c.event:
        srcs.append(c.event["source"])
    w = p.get("features", {}).get("wheelchair")
    lo, hi = c.visit_range
    free = min(plan.budget, plan.deadline_min - plan.deadline_buffer) if plan.deadline_min is not None else plan.budget
    room = free - c.travel_min - (c.return_min or 0)
    if available_visit_min is not None:
        room = available_visit_min  # a route's already-validated timeline owns this interval
    if room < 5:
        return None
    visit = int(max(5, min(visit, room)))
    vmin = [max(5, min(visit, lo)), max(visit, min(hi, max(room, visit)))]
    ost, oconf = _contract_open(c.opening)
    straight = int(round(float(hav_m(plan.origin[0], plan.origin[1], p["lat"], p["lon"]))))
    description, description_attribution = _description_publication(p, lang)
    details = accepted_details(p, plan.evidence_date or parse_now(None).date())
    return {
        # team contract §3.3
        "poi_id": p["id"], "name": display_name(p, lang),
        "category": CONTRACT_CATEGORY.get(p["category"], "other"), "lat": p["lat"], "lon": p["lon"],
        "distance_m": straight, "travel_min": max(1, c.travel_min), "why": why, "visit_min": vmin, "what_to_do": todo,
        "open_status": ost, "open_confidence": oconf, "source": "poi_data",
        "source_url": url if (url or "").startswith("http") else None, "rating": p.get("rating"),
        "website": p.get("website") if (p.get("website") or "").startswith("http") else None,
        # extensions
        "rank": rank_i, "match": round(c.match, 2) if c.match is not None else None,
        "category_detail": p["category"], "category_label": label(p["category"], lang),
        "icon": CATEGORIES[p["category"]].icon, "walk_distance_m": int(round(c.distance_m / 10) * 10),
        "travel_mode": out_mode, "visit_suggested_min": visit, "leave_by": c.leave_by, "return_min": c.return_min or 0,
        "opening": {**{k: c.opening.get(k) for k in ("status", "confidence", "label", "raw", "next_change")},
                    "source": p.get("hours_source"), "source_url": p.get("hours_source_url"), "check_date": p.get("check_date")},
        "source_label": t("src_poi", lang), "data_sources": srcs, "popularity": p.get("popularity"),
        "features": feature_labels(p.get("features", {}), lang),
        "accessibility": w if w in ("yes", "limited", "no") else "unknown", "badges": _badges(c, plan),
        "event": ({k: c.event[k] for k in ("title", "starts_at", "url", "source", "price_from")} if c.event else None),
        "address": p.get("address"), "description": description,
        "structured_facts": details["facts"], "menu_items": details["menu_items"], "prices": details["prices"],
        "description_source": p.get("description_source"), "description_attribution": description_attribution,
        "description_url": p.get("description_url"), "phone": p.get("phone"), "instagram": p.get("instagram"),
        "cuisine": cuisine_labels(p.get("cuisine"), lang) or None,
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

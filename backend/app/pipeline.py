"""Оркестрация /api/recommend — 8 шагов из team/01_backend.md."""
import logging
import re
import time
import uuid
from datetime import datetime

from . import cache, llm, tracing
from . import rag_adapter as rag
from .config import ASTANA_BBOX, ASTANA_TZ
from .generate import llm_generate, template_generate
from .guards import looks_like_injection, mask_pii
from .intent import Intent, parse_intent
from .routing import MAX_RADIUS, build_route, search_radius_m, travel_min
from .schemas import RecommendRequest, RecommendResponse

log = logging.getLogger("backend.pipeline")

MAX_CANDIDATES = 8

TEXTS = {
    "ru": {
        "disclaimer": "Рекомендации основаны на открытых данных о местах (POI). Приблизительная локация используется только для этого запроса и не сохраняется.",
        "no_location": "Не удалось определить, где вы. Включите геолокацию или напишите ориентир, например «я возле Байтерека».",
        "outside": "Координаты вне Астаны: искали по всему городу.",
        "injection": "Запрос похож на попытку изменить инструкции помощника, поэтому он не обработан. Опишите, куда хотите сходить.",
        "off_topic": "Я подсказываю, куда сходить в Астане. Опишите, где вы и что хотите: прогулка, кофе, музей, с ребёнком…",
        "nothing": "Рядом не нашлось подходящих мест. Попробуйте увеличить время или убрать часть ограничений.",
        "unknown_hours": "Часы работы {names} неизвестны: уточните перед визитом.",
        "closed": "Часть подходящих мест сейчас закрыта, поэтому они не показаны.",
        "widened": "Рядом вариантов мало, поэтому радиус поиска увеличен.",
    },
    "en": {
        "disclaimer": "Recommendations are based on open POI data. Your approximate location is used only for this request and is not stored.",
        "no_location": "Could not determine where you are. Enable geolocation or name a landmark, e.g. “near Bayterek”.",
        "outside": "Coordinates are outside Astana, so the whole city was searched.",
        "injection": "The request looks like an attempt to change the assistant's instructions and was not processed.",
        "off_topic": "I suggest places to go in Astana. Tell me where you are and what you'd like to do.",
        "nothing": "No suitable places nearby. Try a larger time budget or fewer constraints.",
        "unknown_hours": "Opening hours for {names} are unknown: check before you go.",
        "closed": "Some matching places are closed right now and were hidden.",
        "widened": "Few options nearby, so the search radius was widened.",
    },
}


def _t(lang: str, key: str, **kw) -> str:
    return TEXTS["en" if lang == "en" else "ru"][key].format(**kw)


def _in_astana(lat: float, lon: float) -> bool:
    s, w, n, e = ASTANA_BBOX
    return s <= lat <= n and w <= lon <= e


def _filters_label(intent: Intent) -> list[str]:
    out = list(intent.categories)
    out += [k for k, v in intent.constraints.model_dump().items() if v]
    if intent.group_size:
        out.append(f"group:{intent.group_size}")
    return out


def _search(query: str, lat, lon, radius: int, categories: list[str]) -> list[dict]:
    """Сначала по категориям; если мало — добираем без фильтра категорий (поиск по смыслу сам отранжирует)."""
    hits = rag.search(query, lat, lon, radius_m=radius, categories=categories or None, top_k=15)
    if categories and len(hits) < 4:
        seen = {h["id"] for h in hits}
        extra = rag.search(query, lat, lon, radius_m=radius, categories=None, top_k=15)
        hits += [{**h, "score": h.get("score", 0) * 0.7} for h in extra if h["id"] not in seen]
    return hits


def _filter_candidates(hits: list[dict], intent: Intent, now: datetime) -> tuple[list[dict], bool]:
    """Жёсткие правила кодом: часы, дети, доступность. -> (кандидаты, были ли закрытые)."""
    out, had_closed = [], False
    c = intent.constraints
    for h in hits:
        status, conf = rag.open_status(h.get("opening_hours"), now)
        if status == "closed":
            had_closed = True
            continue
        if c.accessibility and h.get("wheelchair") == "no":
            continue
        if c.kids and h.get("kid_friendly") is False:
            continue
        h = {**h, "open_status": status, "open_confidence": conf, "travel_min": travel_min(h.get("distance_m"), intent.mode)}
        bonus = 0.0
        if c.kids and h.get("kid_friendly"):
            bonus += 0.5
        if c.night and status == "open":
            bonus += 0.5
        if status == "open":
            bonus += 0.1
        h["rank"] = h.get("score", 0) + bonus
        out.append(h)
    out.sort(key=lambda x: x["rank"], reverse=True)
    return out[:MAX_CANDIDATES], had_closed


def recommend(req: RecommendRequest) -> RecommendResponse:
    """Вход API: кэш → пайплайн → учёт токенов/стоимости → трейс."""
    resp, _ = recommend_with_stats(req)
    return resp


def recommend_with_stats(req: RecommendRequest, use_cache: bool = True,
                         photo_landmark: dict | None = None) -> tuple[RecommendResponse, dict]:
    """photo_landmark — место, распознанное по фото ({"lat","lon","label"}); заменяет GPS/ориентир из текста."""
    t0 = time.perf_counter()
    request_id = uuid.uuid4().hex[:12]
    now = (req.now or datetime.now(ASTANA_TZ))
    now = now.replace(tzinfo=ASTANA_TZ) if now.tzinfo is None else now.astimezone(ASTANA_TZ)
    query = mask_pii(req.query)

    loc = (req.location.lat, req.location.lon) if req.location else None
    key = cache.make_key(query, loc, now, {
        "t": req.time_budget_min, "m": req.mode, "l": req.lang,
        "p": req.profile.model_dump() if req.profile else None,
        "models": llm.models(), "override": llm.current_override(),
        "photo": photo_landmark["label"] if photo_landmark else None,
    })
    if use_cache and (hit := cache.responses.get(key)):
        resp = RecommendResponse.model_validate({**hit, "request_id": request_id})
        stats = {"cache": "hit", "latency_ms": int((time.perf_counter() - t0) * 1000), **llm.summarize([])}
        log.info("request_id=%s cache=hit recs=%d", request_id, len(resp.recommendations))
        return resp, stats

    with llm.usage_scope() as calls, tracing.span(
        "recommend", input={"query": query, "time_budget_min": req.time_budget_min, "mode": req.mode,
                            "has_location": loc is not None},
    ) as root:
        resp = _recommend(req, request_id, now, query, photo_landmark)
        usage = llm.summarize(calls)
        root.update(output={"recommendations": [r.name for r in resp.recommendations], "notes": resp.notes},
                    metadata={"request_id": request_id, **usage})
    stats = {"cache": "miss", "latency_ms": int((time.perf_counter() - t0) * 1000), **usage,
             "calls": llm.usage_dicts(calls)}
    if use_cache and resp.recommendations:
        cache.responses.set(key, resp.model_dump(mode="json"))
    log.info("request_id=%s recs=%d llm_calls=%d tokens=%d/%d cost_usd=%s latency_ms=%d", request_id,
             len(resp.recommendations), usage["llm_calls"], usage["input_tokens"], usage["output_tokens"],
             usage["cost_usd"], stats["latency_ms"])
    return resp, stats


def _recommend(req: RecommendRequest, request_id: str, now: datetime, query: str,
               photo_landmark: dict | None = None) -> RecommendResponse:
    notes: list[str] = []

    # 1. вход: injection (PII уже замаскирован)
    lang_guess = req.lang or "ru"
    if looks_like_injection(query):
        with tracing.span("injection-guard", as_type="guardrail", input={"query": query}) as g:
            g.update(output={"blocked": True})
        return _empty(request_id, req, now, lang_guess, _t(lang_guess, "injection"))

    # 2. разбор запроса
    intent, used_llm = parse_intent(req, query)
    lang = intent.lang
    if intent.off_topic and not intent.categories:
        return _empty(request_id, req, now, lang, _t(lang, "off_topic"), intent)

    # 3. локация: GPS (округлённый) → ориентир → нет
    lat = lon = None
    loc_source, loc_label = "none", None
    if photo_landmark:
        lat, lon = photo_landmark["lat"], photo_landmark["lon"]
        loc_source, loc_label = "landmark", f"~ {photo_landmark['label']} (по фото)"
    elif req.location:
        rlat, rlon = round(req.location.lat, 3), round(req.location.lon, 3)
        if _in_astana(rlat, rlon):
            lat, lon, loc_source, loc_label = rlat, rlon, "gps_rounded", "~ ваша локация (±100 м)"
        else:
            notes.append(_t(lang, "outside"))
    if lat is None:
        lm = rag.resolve_landmark(intent.landmark) if intent.landmark else None
        lm = lm or rag.resolve_landmark(query)
        if lm:
            lat, lon, loc_source, loc_label = lm["lat"], lm["lon"], "landmark", f"~ {lm['label']}"
    if lat is None and not notes:
        return _empty(request_id, req, now, lang, _t(lang, "no_location"), intent)

    # 4–5. радиус + поиск
    radius = search_radius_m(intent.time_budget_min, intent.mode)
    search_q = intent.search_query or query
    with tracing.span("poi-search", as_type="retriever",
                      input={"query": search_q, "radius_m": radius, "categories": intent.categories}) as r:
        hits = _search(search_q, lat, lon, radius, intent.categories)
        if len(hits) < 2 and lat is not None and radius < MAX_RADIUS:  # одно расширение радиуса
            radius = min(MAX_RADIUS, radius * 2)
            hits = _search(search_q, lat, lon, radius, intent.categories)
            if hits:
                notes.append(_t(lang, "widened"))
        r.update(output=[{"id": h["id"], "name": h["name"], "distance_m": h.get("distance_m"),
                          "score": h.get("score")} for h in hits])

    # 6. фильтры кодом; сам ориентир («я возле Mega Silk Way») не советуем
    if loc_source == "landmark":
        hits = [h for h in hits if (h.get("distance_m") or 0) > 60]
    candidates, had_closed = _filter_candidates(hits, intent, now)
    if had_closed:
        notes.append(_t(lang, "closed"))
    if not candidates:
        return _empty(request_id, req, now, lang, _t(lang, "nothing"), intent, radius, loc_source, loc_label, notes)

    # 7. генерация
    generated = llm_generate(query, intent, candidates, loc_label)
    if generated:
        picks, llm_notes = generated
        notes += llm_notes
    else:
        picks = template_generate(intent, candidates)

    # 8. факты подставляет код
    by_id = {c["id"]: c for c in candidates}
    recs = []
    for p in picks:
        c = by_id[p["poi_id"]]
        recs.append({
            **p,
            "name": c["name"], "category": c["category"], "lat": c["lat"], "lon": c["lon"],
            "distance_m": c.get("distance_m"), "travel_min": c.get("travel_min"),
            "open_status": c["open_status"], "open_confidence": c["open_confidence"],
            "source_url": c.get("source_url"), "rating": c.get("rating"),
        })
    unknown = [r["name"] for r in recs if r["open_status"] == "unknown"]
    if unknown:
        notes.append(_t(lang, "unknown_hours", names=", ".join(f"«{n}»" for n in unknown)))

    route = build_route((lat, lon) if lat is not None else None, recs, intent.time_budget_min, intent.mode)

    log.debug("request_id=%s candidates=%d intent_llm=%s", request_id, len(candidates), used_llm)
    return RecommendResponse(
        request_id=request_id,
        used_context=_ctx(intent, now, radius, loc_source, loc_label),
        recommendations=recs,
        route=route,
        notes=list(dict.fromkeys(notes)),
        disclaimer=_t(lang, "disclaimer"),
    )


def _ctx(intent: Intent | None, now: datetime, radius, loc_source, loc_label, req: RecommendRequest | None = None) -> dict:
    return {
        "location_source": loc_source,
        "location_label": loc_label,
        "radius_m": radius,
        "time_budget_min": intent.time_budget_min if intent else (req.time_budget_min or 60),
        "mode": intent.mode if intent else (req.mode or "walk"),
        "filters": _filters_label(intent) if intent else [],
        "now": now,
    }


def _empty(request_id, req, now, lang, note, intent=None, radius=None, loc_source="none", loc_label=None, notes=None):
    log.info("request_id=%s recs=0 reason=%s", request_id, note[:40])
    return RecommendResponse(
        request_id=request_id,
        used_context=_ctx(intent, now, radius, loc_source, loc_label, req),
        recommendations=[],
        route=None,
        notes=list(dict.fromkeys([*(notes or []), note])),
        disclaimer=_t(lang, "disclaimer"),
    )


def photo_not_recognized(req: RecommendRequest, seen: str) -> RecommendResponse:
    lang = req.lang or "ru"
    now = (req.now or datetime.now(ASTANA_TZ)).astimezone(ASTANA_TZ)
    seen = re.sub(r"^на фото[:,]?\s*", "", seen.strip(), flags=re.IGNORECASE).rstrip(".")
    seen_part = f" На фото: {seen[:1].lower() + seen[1:]}." if seen and lang != "en" else ""
    note = ("Could not recognise the place in the photo. Please name a landmark or enable geolocation." if lang == "en"
            else f"Не удалось узнать место по фото.{seen_part} Напишите ориентир или включите геолокацию.")
    return _empty(uuid.uuid4().hex[:12], req, now, lang, note)

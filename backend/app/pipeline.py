"""Оркестрация /api/recommend — 8 шагов из team/01_backend.md."""
import logging
import re
import time
import uuid
from datetime import datetime, timedelta

from . import cache, llm, tracing
from . import rag_adapter as rag
from .config import ASTANA_BBOX, ASTANA_TZ, get_settings
from .generate import _lang as gen_lang, llm_generate, template_generate, template_texts
from .guards import drop_unverified_open_claims, looks_like_injection, mask_pii
from .intent import Intent, parse_intent
from .routing import MAX_RADIUS, build_route, default_visit, search_radius_m, travel_min, visit_open_status
from .schemas import QUERY_MAX_CHARS, RecommendRequest, RecommendResponse

log = logging.getLogger("backend.pipeline")

MAX_CANDIDATES = 8
MIN_VISIT_MIN = 10  # если на месте остаётся меньше 10 минут — место не советуем

TEXTS = {
    "ru": {
        "disclaimer": "Рекомендации основаны на открытых данных о местах (POI). Приблизительная локация используется только для этого запроса и не сохраняется.",
        "no_location": "Не удалось определить, где вы. Включите геолокацию или напишите ориентир, например «я возле Байтерека».",
        "outside": "Эти координаты вне Астаны, а помощник знает места только в Астане. Напишите ориентир в городе.",
        "clarify": "Напишите, что хочется: например, «прогулка на час», «кофе рядом» или «куда сходить с ребёнком».",
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
        "outside": "These coordinates are outside Astana, and the assistant only knows places in Astana. Name a landmark in the city.",
        "clarify": "Tell me what you'd like: e.g. “a one-hour walk”, “coffee nearby” or “something for kids”.",
        "injection": "The request looks like an attempt to change the assistant's instructions and was not processed.",
        "off_topic": "I suggest places to go in Astana. Tell me where you are and what you'd like to do.",
        "nothing": "No suitable places nearby. Try a larger time budget or fewer constraints.",
        "unknown_hours": "Opening hours for {names} are unknown: check before you go.",
        "closed": "Some matching places are closed right now and were hidden.",
        "widened": "Few options nearby, so the search radius was widened.",
    },
    "kk": {
        "disclaimer": "Ұсыныстар орындар туралы ашық деректерге (POI) негізделген. Шамамен алынған орналасқан жеріңіз тек осы сұрау үшін қолданылады және сақталмайды.",
        "no_location": "Қай жерде екеніңізді анықтай алмадық. Геолокацияны қосыңыз немесе бағдар жазыңыз, мысалы «Бәйтерек маңындамын».",
        "outside": "Бұл координаттар Астанадан тыс, ал көмекші тек Астанадағы орындарды біледі. Қаладағы бағдарды жазыңыз.",
        "clarify": "Не қалайтыныңызды жазыңыз: мысалы, «бір сағаттық серуен», «жақын жерде кофе» немесе «баламен қайда бару».",
        "injection": "Сұрау көмекшінің нұсқауларын өзгертуге тырысуға ұқсайды, сондықтан өңделмеді. Қайда барғыңыз келетінін жазыңыз.",
        "off_topic": "Мен Астанада қайда баруға болатынын ұсынамын. Қай жерде екеніңізді және не қалайтыныңызды жазыңыз.",
        "nothing": "Жақын жерде қолайлы орын табылмады. Уақытты көбейтіп немесе шектеулерді азайтып көріңіз.",
        "unknown_hours": "{names} жұмыс уақыты белгісіз: бармас бұрын тексеріңіз.",
        "closed": "Қолайлы орындардың бір бөлігі қазір жабық, сондықтан көрсетілмеді.",
        "widened": "Жақын жерде нұсқалар аз, сондықтан іздеу радиусы үлкейтілді.",
    },
}


def _t(lang: str, key: str, **kw) -> str:
    return TEXTS.get(lang, TEXTS["ru"])[key].format(**kw)


def _in_astana(lat: float, lon: float) -> bool:
    s, w, n, e = ASTANA_BBOX
    return s <= lat <= n and w <= lon <= e


def _filters_label(intent: Intent) -> list[str]:
    out = list(intent.categories)
    out += [k for k, v in intent.constraints.model_dump().items() if v]
    if intent.group_size:
        out.append(f"group:{intent.group_size}")
    return out


def _search(query: str, lat, lon, radius: int, categories: list[str], raw_query: str | None = None) -> list[dict]:
    """Multi-query retrieval + RRF.

    1) переписанный LLM запрос с фильтром категорий (точность по смыслу);
    2) если мало — он же без категорий;
    3) исходная фраза пользователя без категорий: LLM при переписывании может выкинуть название места
       («торговый центр Хан Шатыр» → «торговый центр»), а исходник его сохраняет.
       В retrieval-eval это подняло NDCG@5 по запросам-названиям (см. experiments/README.md).
    """
    lists = [rag.search(query, lat, lon, radius_m=radius, categories=categories or None, top_k=15)]
    if categories and len(lists[0]) < 4:
        lists.append(rag.search(query, lat, lon, radius_m=radius, categories=None, top_k=15))
    if raw_query and raw_query.strip().casefold() != query.strip().casefold():
        lists.append(rag.search(raw_query, lat, lon, radius_m=radius, categories=None, top_k=15))
    if len(lists) == 1:
        return lists[0]
    fused: dict[str, float] = {}
    by_id: dict[str, dict] = {}
    for weight, hits in zip([1.0, 0.7, 1.0], lists):
        for rank, h in enumerate(hits, 1):
            fused[h["id"]] = fused.get(h["id"], 0.0) + weight / (60 + rank)
            by_id.setdefault(h["id"], h)
    ordered = sorted(fused, key=lambda i: -fused[i])[:15]
    return [{**by_id[i], "score": round(fused[i] * 60, 4)} for i in ordered]


def _filter_candidates(hits: list[dict], intent: Intent, now: datetime) -> tuple[list[dict], bool]:
    """Жёсткие правила кодом: часы, дети, доступность. -> (кандидаты, были ли закрытые)."""
    out, had_closed = [], False
    c = intent.constraints
    for h in hits:
        tmin = travel_min(h.get("distance_m"), intent.mode)
        available = intent.time_budget_min - (tmin or 0)
        if available < MIN_VISIT_MIN:
            continue
        minimum = min(default_visit(h["category"], intent.time_budget_min)[0], available)
        arrival = now + timedelta(minutes=tmin or 0)
        status, conf = visit_open_status(h.get("opening_hours"), arrival, minimum)
        if status == "open":
            try:
                checked = datetime.fromisoformat(str(h.get("check_date") or "")[:10]).date()
                age = (now.date() - checked).days
                recent_evidence = (h.get("hours_source") and h.get("hours_source_url")
                                   and 0 <= age <= getattr(get_settings(), "hours_max_age_days", 180))
            except ValueError:
                recent_evidence = False
            if not recent_evidence:
                conf = "low"
        if status == "closed":
            had_closed = True
            continue
        if c.accessibility and h.get("wheelchair") == "no":
            continue
        if c.kids and h.get("kid_friendly") is False:
            continue
        tmin = travel_min(h.get("distance_m"), intent.mode)
        available = intent.time_budget_min - (tmin or 0)
        if available < MIN_VISIT_MIN:  # дорога съедает почти весь бюджет — не предлагаем
            continue
        h = {**h, "open_status": status, "open_confidence": conf, "travel_min": tmin, "max_visit_min": available}
        h["arrival"] = arrival
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
    query = mask_pii(req.query)[:QUERY_MAX_CHARS]

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

    # 1. вход: пустой запрос → просим уточнить; injection (PII уже замаскирован)
    lang_guess = req.lang or "ru"
    if not query.strip():
        return _empty(request_id, req, now, lang_guess, _t(lang_guess, "clarify"))
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
        lm = lm or rag.resolve_landmark(query, allow_network=False)  # фразу пользователя наружу не шлём
        if lm:
            lat, lon, loc_source, loc_label = lm["lat"], lm["lon"], "landmark", f"~ {lm['label']}"
    if lat is None:  # вне Астаны или локации нет — не ищем «по всему городу» без расстояний
        return _empty(request_id, req, now, lang, notes[0] if notes else _t(lang, "no_location"), intent)

    # 4–5. радиус + поиск
    radius = search_radius_m(intent.time_budget_min, intent.mode)
    search_q = intent.search_query or query
    with tracing.span("poi-search", as_type="retriever",
                      input={"query": search_q, "radius_m": radius, "categories": intent.categories}) as r:
        hits = _search(search_q, lat, lon, radius, intent.categories, raw_query=query)
        if len(hits) < 2 and lat is not None and radius < MAX_RADIUS:  # одно расширение радиуса
            radius = min(MAX_RADIUS, radius * 2)
            hits = _search(search_q, lat, lon, radius, intent.categories, raw_query=query)
            if hits:
                notes.append(_t(lang, "widened"))
        r.update(output=[{"id": h["id"], "name": h["name"], "distance_m": h.get("distance_m"),
                          "score": h.get("score")} for h in hits])

    # 6. фильтры кодом; сам ориентир («я возле Mega Silk Way») не советуем
    stem = (loc_label or "").removeprefix("~ ").split(" (")[0].casefold()[:6] if loc_source == "landmark" else ""
    if loc_source == "landmark":
        hits = [h for h in hits if (h.get("distance_m") or 0) > 60
                and not (stem and (h.get("distance_m") or 0) < 400 and h["name"].casefold().startswith(stem))]
    candidates, had_closed = _filter_candidates(hits, intent, now)
    # нужного типа мест рядом нет («прогулка», а вокруг только кафе) — один раз расширяем радиус,
    # чем подменять запрос неподходящими местами; бюджет времени всё равно проверит _filter_candidates
    wanted = set(intent.categories)
    if wanted and not any(c["category"] in wanted for c in candidates) and radius < MAX_RADIUS:
        radius = min(MAX_RADIUS, radius * 2)
        wider = _search(search_q, lat, lon, radius, intent.categories, raw_query=query)
        if loc_source == "landmark":
            wider = [h for h in wider if (h.get("distance_m") or 0) > 60
                     and not (stem and (h.get("distance_m") or 0) < 400 and h["name"].casefold().startswith(stem))]
        wider_c, wider_closed = _filter_candidates(wider, intent, now)
        if any(c["category"] in wanted for c in wider_c):
            candidates, had_closed = wider_c, had_closed or wider_closed
            notes.append(_t(lang, "widened"))
    if had_closed:
        notes.append(_t(lang, "closed"))
    if not candidates:
        return _empty(request_id, req, now, lang, _t(lang, "nothing"), intent, radius, loc_source, loc_label, notes)

    # 7. генерация
    generated = llm_generate(query, intent, candidates, loc_label)
    if generated is not None:
        picks, llm_notes = generated
        notes += llm_notes
        if not picks:
            return _empty(request_id, req, now, lang, _t(lang, "nothing"), intent, radius, loc_source, loc_label, notes)
    else:
        picks = template_generate(intent, candidates)

    # 8. факты подставляет код
    by_id = {c["id"]: c for c in candidates}
    recs = []
    for p in picks:
        c = by_id[p["poi_id"]]
        p = dict(p)
        avail = c["max_visit_min"]  # визит + дорога должны влезать в бюджет пользователя
        lo, hi = p["visit_min"]
        lo = max(5, min(lo, avail))
        p["visit_min"] = [lo, max(lo, min(hi, avail))]
        if visit_open_status(c.get("opening_hours"), c["arrival"], p["visit_min"][1])[0] == "closed":
            # Model duration cannot extend a validated visit beyond closing.
            minimum = min(default_visit(c["category"], intent.time_budget_min)[0], avail)
            p["visit_min"] = [minimum, minimum]
        if c["open_status"] != "open":  # модель не может «подтвердить» часы, которых нет в данных
            p["why"] = drop_unverified_open_claims(p["why"])
            p["what_to_do"] = drop_unverified_open_claims(p["what_to_do"])
            if not p["why"] or not p["what_to_do"]:
                t_why, t_what, _ = template_texts(c, gen_lang(intent))
                p["why"], p["what_to_do"] = p["why"] or t_why, p["what_to_do"] or t_what
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

    route_recs = [{**r, "opening_hours": by_id[r["poi_id"]].get("opening_hours")} for r in recs]
    route = build_route((lat, lon) if lat is not None else None, route_recs, intent.time_budget_min, intent.mode, now=now)
    if route:
        # A routed card advertises the duration actually counted by the route.
        order = route["order"]
        recs = sorted((r for r in recs if r["poi_id"] in order), key=lambda r: order.index(r["poi_id"]))
        for r in recs:
            r["visit_min"] = [r["visit_min"][0]] * 2

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

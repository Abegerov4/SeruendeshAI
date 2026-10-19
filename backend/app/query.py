"""Query understanding: fast rules + LLM structured parse (run in parallel), merged with UI filters.

The rules pass always runs (~1 ms) and is the fallback when the LLM is slow/unavailable.
UI filters that the user explicitly set win over anything parsed from text.
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field
from rapidfuzz import fuzz

from app.categories import CATEGORIES
from app.food import FoodRequirement, food_requirement_is_asserted, parse_food_requirements, needs_meal_kitchen
from app.textnorm import KK_LETTERS, fold

CatKey = Literal[tuple(CATEGORIES)]  # type: ignore[valid-type]
Need = Literal["wifi", "power_outlets", "quiet", "outdoor_seating", "wheelchair", "kids", "indoor", "free",
               "view", "open_late", "warm"]


class LLMParsed(BaseModel):
    """Strict schema for the parse call (all fields required; null = not mentioned)."""
    lang: Literal["ru", "kk", "en"]
    categories: list[CatKey] = Field(description="Place types the user wants; empty if not specific")
    avoid_categories: list[CatKey]
    needs: list[Need]
    time_budget_min: int | None = Field(description="Total free time in minutes (e.g. '30–60 мин' -> 60, 'час' -> 60)")
    travel_mode: Literal["walk", "car"] | None
    party: Literal["solo", "couple", "family_kids", "friends_group", "business"] | None
    group_size: int | None
    tourist: bool | None
    landmark_text: str | None = Field(description="Place the user says they are near, verbatim (e.g. 'Mega Silk Way')")
    deadline_kind: Literal["flight", "airport_arrival", "train", "meeting"] | None
    deadline_in_min: int | None = Field(description="Minutes until the user must leave/depart, if stated")
    deadline_clock: str | None = Field(description="HH:MM of the deadline if a clock time is stated")
    wants_route: bool | None
    night: bool
    surprise: bool = Field(description="User wants something unusual / hidden gem")
    search_text_ru: str = Field(description="The request rewritten as a short Russian search phrase")
    keywords_ru: list[str] = Field(description="3-8 Russian keywords describing desired places/activities")
    off_topic: bool = Field(False, description="True only if the request is clearly NOT about going somewhere in the city")
    food_requirements: list[FoodRequirement] = Field(default_factory=list, description=(
        "Explicit dishes/drinks (menu), budget (price), cuisine/meal format (style), diet/ingredients (diet). "
        "text must be a verbatim span of the user's positive requirement. Exclude negated or optional wishes "
        "and generic eat/coffee/cafe requests. These are user requirements, never facts about a venue."))


PARSE_SYSTEM = """You convert a city-walk request (Astana, Kazakhstan; Russian, Kazakh or English) into JSON.
Rules:
- Extract only what the user said or clearly implied; use null/empty when not mentioned. Do not invent places.
- categories: place types that would satisfy the request, from the allowed keys only (they are used as soft preferences).
  Map: coffee/кофе -> cafe; kids playground -> playground; interactive museum -> museum, kids_indoor; a walk/прогулка -> park, garden, landmark, viewpoint, museum; nightlife -> bar, nightclub, karaoke, cinema; warm/indoor -> mall, museum, cafe; unusual -> arts_centre, gallery, viewpoint, active, karaoke.
- needs: power outlet/розетка -> power_outlets; Wi-Fi -> wifi; quiet/тихо/тыныш -> quiet; stroller/wheelchair/коляска/арба -> wheelchair; with a child -> kids; warm/тепло -> warm.
- food_requirements: preserve named dishes, price limits, home-style/canteen/cuisine and dietary requirements separately from categories. Use verbatim spans only; generic coffee/eat/cafe has no such requirement. A negated or explicitly optional wish is not mandatory.
- time_budget_min: "30–60 минут" -> 60; "пару часов" -> 120; "полчаса" -> 30; "1-2 сағат" -> 120.
- "2 hours before my flight" -> deadline_kind=flight, deadline_in_min=120, time_budget_min=null.
- "be at the airport in 2 hours" -> deadline_kind=airport_arrival, deadline_in_min=120. An airport mention without explicit arrival means flight departure.
- landmark_text: ONLY the place where the user is right now ("я у X", "возле X", "X-тың жанында", "I'm at X"), copied as written.
  A place the user wants to go to ("хочу в X", "как попасть в X", "X-қа барғым келеді") is NOT landmark_text: keep it in search_text_ru.
- night=true for late-evening/night requests ("ночью", "түнде", "late night", "последние пару часов" at night).
- search_text_ru and keywords_ru: always in Russian, even for Kazakh/English input.
- lang: language of the user's text (kk if it contains Kazakh words/letters).
- off_topic=true ONLY when the text is clearly not about going out in the city: e.g. "напиши код", "реши уравнение",
  "кто президент США", "translate this essay". Anything about places, food, coffee, walks, rest, kids, events, a landmark,
  free time or "куда сходить" is NOT off-topic. When in doubt -> false."""


# clear "not about going somewhere" requests (template mode; the LLM parse has its own off_topic flag)
_OFF_TOPIC = re.compile(
    r"(напиши|написать|пиши|сгенерируй|write|generate)\w*\s+(?:(?:мне|me|a|an|some|the)\s+){0,2}"
    r"(код|программ|скрипт|функци|алгоритм|сочинени|эссе|реферат|стих|code|program|script|function|essay|poem)"
    r"|\b(python|javascript|java|c\+\+|sql|html|css)\b.*\b(код|code|функци|function|скрипт|script)"
    r"|(реши|решить|решите|посчитай|вычисли|solve|calculate)\w*\s+(\S+\s+)?(уравнени|задач|пример|интеграл|equation|problem|integral)"
    r"|\d\s*[\^*/+]\s*\d.*=|\bx\s*[\^²]|уравнени|интеграл|производн|теорем|equation|integral|derivative"
    r"|кто\s+(такой\s+|такая\s+|сейчас\s+)?(президент|премьер|канцлер|царь|король)|who\s+is\s+(the\s+)?(president|prime\s+minister|king)"
    r"|президент\w*\s+(сша|америк|росси|франц|кита)|(код|есеп|теңдеу)\w*\s+(жаз|шығар|шеш)|президенті\s+кім"
    r"|переведи\s+(текст|на\s+английский)|translate\s+(this|the)\s+text",
    re.IGNORECASE)


def is_off_topic(text: str, place_signal: bool = False) -> bool:
    """Rules: an off-topic pattern and nothing about places / walks / landmarks in the text."""
    return bool(text and not place_signal and _OFF_TOPIC.search(text))


@dataclass
class Parsed:
    lang: str = "ru"
    categories: list[str] = field(default_factory=list)
    avoid: list[str] = field(default_factory=list)
    needs: set[str] = field(default_factory=set)
    time_budget_min: int | None = None
    travel_mode: str | None = None
    party: str | None = None
    group_size: int | None = None
    tourist: bool = False
    landmark_text: str | None = None
    deadline_kind: str | None = None
    deadline_in_min: int | None = None
    deadline_clock: str | None = None
    flight_type: str = "unknown"
    wants_route: bool | None = None
    night: bool = False
    surprise: bool = False
    stroller: bool = False  # a baby stroller: kids and a flat walk, not a wheelchair profile
    walk_intent: bool = False
    wants_event: bool = False
    soft_categories: list[str] = field(default_factory=list)  # LLM-inferred preferences (boost, not filter)
    search_text: str = ""
    keywords: list[str] = field(default_factory=list)
    source: str = "rules"
    food_requirements: list[FoodRequirement] = field(default_factory=list)
    meal_intent: bool = False


def detect_lang(text: str) -> str:
    s = (text or "").lower()
    if any(c in KK_LETTERS for c in s) or re.search(r"\b(мен|маған|қай|жерде|барып|бала|балам|сағат|жанында)\b", s):
        return "kk"
    lat = len(re.findall(r"[a-z]", s))
    cyr = len(re.findall(r"[а-яё]", s))
    if lat > cyr:
        return "en"
    return "ru"


_NUM_WORDS = {"один": 1, "одна": 1, "два": 2, "две": 2, "пару": 2, "пара": 2, "три": 3, "полтора": 1.5, "one": 1,
              "two": 2, "couple": 2, "three": 3, "бір": 1, "екі": 2, "үш": 3}
_RULES: list[tuple[str, dict]] = [
    (r"кофе|кофейн|coffee|капучин|латте|кофехана", {"cat": ["cafe"]}),
    (r"розетк|socket|outlet|заряд|ноутбук|laptop|ноутбук|поработать|work from", {"need": ["power_outlets"], "cat": ["cafe", "coworking", "library"]}),
    (r"wi-?fi|вайфай|интернет", {"need": ["wifi"]}),
    (r"тих|спокойн|quiet|calm|тыныш", {"need": ["quiet"]}),
    (r"\bребен|\bребён|\bдет[еиcкя]|\bдетьми|\bмалыш|\bсын(\b|ом|ишк)|\bдоч|\bбала(\b|м|мен|лар|ға)|\bkids?\b|\bchild|toddler|\bfamily|\bсемь[еяйю]", {"need": ["kids"], "party": "family_kids"}),
    (r"(?<!смотров\w\w )площадк|playground|ойын алаң|качел", {"cat": ["playground"]}),
    (r"интерактив|interactive|науч|science", {"cat": ["museum", "kids_indoor"]}),
    (r"музе|museum|мұражай", {"cat": ["museum"]}),
    (r"галере|gallery|выставк|exhibition|көрме", {"cat": ["gallery", "museum", "arts_centre"]}),
    (r"парк|сквер|park|саябақ|набережн|embankment", {"cat": ["park", "garden"]}),
    (r"прогул|погулят|гулять|пройтис|walk|stroll|серуен", {"walk": True}),
    (r"турист|впервые|first time|tourist|приезж|в городе проездом|туристпін|посмотреть город|достопримечат|sightseeing|what to see|see the city|көрікті жер", {"tourist": True}),
    (r"вылет|рейс|flight|самол|ұшақ|ұшу|аэропорт|airport|әуежай", {"deadline": "flight"}),
    (r"поезд|train|пойыз", {"deadline": "train"}),
    (r"ноч|поздн|night|late|түн", {"night": True}),
    (r"необычн|unusual|hidden|секрет|ерекше|удиви|сюрприз|surprise|необычное", {"surprise": True}),
    (r"поесть|пообед|поужин|ресторан|lunch|dinner|restaurant|тамақ|мейрамхана|покушать", {"cat": ["restaurant", "cafe"]}),
    (r"\bбар\b|выпить(?!\s+(кофе|чай|чаю|какао|смузи|сок))|коктейл|пиво|beer|cocktail|\bpub\b|\bbar\b", {"cat": ["bar"]}),
    (r"\bкафе\b|кафешк|\bcafe\b|кафеге|кафеде", {"cat": ["cafe"]}),
    (r"развлеч|развлекат|entertain|have fun|\bfun\b|көңіл көтер|ойын-сауық|повеселит", {"cat": ["cinema", "karaoke", "active", "theme_park", "kids_indoor"]}),
    (r"клуб|club|тусов|dance|танц", {"cat": ["nightclub"]}),
    (r"караоке|karaoke", {"cat": ["karaoke"]}),
    (r"кальян|hookah", {"cat": ["hookah"]}),
    (r"тепл|трц|торгов|mall|warm|жылы|сауда орталы", {"cat": ["mall"], "need": ["warm"]}),
    (r"вид на|панорам|смотров|view|панорама|көрініс|с высоты|высот\w* птичьего|на высоте|from above|skyline|биіктен", {"cat": ["viewpoint", "landmark"], "need": ["view"]}),
    (r"с коляской|детск\w* коляск|коляск\w* с (?:ребен|малыш)|stroller|pram|pushchair|бала арба", {"need": ["kids"], "party": "family_kids", "walk": True, "stroller": True}),
    (r"инвалид|wheelchair|пандус|без ступен|step-free|(?<!с )коляск|(?<!бала )арба", {"need": ["wheelchair"]}),
    (r"бесплатн|без денег|денег нет|нет денег|for free|free (?:entry|admission|of charge)|no money|тегін|ақшасыз", {"need": ["free"]}),
    (r"собак|\bпс[аео]м?\b|\bdogs?\b|итпен|итім", {"cat": ["park", "garden"], "walk": True}),
    (r"истори|стар\w* город|old town|history|historic|тарих|ескі қала", {"cat": ["museum", "monument", "landmark", "worship", "gallery"]}),
    (r"родител|пожил|пенсионер|бабушк|дедушк|за [6-8]0\b|elderly|seniors?\b|my parents|ата-ана|қарт", {"cat": ["museum", "landmark", "theatre", "park", "garden", "worship", "gallery", "cafe", "viewpoint"]}),
    (r"романти|свидани|\bdate\b|romantic|ғашық", {"cat": ["landmark", "viewpoint", "park", "garden", "restaurant", "cafe", "theatre"]}),
    (r"на машин|на авто|by car|көлікпен|такси|taxi|driving", {"mode": "car"}),
    (r"пешком|on foot|жаяу", {"mode": "walk"}),
    (r"мечет|храм|собор|mosque|cathedral|мешіт", {"cat": ["worship"]}),
    (r"кино|cinema|movie|фильм", {"cat": ["cinema"]}),
    (r"театр|опер|балет|theatre|theater|opera|ballet|концерт|concert", {"cat": ["theatre"]}),
    (r"библиотек|library|кітапхана|почитать", {"cat": ["library"], "need": ["quiet"]}),
    (r"коворк|coworking", {"cat": ["coworking"], "need": ["power_outlets", "wifi"]}),
    (r"сувенир|souvenir|кәдесый|подар", {"cat": ["souvenir", "market"]}),
    (r"рынок|базар|bazaar|market", {"cat": ["market"]}),
    (r"бан[яи]|сауна|spa|спа|монша", {"cat": ["spa"]}),
    (r"активн|подвижн|спортив|\bactive\b|sporty", {"cat": ["active", "park"]}),
    (r"коньк|каток|катани\w* на льду|ice[ -]?skat|ice rink|мұз айдын|конькимен", {"cat": ["active"], "kw": ["каток"]}),
    (r"боулинг|bowling|каток|ice rink|квест|escape|батут|trampoline|скалодр|climb", {"cat": ["active", "kids_indoor"]}),
    (r"океанариум|aquarium|зоопарк|zoo", {"cat": ["zoo_aquarium"]}),
    (r"аквапарк|water park", {"cat": ["water_park"]}),
    (r"аттракцион|amusement|колесо обозр", {"cat": ["theme_park"]}),
    (r"сладк|десерт|мороженое|dessert|ice cream|выпечк|кондитер", {"cat": ["sweets", "cafe"]}),
    (r"маршрут|route|по пути|несколько мест|прогулку из|бағыт", {"route": True}),
    (r"концерт|спектакл|шоу|афиш|событи|мероприят|\bevent|concert|\bshow\b|квиз|quiz|стендап|stand-?up|фестивал|festival|көрме|іс-шара|выставк", {"event": True}),
    (r"компани|друз|friends|group|достар|коллег", {"party": "friends_group"}),
]


_RULES = [(fold(p), a) for p, a in _RULES]


def _num(s: str) -> float | None:
    s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return _NUM_WORDS.get(s)


def parse_time_budget(text: str) -> int | None:
    s = fold(text)
    m = re.search(r"(\d+)\s*[-–—]\s*(\d+)\s*(мин|min|минут)", s)
    if m:
        return int(m.group(2))
    m = re.search(r"(\d+(?:[.,]\d+)?|один|одна|два|две|пару|пара|три|полтора|one|two|couple|three|бир|еки|уш)\s*[-–—]?\s*(?:(\d+)\s*)?(час|ч\b|сагат|hours?|hrs?\b|h\b)", s)
    if m:
        hi = _num(m.group(2)) if m.group(2) else _num(m.group(1).replace("бир", "бір").replace("еки", "екі").replace("уш", "үш"))
        if hi:
            tail = re.match(r"[а-я]*\s*(?:и\s+|and\s+)?(\d+)\s*(?:мин|min)", s[m.end():])
            return int(hi * 60) + (int(tail[1]) if tail else 0)
    m = re.search(r"(\d+)\s*(мин|min|минут)", s)
    if m:
        return int(m.group(1))
    if re.search(r"полчаса|жарты сагат|half an hour", s):
        return 30
    if re.search(r"\b(час|часик|an hour|one hour|сагат)\b", s):
        return 60
    return None


def _temporal_durations(text: str, clock_deadline: bool) -> tuple[int | None, int | None]:
    """Separate the duration attached to a departure from independent free time."""
    s = fold(text)
    number = r"(?:\d+(?:[.,]\d+)?|один|одна|два|две|пару|пара|три|полтора|one|two|couple|three|бир|еки|уш)"
    amount = number + r"(?:\s*[-–—]\s*" + number + r")?"
    minute = r"(?:мин[а-я]*|minutes?|mins?\b)"
    hour = r"(?:час[а-я]*|ч\b|сагат[а-я]*|hours?|hrs?\b|h\b)"
    pattern = (r"(?<!\w)(?:полчаса|жарты сагат|half an hour|" + amount + r"\s*" + hour
               + r"(?:\s*(?:и\s+|and\s+)?\d+\s*" + minute + r")?|" + amount + r"\s*" + minute
               + r"|an hour|часик|час|сагат)(?!\w)")
    spans = [(m, parse_time_budget(m.group())) for m in re.finditer(pattern, s)]
    spans = [(m, value) for m, value in spans if value is not None]
    anchor = r"вылет\w*|рейс\w*|flight|самол\w*|ушак\w*|ушу\w*|аэропорт\w*|airport|ауежай\w*|поезд\w*|train|пойыз\w*|встреч\w*|meeting"
    anchors = list(re.finditer(anchor, s))
    selected = None
    # An explicit relative deadline after the named departure takes precedence
    # over an earlier free-time phrase that happens to say "before flight".
    for i, (span, _) in enumerate(spans):
        if (re.search(r"\b(?:через|in)\s*$", s[:span.start()])
                and re.search(anchor, s[:span.start()])) or (
                re.match(r"\s*(?:кейин|калды)", s[span.end():]) and re.search(anchor, s[:span.start()])):
            selected = i
            break
    if selected is None:
        for i, (span, _) in enumerate(spans):
            if re.match(r"\s*(?:до|перед|before|until)\s+(?:my\s+|domestic\s+|international\s+|моего\s+|внутренн\w*\s+|международн\w*\s+)*(?:" + anchor + r")", s[span.end():]):
                selected = i
                break
    if selected is None and spans and not clock_deadline:
        # Preserve single-duration requests such as "2 hours before my flight";
        # with several unmarked durations use the one closest to the deadline.
        selected = min(range(len(spans)), key=lambda i: min(
            (max(a.start() - spans[i][0].end(), spans[i][0].start() - a.end(), 0) for a in anchors), default=0))
    deadline = spans[selected][1] if selected is not None else None
    free = [value for i, (_, value) in enumerate(spans) if i != selected]
    return (min(free) if free else None), deadline


def parse_clock(text: str) -> str | None:
    m = re.search(r"\b([01]?\d|2[0-3])[:.]([0-5]\d)\b", text or "")
    return f"{int(m.group(1)):02d}:{m.group(2)}" if m else None


_NEG_BEFORE = re.compile(r"(?:\bне|\bбез|\bкроме|\bno|\bnot|\bwithout|\bexcept|\bavoid)\s+(?:[\w-]+\s+){0,3}$")
_NEG_AFTER = re.compile(r"^\w*\s+(?:емес|керек емес)\b")


def _negated(s: str, m: re.Match) -> bool:
    before = s[max(0, m.start() - 40):m.start()]
    if re.search(r"не\s+только\s+(?:[\w-]+\s+){0,2}$|not\s+only\s+(?:[\w-]+\s+){0,2}$", before):
        return False
    return bool(_NEG_BEFORE.search(before) or _NEG_AFTER.search(s[m.start():m.start() + 40]))


def parse_rules(text: str) -> Parsed:
    s = fold(text)
    p = Parsed(lang=detect_lang(text), search_text=text.strip(), food_requirements=parse_food_requirements(text))
    p.meal_intent = needs_meal_kitchen(text, p.food_requirements)
    cats: list[str] = []
    avoid: list[str] = []
    for pat, act in _RULES:
        hits = list(re.finditer(pat, s))
        if not hits:
            continue
        if all(_negated(s, m) for m in hits):
            avoid += act.get("cat", [])  # «только не кофейня», «не торговый центр», «без кафе»
            continue
        if p.lang == "kk" and act.get("cat") == ["bar"] and not re.search(r"\bpub\b|\bbar\b|пиво|сыра|коктейл", s):
            continue  # Kazakh "бар" = "there is", not a bar
        cats += act.get("cat", [])
        p.needs.update(act.get("need", []))
        if "party" in act:
            p.party = act["party"]
        if act.get("walk"):
            p.walk_intent = True
        if act.get("tourist"):
            p.tourist = True
        if act.get("deadline"):
            p.deadline_kind = act["deadline"]
        if act.get("night"):
            p.night = True
        if act.get("surprise"):
            p.surprise = True
        if act.get("mode"):
            p.travel_mode = act["mode"]
        if act.get("route"):
            p.wants_route = True
        if act.get("event"):
            p.wants_event = True
        if act.get("stroller"):
            p.stroller = True
        p.keywords += [k for k in act.get("kw", []) if k not in p.keywords]
    p.categories = list(dict.fromkeys(cats))
    p.avoid = [c for c in dict.fromkeys(avoid) if c not in p.categories]
    if (p.food_requirements or p.meal_intent) and not p.categories:
        p.categories = ["restaurant","cafe"]
    if p.deadline_kind == "flight":
        # Naming an airport is ambiguous; default to departure unless arrival is explicit.
        if re.search(r"be (?:at|in) (?:the )?airport|arriv\w* (?:at )?(?:the )?airport|быть в аэропорт|прибы\w* в аэропорт|к аэропорт|ауежайда.*(?:болу|болам)|ауежайга.*(?:жету|келу)", s):
            p.deadline_kind = "airport_arrival"
        if re.search(r"international|международ|халыкаралык", s):
            p.flight_type = "international"
        elif re.search(r"domestic|внутренн|ишки", s):
            p.flight_type = "domestic"
    p.deadline_clock = parse_clock(text) if p.deadline_kind else None
    if p.deadline_kind:
        p.time_budget_min, p.deadline_in_min = _temporal_durations(text, p.deadline_clock is not None)
    else:
        p.time_budget_min = parse_time_budget(text)
    m = re.search(r"\b(нас|we are|біз)\s*(\d+)", s)
    if m:
        p.group_size = int(m.group(2))
    return p


def merge_llm(rules: Parsed, llm: LLMParsed | None) -> Parsed:
    if llm is None:
        return rules
    p = Parsed(source="llm+rules", lang=llm.lang or rules.lang)
    p.food_requirements = list(rules.food_requirements)
    seen = {(r.kind, fold(r.text)) for r in p.food_requirements}
    for requirement in llm.food_requirements:
        key = (requirement.kind, fold(requirement.text))
        if key not in seen and food_requirement_is_asserted(rules.search_text, requirement.text):
            p.food_requirements.append(requirement)
            seen.add(key)
    p.meal_intent = rules.meal_intent or needs_meal_kitchen("", p.food_requirements)
    # explicit place types named in the text (rules) filter; LLM-inferred types only boost ranking
    p.categories = list(rules.categories)
    p.soft_categories = list(dict.fromkeys([c for c in llm.categories if c in CATEGORIES] + rules.categories))
    p.avoid = [c for c in dict.fromkeys([*llm.avoid_categories, *rules.avoid]) if c in CATEGORIES and c not in p.categories]
    p.needs = set(llm.needs) | rules.needs
    p.time_budget_min = rules.time_budget_min if rules.time_budget_min is not None else llm.time_budget_min
    p.travel_mode = llm.travel_mode or rules.travel_mode
    p.party = llm.party or rules.party
    p.group_size = llm.group_size or rules.group_size
    p.tourist = bool(llm.tourist) or rules.tourist
    p.landmark_text = llm.landmark_text or rules.landmark_text
    p.deadline_kind = rules.deadline_kind or llm.deadline_kind
    p.flight_type = rules.flight_type
    p.deadline_in_min = rules.deadline_in_min if rules.deadline_in_min is not None else llm.deadline_in_min
    p.deadline_clock = rules.deadline_clock or llm.deadline_clock
    if p.deadline_kind and p.time_budget_min and p.deadline_in_min is None:
        p.deadline_in_min, p.time_budget_min = p.time_budget_min, None
    p.wants_route = llm.wants_route if llm.wants_route is not None else rules.wants_route
    p.night = llm.night or rules.night
    p.surprise = llm.surprise or rules.surprise
    p.stroller = rules.stroller
    if rules.stroller and "wheelchair" not in rules.needs:
        p.needs.discard("wheelchair")  # a model often reads «коляска» as a wheelchair
    p.walk_intent = rules.walk_intent or any(c in ("park", "garden") for c in llm.categories)
    p.wants_event = rules.wants_event
    p.search_text = llm.search_text_ru or rules.search_text
    p.keywords = llm.keywords_ru
    if "kids" in p.needs and not p.party:
        p.party = "family_kids"
    return p


def deadline_minutes(p: Parsed, now: dt.datetime) -> int | None:
    if p.deadline_clock:
        hh, mm = map(int, p.deadline_clock.split(":"))
        target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if target < now:
            target += dt.timedelta(days=1)
        return int((target - now).total_seconds() // 60)
    return p.deadline_in_min


# --- landmark resolution -------------------------------------------------------------------

_GENERIC = {"парк", "сквер", "кафе", "музей", "бар", "ресторан", "театр", "кофейня", "мечеть", "библиотека", "park",
            "cafe", "museum", "детская площадка", "площадка", "рынок", "базар", "сад", "центр", "дом", "тц", "трц",
            # common words that are also names of hotels/clinics in the team anchors ("Я турист" is not hotel "Турист")
            "турист", "tourist", "университет", "university", "ночлег", "капитал", "capital", "отель", "hotel",
            "хостел", "hostel", "гостиница", "больница", "поликлиника", "hospital", "акимат", "министерство"}
# origin-only anchors (hotels, universities, clinics, offices) count as the start only with an explicit cue
ANCHOR_KINDS = {"hotel", "university", "hospital", "government"}


# where the user IS vs where they want TO GO (texts are folded: Kazakh letters -> Russian ones)
_ORIGIN_BEFORE = re.compile(r"(?:\bя\s+)?(?:\bу|возле|около|рядом\s+с|рядом|недалеко\s+от|напротив|в\s+районе|\bнахожусь\s+(?:у|в|возле)|"
                            r"\bживу\s+в|\bостановил\w*\s+в|\bя\s+в|\bв\s+(?:отеле|гостинице|хостеле)|staying\s+(?:at|in)|"
                            r"\bnear|\bat|\bby|i'?m\s+(?:at|near|by|in)|i\s+am\s+(?:at|near|by|in))\s*$")
_ORIGIN_AFTER = re.compile(r"^\w*\s*(?:жанында|манында|касында|алдында)|^(?:да|де|та|те)\b")
_DEST_BEFORE = re.compile(r"(?:маршрут|путь|дорог\w*|проложи|построй|веди|проведи\w*)\s+(?:\w+\s+)?(?:до|к|в|на)\s*$|"
                          r"(?:route|directions|way|navigate|take\s+me)\s+to\s*(?:the\s*)?$|how\s+(?:do\s+i\s+|to\s+)?get\s+to\s*(?:the\s*)?$|"
                          r"(?:хочу|хотим|хотел\w*|надо|нужно)\s+(?:в|на|до|к|попасть\s+(?:в|на|к))\s*$|(?:попасть|пойти|сходить|дойти|добраться|"
                          r"доехать|пройти|проехать|едем|иду|идти)\s+(?:в|на|до|к)\s*$|как\s+(?:пройти|дойти|доехать|попасть|добраться)\s+(?:в|на|до|к)?\s*$|"
                          r"(?:подня\w*|залезть|взобраться|забраться|побывать|посетить|посмотреть)\s+(?:в|на|до|к)?\s*$|"
                          r"(?:go|get|walk|drive|head)\s+to\s*(?:the\s*)?$|\b(?:visit|climb|go\s+up)\s*(?:the\s*)?$")
# inside a route request: «с/от/из X до/к/в/на Y», «from X to Y», «X-тен Y-ге»
_TO_BEFORE = re.compile(r"(?:\bдо|\bк|\bко|\bв|\bво|\bна|\bto|\binto)\s*$")
_FROM_BEFORE = re.compile(r"(?:\bс|\bсо|\bот|\bиз|\bfrom)\s*$")
_FROM_AFTER = re.compile(r"^(?:нан|нен|дан|ден|тан|тен)\b")
_DEST_AFTER = re.compile(r"^(?:га|ге|ка|ке)\b|^\w*\s*(?:баргым|баруга|барамын|бару)")


# "маршрут до ботсада", "как дойти до Байтерека", "route to Khan Shatyr": the user wants directions to one place
# the user's own home as the start: «от дома», «рядом с домом», «у меня дома», «near my home», «үйдің жанында»
HOME_CUE = re.compile(r"(?:\bот|\bиз|\bу|\bоколо|\bвозле|\bрядом\s+с|\bнедалеко\s+от|\bнедалеко\s+от)\s+(?:моего\s+|своего\s+|нашего\s+)?"
                      r"дом(?:а|ом)\b|\bу\s+меня\s+дома\b|\b(?:near|from|around|close\s+to)\s+(?:my\s+|our\s+)?home\b|"
                      r"\bуйден\b|\bуйимнен\b|\bуйдин\s+жанында|\bуйимнин\s+жанында")
NAV_INTENT = re.compile(r"маршрут|\bпуть\b|\bдорог[уаи]\b|проложи|построй|\bвед[иь]\b|проведи|как\s+(?:мне\s+)?(?:пройти|дойти|доехать|попасть|добраться)|"
                        r"\broute\b|directions|how\s+(?:do\s+i\s+|to\s+)?get\s+to|navigate|take\s+me\s+to|багыт|калай\s+бар")


KIND_BONUS = {"landmark": 50, "airport": 40, "station": 30, "hotel": 12, "university": 10, "hospital": 8,
              "government": 8, "stadium": 8, "place": 5, "poi": 0}


def _ambiguous_spans(text: str, gazetteer: list[dict]) -> list[tuple[int, int]]:
    names = {k for g in gazetteer for k in g.get("ambiguous_keys", []) if len(k) >= 4}
    return [(m.start(), m.end()) for k in names if k in text
            for m in re.finditer(r"(?<!\w)" + re.escape(k) + r"(?!\w)", text)]


def _name_spans(text: str, key: str, curated: bool, blocked: list[tuple[int, int]]):
    if key not in text:
        return
    # Preserve local grammatical endings (e.g. «в Хилтоне») while English
    # names such as Coffee must not match a different place called Coffeeshop.
    inflected = curated or re.search(r"[а-яёәіңғүұқөһ]", key)
    suffix = r"\w{0,4}(?!\w)" if inflected else r"(?!\w)"
    for match in re.finditer(r"(?<!\w)" + re.escape(key) + suffix, text):
        a, b = match.span()
        if curated or not any(x <= a and b <= y for x, y in blocked):
            yield a, b


def landmark_mentions(text: str, gazetteer: list[dict]) -> list[dict]:
    """All gazetteer names mentioned in the text with their role: origin / dest / unknown."""
    s = " " + fold(text) + " "
    blocked = _ambiguous_spans(s, gazetteer)
    route_cue = bool(NAV_INTENT.search(s))
    cands = []
    for g in gazetteer:
        for k in g["keys"]:
            if len(k) < 4 or k in _GENERIC:
                continue
            if g["kind"] != "landmark" and len(k) < 6:
                continue
            score = len(k) + KIND_BONUS.get(g["kind"], 0)
            cands.extend((score, a, b, g) for a, b in _name_spans(s, k, g["kind"] == "landmark", blocked))
    cands.sort(key=lambda c: -c[0])
    taken: list[tuple[int, int]] = []
    out = []
    for score, a, b, g in cands:
        if any(a < y and x < b for x, y in taken):
            continue  # overlaps a better mention of the same words
        taken.append((a, b))
        before, after = s[max(0, a - 32):a], s[b:b + 24]
        if route_cue and (_TO_BEFORE.search(before) or _DEST_AFTER.search(after)):
            role = "dest"  # «маршрут с AITU до ботсада»: the place after «до» is where to go
        elif route_cue and (_FROM_BEFORE.search(before) or _FROM_AFTER.search(after)):
            role = "origin"  # …and the place after «с / от» is the start
        else:
            role = ("dest" if _DEST_BEFORE.search(before) or _DEST_AFTER.search(after)
                    else "origin" if _ORIGIN_BEFORE.search(before) or _ORIGIN_AFTER.search(after) else "unknown")
        out.append({"entry": g, "role": role, "pos": a})
    return sorted(out, key=lambda m: m["pos"])


def split_mentions(text: str, gazetteer: list[dict]) -> tuple[dict | None, list[dict]]:
    """(origin gazetteer entry or None, destination entries)."""
    ms = landmark_mentions(text, gazetteer)
    dests = [m["entry"] for m in ms if m["role"] == "dest"]
    origin = next((m["entry"] for m in ms if m["role"] == "origin"), None)
    if origin is None:
        origin = next((m["entry"] for m in ms if m["role"] == "unknown" and m["entry"]["kind"] not in ANCHOR_KINDS), None)
    return origin, dests


def find_landmark_in_text(text: str, gazetteer: list[dict]) -> dict | None:
    """Exact (folded) mention of a gazetteer name inside the query, preferring curated landmarks."""
    s = " " + fold(text) + " "
    blocked = _ambiguous_spans(s, gazetteer)
    best = None
    for g in gazetteer:
        for k in g["keys"]:
            if len(k) < 4 or k in _GENERIC:
                continue
            if g["kind"] != "landmark" and len(k) < 6:
                continue
            if next(_name_spans(s, k, g["kind"] == "landmark", blocked), None) is None:
                continue
            score = len(k) + KIND_BONUS.get(g["kind"], 0)
            if best is None or score > best[0]:
                best = (score, g)
    return best[1] if best else None


def resolve_landmark(name: str, gazetteer: list[dict]) -> dict | None:
    """Resolve a landmark key or free-text name (from UI or LLM) against the gazetteer."""
    if not name:
        return None
    for g in gazetteer:
        if g.get("landmark_key") == name or g.get("poi_id") == name:  # landmark key or a POI id (photo mode, MCP)
            return g
    hit = find_landmark_in_text(name, gazetteer)
    if hit:
        return hit
    q = fold(name)
    if _ambiguous_spans(q, gazetteer):
        return None  # Ask for a branch/address instead of fuzzy-matching a chain.
    best = None
    for g in gazetteer:
        for k in g["keys"]:
            if len(k) < 4:
                continue
            sc = fuzz.WRatio(q, k)
            if g["kind"] == "landmark":
                sc += 5
            if sc >= 88 and (best is None or sc > best[0]):
                best = (sc, g)
    return best[1] if best else None

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
    deadline_kind: Literal["flight", "train", "meeting"] | None
    deadline_in_min: int | None = Field(description="Minutes until the user must leave/depart, if stated")
    deadline_clock: str | None = Field(description="HH:MM of the deadline if a clock time is stated")
    wants_route: bool | None
    night: bool
    surprise: bool = Field(description="User wants something unusual / hidden gem")
    search_text_ru: str = Field(description="The request rewritten as a short Russian search phrase")
    keywords_ru: list[str] = Field(description="3-8 Russian keywords describing desired places/activities")


PARSE_SYSTEM = """You convert a city-walk request (Astana, Kazakhstan; Russian, Kazakh or English) into JSON.
Rules:
- Extract only what the user said or clearly implied; use null/empty when not mentioned. Do not invent places.
- categories: place types that would satisfy the request, from the allowed keys only (they are used as soft preferences).
  Map: coffee/кофе -> cafe; kids playground -> playground; interactive museum -> museum, kids_indoor; a walk/прогулка -> park, garden, landmark, viewpoint, museum; nightlife -> bar, nightclub, karaoke, cinema; warm/indoor -> mall, museum, cafe; unusual -> arts_centre, gallery, viewpoint, active, karaoke.
- needs: power outlet/розетка -> power_outlets; Wi-Fi -> wifi; quiet/тихо/тыныш -> quiet; stroller/wheelchair/коляска/арба -> wheelchair; with a child -> kids; warm/тепло -> warm.
- time_budget_min: "30–60 минут" -> 60; "пару часов" -> 120; "полчаса" -> 30; "1-2 сағат" -> 120.
- "2 hours before my flight" -> deadline_kind=flight, deadline_in_min=120, time_budget_min=null.
- landmark_text: copy the landmark/mall/street name exactly as written (keep original language).
- night=true for late-evening/night requests ("ночью", "түнде", "late night", "последние пару часов" at night).
- search_text_ru and keywords_ru: always in Russian, even for Kazakh/English input.
- lang: language of the user's text (kk if it contains Kazakh words/letters)."""


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
    wants_route: bool | None = None
    night: bool = False
    surprise: bool = False
    walk_intent: bool = False
    wants_event: bool = False
    soft_categories: list[str] = field(default_factory=list)  # LLM-inferred preferences (boost, not filter)
    search_text: str = ""
    keywords: list[str] = field(default_factory=list)
    source: str = "rules"


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
    (r"площадк|playground|ойын алаң|качел", {"cat": ["playground"]}),
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
    (r"вид на|панорам|смотров|view|панорама|көрініс", {"cat": ["viewpoint", "landmark"], "need": ["view"]}),
    (r"коляск|инвалид|wheelchair|пандус|арба|без ступен|step-free", {"need": ["wheelchair"]}),
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
    (r"боулинг|bowling|каток|ice rink|квест|escape|батут|trampoline|скалодр|climb", {"cat": ["active", "kids_indoor"]}),
    (r"океанариум|aquarium|зоопарк|zoo", {"cat": ["zoo_aquarium"]}),
    (r"аквапарк|water park", {"cat": ["water_park"]}),
    (r"аттракцион|amusement|колесо обозр", {"cat": ["theme_park"]}),
    (r"сладк|десерт|мороженое|dessert|ice cream|выпечк|кондитер", {"cat": ["sweets", "cafe"]}),
    (r"маршрут|route|по пути|несколько мест|прогулку из|бағыт", {"route": True}),
    (r"концерт|спектакл|шоу|афиш|событи|мероприят|\bevent|concert|\bshow\b|квиз|quiz|стендап|stand-?up|фестивал|festival|көрме|іс-шара|выставк", {"event": True}),
    (r"компани|друз|friends|group|достар|коллег", {"party": "friends_group"}),
]


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
            return int(hi * 60)
    m = re.search(r"(\d+)\s*(мин|min|минут)", s)
    if m:
        return int(m.group(1))
    if re.search(r"полчаса|жарты сагат|half an hour", s):
        return 30
    if re.search(r"\b(час|часик|an hour|one hour|сагат)\b", s):
        return 60
    return None


def parse_clock(text: str) -> str | None:
    m = re.search(r"\b([01]?\d|2[0-3])[:.]([0-5]\d)\b", text or "")
    return f"{int(m.group(1)):02d}:{m.group(2)}" if m else None


def parse_rules(text: str) -> Parsed:
    s = fold(text)
    p = Parsed(lang=detect_lang(text), search_text=text.strip())
    cats: list[str] = []
    for pat, act in _RULES:
        if not re.search(pat, s):
            continue
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
    p.categories = list(dict.fromkeys(cats))
    budget = parse_time_budget(text)
    if p.deadline_kind and budget:
        p.deadline_in_min, p.time_budget_min = budget, None
    else:
        p.time_budget_min = budget
    p.deadline_clock = parse_clock(text) if p.deadline_kind else None
    m = re.search(r"\b(нас|we are|біз)\s*(\d+)", s)
    if m:
        p.group_size = int(m.group(2))
    return p


def merge_llm(rules: Parsed, llm: LLMParsed | None) -> Parsed:
    if llm is None:
        return rules
    p = Parsed(source="llm+rules", lang=llm.lang or rules.lang)
    # explicit place types named in the text (rules) filter; LLM-inferred types only boost ranking
    p.categories = list(rules.categories)
    p.soft_categories = list(dict.fromkeys([c for c in llm.categories if c in CATEGORIES] + rules.categories))
    p.avoid = [c for c in llm.avoid_categories if c in CATEGORIES]
    p.needs = set(llm.needs) | rules.needs
    p.time_budget_min = llm.time_budget_min if llm.time_budget_min else rules.time_budget_min
    p.travel_mode = llm.travel_mode or rules.travel_mode
    p.party = llm.party or rules.party
    p.group_size = llm.group_size or rules.group_size
    p.tourist = bool(llm.tourist) or rules.tourist
    p.landmark_text = llm.landmark_text or rules.landmark_text
    p.deadline_kind = llm.deadline_kind or rules.deadline_kind
    p.deadline_in_min = llm.deadline_in_min or rules.deadline_in_min
    p.deadline_clock = llm.deadline_clock or rules.deadline_clock
    if p.deadline_kind and p.time_budget_min and p.deadline_in_min is None:
        p.deadline_in_min, p.time_budget_min = p.time_budget_min, None
    p.wants_route = llm.wants_route if llm.wants_route is not None else rules.wants_route
    p.night = llm.night or rules.night
    p.surprise = llm.surprise or rules.surprise
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
            "cafe", "museum", "детская площадка", "площадка", "рынок", "базар", "сад", "центр", "дом", "тц", "трц"}


def find_landmark_in_text(text: str, gazetteer: list[dict]) -> dict | None:
    """Exact (folded) mention of a gazetteer name inside the query, preferring curated landmarks."""
    s = " " + fold(text) + " "
    best = None
    for g in gazetteer:
        for k in g["keys"]:
            if len(k) < 4 or k in _GENERIC:
                continue
            pos = s.find(k)
            if pos < 0:
                continue
            if g["kind"] != "landmark" and (not s[pos - 1].isspace() or len(k) < 6):
                continue
            score = len(k) + {"landmark": 50, "airport": 40, "station": 30, "place": 5, "poi": 0}.get(g["kind"], 0)
            if best is None or score > best[0]:
                best = (score, g)
    return best[1] if best else None


def resolve_landmark(name: str, gazetteer: list[dict]) -> dict | None:
    """Resolve a landmark key or free-text name (from UI or LLM) against the gazetteer."""
    if not name:
        return None
    for g in gazetteer:
        if g.get("landmark_key") == name:
            return g
    hit = find_landmark_in_text(name, gazetteer)
    if hit:
        return hit
    q = fold(name)
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

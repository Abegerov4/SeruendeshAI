"""Разбор запроса пользователя → структурированный Intent.

Правила работают всегда (и без ключа LLM); LLM, если доступна, уточняет результат.
Явные поля из запроса фронта перекрывают и то, и другое.
"""
import re
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError

from . import llm
from .schemas import RecommendRequest

PROMPT = (Path(__file__).parent / "prompts" / "intent.md").read_text(encoding="utf-8")

ALL_CATEGORIES = {
    "cafe", "restaurant", "bar", "nightlife", "museum", "gallery", "theatre", "cinema", "park", "viewpoint",
    "monument", "attraction", "playground", "mall", "library", "coworking", "sport",
}


class Constraints(BaseModel):
    quiet: bool = False
    socket: bool = False
    kids: bool = False
    night: bool = False
    accessibility: bool = False
    unusual: bool = False


class Intent(BaseModel):
    categories: list[str] = Field(default_factory=list)
    search_query: str = ""
    time_budget_min: int | None = None
    mode: str | None = None
    landmark: str | None = None
    constraints: Constraints = Field(default_factory=Constraints)
    group_size: int | None = None
    lang: str = "ru"
    off_topic: bool = False


# (регулярка по нижнему регистру) -> категории / флаги
KEYWORDS: list[tuple[str, list[str]]] = [
    (r"коф|кофе|кафе|coffee|cafe|кофейн|кофе", ["cafe"]),
    (r"розетк|ноутбук|поработ|wi-?fi|вайфай|socket|laptop", ["cafe", "coworking"]),
    (r"поест|пообед|поужин|ресторан|еда|restaurant|food|eat", ["restaurant", "cafe"]),
    (r"музе|museum|выставк|экспозиц", ["museum", "gallery"]),
    (r"галере|gallery|искусств|art\b", ["gallery", "museum"]),
    (r"парк|прогул|погулят|пройтис|walk|park|саябақ|серуен", ["park", "viewpoint", "attraction"]),
    (r"площадк|playground|детск|ойын алаң", ["playground", "park"]),
    (r"смотров|вид на|панорам|viewpoint|view", ["viewpoint"]),
    (r"достопримечат|посмотрет|sightseeing|landmark|что посмотреть|туристическ", ["attraction", "monument", "viewpoint", "museum"]),
    (r"кино|фильм|cinema|movie", ["cinema"]),
    (r"театр|опер|балет|theatre|theater|opera", ["theatre"]),
    (r"бар\b|бары|паб|клуб|bar\b|pub|club|вечеринк|party", ["bar", "nightlife"]),
    (r"торгов|шопинг|тц\b|трц|mall|shopping", ["mall"]),
    (r"библиотек|library", ["library"]),
    (r"коворкинг|coworking", ["coworking"]),
    (r"спорт|бассейн|каток|sport|gym", ["sport"]),
]
FLAGS = {
    "quiet": r"тих|спокойн|quiet|calm|тыныш",
    "socket": r"розетк|socket|зарядит",
    "kids": r"ребен|ребён|дет[иья]|детск|малыш|kid|child|бала",
    "night": r"ноч|поздн|night|late|түн",
    "accessibility": r"коляск|инвалид|ограниченн\w* подвижн|wheelchair|accessib|пандус",
    "unusual": r"необычн|нестандартн|unusual|unique|интересн\w* мест",
}
MODE_KW = [(r"пешком|пешк|on foot|walk", "walk"), (r"на машин|авто|такси|by car|car\b", "car"),
           (r"автобус|транспорт|метро|lrt|bus|transit", "transit")]


def _lang(text: str) -> str:
    if re.search(r"[әғқңөұүһі]", text.lower()):
        return "kk"
    latin = len(re.findall(r"[a-zA-Z]", text))
    cyr = len(re.findall(r"[а-яА-ЯёЁ]", text))
    return "en" if latin > cyr else "ru"


def _time_budget(low: str) -> int | None:
    if m := re.search(r"(\d+)\s*[–\-—]\s*(\d+)\s*(мин|min)", low):
        return int(m.group(2))
    if m := re.search(r"(\d+[.,]?\d*)\s*(час|ч\b|hour|h\b|сағат)", low):
        return int(float(m.group(1).replace(",", ".")) * 60)
    if m := re.search(r"(\d+)\s*[–\-—]\s*(\d+)\s*(час|hour|сағат)", low):
        return int(m.group(2)) * 60
    if m := re.search(r"(\d+)\s*(мин|min)", low):
        return int(m.group(1))
    if "полчаса" in low or "half an hour" in low:
        return 30
    if re.search(r"\bчас\b|an hour|one hour", low):
        return 60
    if "пару часов" in low or "couple of hours" in low:
        return 120
    return None


def rule_intent(query: str) -> Intent:
    low = query.lower()
    cats: list[str] = []
    for pattern, add in KEYWORDS:
        if re.search(pattern, low):
            cats += [c for c in add if c not in cats]
    flags = {k: bool(re.search(p, low)) for k, p in FLAGS.items()}
    if flags["kids"]:
        cats = [c for c in ["playground", "museum", "park"] if c not in cats] + cats
    if flags["night"] and not cats:
        cats = ["bar", "nightlife", "attraction", "viewpoint"]
    if flags["unusual"]:
        cats += [c for c in ["attraction", "gallery", "viewpoint"] if c not in cats]
    mode = next((m for p, m in MODE_KW if re.search(p, low)), None)
    group = None
    if m := re.search(r"(\d+)\s*(человек|чел\b|people|persons|адам)", low):
        group = int(m.group(1))
    landmark = "аэропорт" if re.search(r"вылет|аэропорт|airport|flight|әуежай|ұшуға", low) else None
    return Intent(
        categories=cats[:6],
        search_query=query,
        time_budget_min=_time_budget(low),
        mode=mode,
        landmark=landmark,
        constraints=Constraints(**flags),
        group_size=group,
        lang=_lang(query),
    )


def llm_intent(query: str) -> Intent | None:
    data = llm.chat_json(PROMPT, f"<user_query>\n{query}\n</user_query>", name="parse-intent",
                         validate_output=Intent.model_validate)
    if not data:
        return None
    try:
        intent = Intent.model_validate(data)
    except ValidationError:
        return None
    intent.categories = [c for c in intent.categories if c in ALL_CATEGORIES]
    if intent.mode not in {None, "walk", "car", "transit"}:
        intent.mode = None
    if intent.lang not in {"ru", "kk", "en"}:
        intent.lang = "ru"
    return intent


# смежные категории: LLM и данные могут по-разному назвать одно и то же
RELATED = {
    "bar": ["nightlife"], "nightlife": ["bar"], "museum": ["gallery"], "gallery": ["museum"],
    "cafe": ["coworking"], "coworking": ["cafe"], "viewpoint": ["attraction"], "monument": ["attraction"],
    "playground": ["park"], "restaurant": ["cafe"],
}


def expand_categories(cats: list[str]) -> list[str]:
    out = list(cats)
    for c in cats:
        out += [r for r in RELATED.get(c, []) if r not in out]
    return out


def parse_intent(req: RecommendRequest, masked_query: str) -> tuple[Intent, bool]:
    """-> (intent, used_llm)."""
    rules = rule_intent(masked_query)
    smart = llm_intent(masked_query)
    intent = rules
    if smart:
        intent = smart
        # правила подстраховывают то, что LLM могла упустить
        intent.categories = intent.categories or rules.categories
        intent.time_budget_min = intent.time_budget_min or rules.time_budget_min
        intent.landmark = intent.landmark or rules.landmark
        intent.search_query = intent.search_query or masked_query
        for k, v in rules.constraints.model_dump().items():
            if v:
                setattr(intent.constraints, k, True)
    # явные поля запроса важнее всего
    if req.time_budget_min:
        intent.time_budget_min = req.time_budget_min
    if req.mode:
        intent.mode = req.mode
    if req.lang:
        intent.lang = req.lang
    if req.profile:
        intent.constraints.kids |= req.profile.with_kids
        intent.constraints.accessibility |= req.profile.accessibility
        if req.profile.group_size > 1:
            intent.group_size = req.profile.group_size
        if req.profile.tourist and not intent.categories:
            intent.categories = ["attraction", "monument", "viewpoint", "museum"]
    intent.categories = expand_categories(intent.categories)
    intent.time_budget_min = intent.time_budget_min or 60
    intent.mode = intent.mode or "walk"
    return intent, smart is not None

"""Conservative lexical extraction of user food requirements, never POI facts.

The fallback recognizes common RU/KK/EN dish words, explicit cuisines/formats,
diet phrases, qualitative prices and amounts with a currency. It does not infer
menus, availability, prices, a threshold for "cheap", or unknown dishes. Clause
negation and a few recognizable food brands are guarded; this is not general
entity recognition or a full natural-language negation parser.
"""
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class FoodRequirement(BaseModel):
    """An explicit user wish, with the original input span retained for audit."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["menu", "price", "style", "diet"]
    text: str = Field(min_length=1, max_length=120)


_NUMBER = r"\d+(?:[ \u00a0]\d{3})*(?:[.,]\d{1,2})?"
_CURRENCY = r"(?:KZT|USD|EUR|тенге|теңге|тг|руб(?:лей|ля)?|₸|₽|\$|€)"
_PRICE_PREFIX = r"(?:(?:до|за|не\s+дороже|не\s+более|максимум|бюджет|under|below|up\s+to|less\s+than|budget(?:\s+of)?|for)\s+)?"
_RULES = [
    ("menu", r"(?:картофельн\w*\s+)?пюре|котлет\w*|борщ\w*|суп(?:а|ы|ом|чик)?|пельмен\w*|манты|мантов|лагман\w*|плов\w*|палау\w*|қуырдақ\w*|б[еә]шбарма[қк]\w*|кеспе\w*|ботқа\w*|суши|пицц\w*|бургер\w*|стейк\w*|лапш\w*|mashed\s+potatoes|cutlets?|borscht|soups?|dumplings?|ramen|pizza|sushi|burgers?|pasta|steaks?|noodles?|rice"),
    ("style", r"домашн\w*\s+(?:ед\w*|кухн\w*)|home[ -](?:style|cooked|made)(?:\s+(?:food|meals?))?|үй(?:дегі|дегідей)?\s+(?:тағам\w*|тамақ\w*|ас)|столов\w*|асхана\w*|canteens?|cafeterias?|(?:грузинск|русск|казахск|итальянск|китайск|корейск|турецк|индийск|японск|узбекск)\w*\s+(?:кухн\w*|ед\w*)|(?:Georgian|Russian|Kazakh|Italian|Chinese|Korean|Turkish|Indian|Japanese|Uzbek)\s+(?:food|cuisine)|(?:қазақ|орыс|өзбек|қытай|кәріс|түрік)\s+(?:асханасы|тағам\w*)"),
    ("diet", r"халал\w*|halal|вегетариан\w*|веган\w*|vegetarian|vegan|gluten[ -]free|lactose[ -]free|без\s+(?:мяса|глютена|лактозы)|етсіз|глютенсіз"),
    ("price", r"(?:очень\s+)?д[её]ш[её]в\w*|недорог\w*|бюджетн\w*|(?:very\s+)?cheap|inexpensive|affordable|арзан\w*"),
    ("price", _PRICE_PREFIX + rf"(?:{_NUMBER}\s*{_CURRENCY}|{_CURRENCY}\s*{_NUMBER})(?!\w)"),
]
_RULES = [(kind, re.compile(r"(?<!\w)(?:" + pattern + r")(?!\w)", re.I)) for kind, pattern in _RULES]
_CLAUSE_BREAK = re.compile(r"[,.;!?]|\b(?:но|однако|but|however|бірақ)\b|\b(?:и|and)\s+(?=(?:не\s+)?хочу|(?:(?:do\s+not|don't)\s+)?want)", re.I)
_NEGATIVE_BEFORE = re.compile(
    r"\b(?:не\s+(?:хочу|нужн\w*|надо|обязательно|важн\w*|ищу)|"
    r"not(?:\s+necessarily)?|(?:do\s+not|don['’]t)\s+(?:want|need)|"
    r"no\s+need(?:\s+for)?)\b", re.I,
)
_NEGATIVE_AFTER = re.compile(
    r"\b(?:не\s+(?:важн\w*|обязательно|нужн\w*|хочу)|"
    r"(?:is\s+)?not\s+(?:important|necessary|required)|"
    r"(?:does\s+not|doesn['’]t)\s+matter|"
    r"(?:міндетті|маңызды|керек)\s+емес|жегім\s+келмейді)\b", re.I,
)
_FOOD_BRAND = re.compile(r"\b(?:суши\s+в[её]сла|sushi\s+vesla|pizza\s+hut|dodo\s+pizza|додо\s+пицца)\b", re.I)
_FOOD_CONTEXT = re.compile(
    r"\b(?:поесть|покушать|пообед\w*|поужин\w*|перекус\w*|ед[ауой]|кофе|кофейн\w*|кафе|ресторан\w*|"
    r"eat|eating|food|meal|lunch|dinner|coffee|caf[eé]|restaurant|тамақ\w*|тағам\w*|кофехана\w*|мейрамхана\w*)\b", re.I)
_FORMAT_ORIGIN = re.compile(r"(?:возле|около|рядом\s+с[о]?|near|by|at)\s+(?:(?:a|an|the)\s+)?$", re.I)


def _dismissed(text: str, start: int, end: int) -> bool:
    boundaries = list(_CLAUSE_BREAK.finditer(text))
    clause_start = max((match.end() for match in boundaries if match.end() <= start), default=0)
    clause_end = min((match.start() for match in boundaries if match.start() >= end), default=len(text))
    return bool(_NEGATIVE_BEFORE.search(text[clause_start:start]) or _NEGATIVE_AFTER.search(text[end:clause_end]))


def _span_asserted(text: str, start: int, end: int) -> bool:
    value = text[start:end]
    return not (
        _dismissed(text, start, end)
        or _NEGATIVE_BEFORE.search(value)
        or _NEGATIVE_AFTER.search(value)
        or any(match.start() < end and start < match.end() for match in _FOOD_BRAND.finditer(text))
    )


def food_requirement_is_asserted(text: str, phrase: str) -> bool:
    """Validate a literal model span using the same conservative assertion guards.

    This permits an unseen dish without claiming the phrase is in the fallback
    lexicon. Case, spelling and word boundaries must match the user's input;
    an occurrence inside a brand, negated or optional wish does not qualify.
    """
    if not phrase or len(phrase) > 120 or phrase != phrase.strip():
        return False
    return any(
        _span_asserted(text, match.start(), match.end())
        for match in re.finditer(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", text)
    )


def parse_food_requirements(text: str) -> list[FoodRequirement]:
    """Return deduplicated, ordered, verbatim positive food wishes.

    Generic eating/coffee/walking words are deliberately absent. A number alone,
    a clock or a travel duration is not a price. A recognized brand mention is
    not a request for its food. Unrecognized language remains unclassified.
    """
    spans = sorted((match.start(), match.end(), kind) for kind, rule in _RULES for match in rule.finditer(text))
    found, seen = [], set()
    for start, end, kind in spans:
        value = text[start:end]
        key = (kind, value.casefold())
        if key in seen or len(value) > 120 or not _span_asserted(text, start, end):
            continue
        if kind == "style" and _FORMAT_ORIGIN.search(text[:start]):
            continue
        seen.add(key)
        found.append(FoodRequirement(kind=kind, text=value))
    # A price mentioned for a museum, taxi or cinema is not a food requirement.
    food_context = any(_span_asserted(text, m.start(), m.end()) for m in _FOOD_CONTEXT.finditer(text))
    if not food_context and not any(r.kind != "price" for r in found):
        found = [r for r in found if r.kind != "price"]
    return found


def is_food_refinement(text: str) -> bool:
    """Only short, closed-vocabulary follow-ups inherit prior meal restrictions."""
    return bool(re.fullmatch(
        r"\s*(?:(?:а|и|ещ[её]|давай|пожалуйста|тогда|можно|покажи|найди|вариант\w*|мест\w*|"
        r"поближе|ближе|подешевле|дешевле|друг\w*|к|у|возле|рядом|с|без\s+кофе|в\s+помещении|"
        r"and|please|show|me|another|option[s]?|closer|cheaper|indoors|no\s+coffee|"
        r"жақынырақ|арзанырақ|басқа|нұсқа\w*)[\s,.!?]*)+", text, re.I))

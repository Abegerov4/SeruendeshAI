"""Conservative identity evidence; geographic distance remains the caller's guard.

Address transliteration compares complete street names, never house numbers
alone. POI names use only complete names and explicitly supplied aliases.
"""

from __future__ import annotations

import re
import unicodedata


_CYRILLIC = str.maketrans({
    "а": "a", "ә": "a", "б": "b", "в": "v", "г": "g", "ғ": "g",
    "д": "d", "е": "e", "ё": "e", "ж": "zh", "з": "z", "и": "i",
    "й": "i", "к": "k", "қ": "q", "л": "l", "м": "m", "н": "n",
    "ң": "ng", "о": "o", "ө": "o", "п": "p", "р": "r", "с": "s",
    "т": "t", "у": "u", "ұ": "u", "ү": "u", "ф": "f", "х": "kh",
    "һ": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch",
    "ъ": "", "ы": "i", "і": "i", "ь": "", "э": "e", "ю": "iu", "я": "ia",
})

# Values encode street types; they are kept separately from the street name.
_STREET_TYPES = {
    "avenue": ("avenue", "ave", "av", "prospekt", "prosp", "pr-t", "pr", "danggili", "dangili", "dang"),
    "street": ("street", "st", "ulitsa", "ul", "koshe", "koshesi", "kosh"),
    "boulevard": ("boulevard", "blvd", "bulvar", "bul"),
    "lane": ("lane", "ln", "pereulok", "per"),
    "highway": ("highway", "hwy", "shosse"),
    "square": ("square", "sq", "ploshchad", "pl"),
    "embankment": ("embankment", "naberezhnaia", "nab"),
}
_SUBADDRESS = {
    "unit": ("unit", "suite", "apartment", "apt", "office", "ofis", "of", "kvartira", "kv", "pomeshchenie", "pom", "room"),
    "floor": ("floor", "fl", "etazh", "et", "kabat"),
    "block": ("block", "korpus", "korp", "stroenie", "str"),
    "house": ("house", "building", "bldg", "dom", "gimarat"),
}
_NUMBER = r"\d+(?:\s*[a-z](?![a-z]))?(?:\s*[/\-]\s*\d+[a-z]?)*"


def _latin(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold().translate(_CYRILLIC)
    value = "".join(character for character in unicodedata.normalize("NFKD", value)
                    if not unicodedata.combining(character))
    # y/i and q/k cover explicit common Kazakh/Russian romanizations.
    return re.sub(r"[a-z]+", lambda match: (match.group(0).replace("y", "i").replace("q", "k")
                                           if len(match.group(0)) > 1 else match.group(0)), value)


def _replace_words(value: str, words: tuple, replacement: str) -> str:
    alternatives = "|".join(re.escape(word) for word in sorted(words, key=len, reverse=True))
    return re.sub(r"(?<![a-z0-9])(?:" + alternatives + r")(?![a-z])\.?", replacement, value)


def _address_signature(value: str):
    value = _latin(value)
    components = re.split(r"[,;]", value)
    if len(components) > 1:
        components = [part for part in components
                      if re.sub(r"[^a-z]", "", part) not in {"astana", "gastana", "gorodastana", "cityastana"}]
    value = " ".join(components)
    street_types = set()
    for kind, words in _STREET_TYPES.items():
        updated = _replace_words(value, words, " ")
        if updated != value:
            street_types.add(kind)
            value = updated
    for kind, words in _SUBADDRESS.items():
        value = _replace_words(value, words, f" {kind} ")
    # A solitary street called D/Д is not the Russian house abbreviation.
    value = re.sub(r"(?<=[a-z])\s+d\.?\s*(?=\d)", " house ", value)
    # Sources place floor labels both before and after their number.
    value = re.sub(r"\b(\d+)(?:st|nd|rd|th|[-\s]*i)?\s+floor\b(?!\s*\d)", r" floor \1 ", value)
    subaddress = []

    def remove_subaddress(match):
        subaddress.append((match.group(1), re.sub(r"\s+", "", match.group(2))))
        return " "

    value = re.sub(r"\b(unit|floor|block)\s*(" + _NUMBER + r")(?![a-z0-9])", remove_subaddress, value)
    explicit_house = re.search(r"\bhouse\s*(" + _NUMBER + r")(?![a-z0-9])", value)
    if explicit_house:
        house = re.sub(r"\s+", "", explicit_house.group(1))
        value = value[:explicit_house.start()] + " " + value[explicit_house.end():]
    else:
        numbers = list(re.finditer(r"(?<![a-z0-9])" + _NUMBER + r"(?![a-z0-9])", value))
        if numbers:
            last = numbers[-1]
            house = re.sub(r"\s+", "", last.group(0))
            value = value[:last.start()] + " " + value[last.end():]
        else:
            house = None
    street = re.sub(r"[^a-z0-9]", "", value)
    # A building number or a city label cannot identify the street.
    if not re.search(r"[a-z]", street) or street in {"astana", "gastana", "gorodastana", "cityastana"}:
        return None
    return street, house, tuple(sorted(subaddress)), frozenset(street_types)


def addresses_compatible(left: str | None, right: str | None) -> bool:
    """Compare whole addresses, retaining explicit house/unit/floor differences.

    A missing whole address contributes no contradiction. An explicit subaddress
    on only one side is conservatively insufficient for an address match.
    """
    if left is None or right is None:
        return True
    if not isinstance(left, str) or not isinstance(right, str):
        return False
    if not left.strip() or not right.strip():
        return True
    a, b = _address_signature(left), _address_signature(right)
    if a is None or b is None:
        return False
    if a[:3] != b[:3]:
        return False
    return not a[3] or not b[3] or a[3] == b[3]


def _name_key(value: str) -> str:
    return re.sub(r"[^\w]", "", unicodedata.normalize("NFKC", value).casefold().replace("ё", "е"))


def _explicit_names(poi: dict) -> list[str]:
    values = [poi.get(field) for field in ("name", "name_en", "name_kk")]
    aliases = poi.get("aliases") or []
    if isinstance(aliases, list):
        values.extend(aliases)
    return [value for value in values if isinstance(value, str) and value.strip()]


def name_keys(poi: dict) -> set[str]:
    """Return complete normalized names and explicit aliases; no inferred aliases."""
    return {key for name in _explicit_names(poi) if (key := _name_key(name))}


def same_name(left: dict, right: dict) -> bool:
    """Use strict aliases, plus an explicit trailing city name for two malls."""
    a, b = name_keys(left), name_keys(right)
    if a & b:
        return True
    if left.get("category") != "mall" or right.get("category") != "mall":
        return False
    suffix = re.compile(r"[\s,;:()\-–—]+(?:astana|астана|астаны)\s*[)]?\s*$", re.IGNORECASE)
    for names, other_keys in ((_explicit_names(left), b), (_explicit_names(right), a)):
        for name in names:
            trimmed = suffix.sub("", name.strip())
            if trimmed != name.strip() and _name_key(trimmed) in other_keys:
                return True
    return False

"""Text normalisation shared by the pipeline (dedup/matching) and the API (gazetteer, BM25)."""
from __future__ import annotations

import re
import unicodedata

# Kazakh-specific Cyrillic letters folded to their closest Russian letter
KK_TO_RU = str.maketrans({"ә": "а", "ғ": "г", "қ": "к", "ң": "н", "ө": "о", "ұ": "у", "ү": "у", "һ": "х", "і": "и", "ё": "е"})
CYR_TO_LAT = dict(zip(
    "абвгдежзийклмнопрстуфхцчшщъыьэюя",
    ["a", "b", "v", "g", "d", "e", "zh", "z", "i", "i", "k", "l", "m", "n", "o", "p", "r", "s", "t", "u", "f",
     "h", "ts", "ch", "sh", "sch", "", "y", "", "e", "yu", "ya"]))
KK_LETTERS = set("әғқңөұүһі")
_STOP = r"\b(kafe|cafe|coffee|kofeinya|kofeynya|restoran|restaurant|bar|trts|trk|tts|the|park|skver|muzei|museum|teatr|ul|ulitsa|prospekt|pr)\b"
_ZW = re.compile(r"[​-‏ - ⁠-⁯﻿]")


def fold(s: str | None) -> str:
    """Lowercase, strip accents/zero-width chars, fold Kazakh letters to Russian ones."""
    s = _ZW.sub("", unicodedata.normalize("NFKC", s or "")).lower().translate(KK_TO_RU)
    return re.sub(r"\s+", " ", s).strip()


def translit(s: str | None) -> str:
    return "".join(CYR_TO_LAT.get(c, c) for c in fold(s))


def match_key(s: str | None) -> str:
    """Script-independent key for fuzzy name matching across OSM/Overture/Wikidata."""
    s = re.sub(r"[«»\"'`’]", " ", translit(s))
    s = re.sub(_STOP, " ", s)
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def has_kazakh(s: str) -> bool:
    return any(c in KK_LETTERS for c in (s or "").lower())


def tokens(s: str) -> list[str]:
    return re.findall(r"[a-zа-я0-9]+", fold(s))


_CITY = re.compile(r"\b(astana|nur sultan|nursultan|akmola|tselinograd)\b")


def name_keys(s: str | None) -> list[str]:
    """Match keys of every variant of a bilingual name ("Парк «Арай» / Arai Park"), city name removed."""
    parts = [s or ""] + re.split(r"\s+/\s+|\s*\|\s*", s or "")
    parts += [re.sub(r"\([^)]*\)", " ", x) for x in parts]  # "Казак ели (монумент)" -> "Казак ели"
    keys = {re.sub(r"\s+", " ", _CITY.sub(" ", match_key(x))).strip() for x in parts}
    return [k for k in keys if k]


def same_name(a: str, b: str, threshold: int = 85) -> bool:
    """Fuzzy equality of two place names. token_set alone treats "Jasmine Coffee room Astana" == "Astana";
    we require the shorter name to cover most of the longer one."""
    return any(_same_key(ka, kb, threshold) for ka in name_keys(a) for kb in name_keys(b))


def _same_key(ka: str, kb: str, threshold: int) -> bool:
    from rapidfuzz import fuzz
    if fuzz.ratio(ka, kb) >= threshold or fuzz.token_sort_ratio(ka, kb) >= threshold:
        return True
    short, long_ = sorted((ka, kb), key=len)
    return fuzz.token_set_ratio(ka, kb) >= max(threshold, 90) and len(short) >= 0.6 * len(long_)


def contains_name(a: str, b: str) -> bool:
    """One name is the other plus descriptors ("ПИНТА Bar & Grill" / "Пинта"). Only safe for points a few metres apart."""
    from rapidfuzz import fuzz
    return any(min(len(ka), len(kb)) >= 4 and fuzz.token_set_ratio(ka, kb) >= 90
               for ka in name_keys(a) for kb in name_keys(b))

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

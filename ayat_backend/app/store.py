"""In-memory POI store: loads the processed snapshot once at startup.

~2.5k POIs: numpy arrays for geo math, BM25 over Russian-stemmed documents and an
optional dense matrix (e5). No database service is needed at this scale.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

import numpy as np
import snowballstemmer
from rank_bm25 import BM25Okapi

from app.categories import CATEGORIES
from app.features import cuisine_ru, feature_labels
from app.paths import EMBEDDINGS_FILE, EVENTS_FILE, GAZETTEER_FILE, MANIFEST_FILE, POIS_FILE, RIVER_FILE
from app.textnorm import fold, tokens

log = logging.getLogger("app.store")
_stem = snowballstemmer.stemmer("russian")

# extra retrieval vocabulary per category group (helps BM25 on short tag-only POIs)
GROUP_WORDS = {
    "culture": "культура искусство выставка экспозиция",
    "sight": "достопримечательность смотреть фото туристы прогулка",
    "nature": "прогулка природа свежий воздух гулять зелень",
    "kids": "дети ребенок семья малыш детский игры",
    "shopping": "покупки магазины тепло",
    "food": "еда поесть перекусить",
    "night": "ночь вечер поздно тусовка",
    "active": "активный спорт развлечение",
    "relax": "отдых расслабиться",
    "work": "работа ноутбук розетка тихо wifi",
    "quiet": "тихо спокойно читать работа",
    "entertainment": "развлечение кино вечер",
}
CATEGORY_WORDS = {
    "cafe": "кофе кофейня капучино десерт посидеть",
    "museum": "музей экспозиция история интерактив",
    "playground": "площадка горка качели дети",
    "kids_indoor": "игровая батуты дети развлечения",
    "zoo_aquarium": "рыбы животные океанариум дети",
    "viewpoint": "вид панорама смотровая",
    "landmark": "символ города панорама фото",
    "mall": "трц торговый центр кино фудкорт тепло",
    "bar": "коктейли вечер",
    "worship": "мечеть храм архитектура",
    "park": "парк аллеи гулять",
    "library": "книги читать тихо",
    "coworking": "ноутбук розетки работа",
}


def stem_tokens(text: str) -> list[str]:
    return [_stem.stemWord(t) for t in tokens(text) if len(t) > 1]


def poi_document(p: dict) -> str:
    c = CATEGORIES[p["category"]]
    parts = [p["name"], *p.get("names", {}).values(), *c.labels, GROUP_WORDS.get(c.group, ""),
             CATEGORY_WORDS.get(p["category"], ""), ", ".join(cuisine_ru(p.get("cuisine"))),
             ", ".join(feature_labels(p.get("features", {}), "ru")), (p.get("description") or "")[:300]]
    if c.kids:
        parts.append(GROUP_WORDS["kids"])
    if c.night:
        parts.append(GROUP_WORDS["night"])
    if c.quiet:
        parts.append(GROUP_WORDS["quiet"])
    return ". ".join(x for x in parts if x)


@dataclass
class Store:
    pois: list[dict]
    lat: np.ndarray
    lon: np.ndarray
    cats: np.ndarray
    popularity: np.ndarray
    bm25: BM25Okapi
    gazetteer: list[dict]
    river: list
    manifest: dict
    events: list[dict] = field(default_factory=list)
    emb: np.ndarray | None = None
    by_id: dict[str, int] = field(default_factory=dict)

    @property
    def size(self) -> int:
        return len(self.pois)


def load_store(embed_model: str | None = None) -> Store:
    pois = [json.loads(line) for line in POIS_FILE.open(encoding="utf-8") if line.strip()]
    docs = [stem_tokens(poi_document(p)) for p in pois]
    emb = None
    meta = {}
    if MANIFEST_FILE.exists():
        meta = json.loads(MANIFEST_FILE.read_text())
    if embed_model and EMBEDDINGS_FILE.exists():
        e = np.load(EMBEDDINGS_FILE)
        if (e.shape[0] == len(pois) and meta.get("embedding_model") == embed_model
                and meta.get("embedding_pois_sha") == meta.get("pois_sha")):
            emb = e.astype(np.float32)
        else:
            log.warning("embeddings file does not match POIs/model (%s vs %s), dense retrieval off",
                        meta.get("embedding_model"), embed_model)
    gaz = json.loads(GAZETTEER_FILE.read_text()) if GAZETTEER_FILE.exists() else []
    for g in gaz:
        g["keys"] = [fold(k) for k in g["keys"]]
    events = []
    if EVENTS_FILE.exists():
        events = [json.loads(line) for line in EVENTS_FILE.open(encoding="utf-8") if line.strip()]
    st = Store(
        pois=pois,
        lat=np.array([p["lat"] for p in pois], dtype=np.float64),
        lon=np.array([p["lon"] for p in pois], dtype=np.float64),
        cats=np.array([p["category"] for p in pois]),
        popularity=np.array([p.get("popularity", 0.0) for p in pois], dtype=np.float32),
        bm25=BM25Okapi(docs),
        gazetteer=gaz,
        river=json.loads(RIVER_FILE.read_text()) if RIVER_FILE.exists() else [],
        manifest=meta,
        events=events,
        emb=emb,
        by_id={p["id"]: i for i, p in enumerate(pois)},
    )
    log.info("store: %d POIs, %d gazetteer entries, dense=%s, events=%d", st.size, len(gaz), emb is not None, len(events))
    return st

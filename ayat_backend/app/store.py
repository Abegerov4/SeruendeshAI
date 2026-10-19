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

from ayat_backend.app.categories import CATEGORIES
from ayat_backend.app.features import cuisine_ru, feature_labels
from ayat_backend.app.paths import DATA_DIR, EMBEDDINGS_FILE, EVENTS_FILE, GAZETTEER_FILE, MANIFEST_FILE, POIS_FILE, RIVER_FILE
from ayat_backend.app.textnorm import fold, tokens

log = logging.getLogger("app.store")
_stem = snowballstemmer.stemmer("russian")
CANONICAL_POIS_FILE = POIS_FILE.with_name("pois.json")
CANONICAL_QUARANTINE_FILE = DATA_DIR / "quarantine.json"

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
    parts = [p["name"], *p.get("names", {}).values(), *p.get("aliases", []), *c.labels, GROUP_WORDS.get(c.group, ""),
             CATEGORY_WORDS.get(p["category"], ""), ", ".join(cuisine_ru(p.get("cuisine"))),
             ", ".join(feature_labels(p.get("features", {}), "ru")), (p.get("description") or "")[:300]]
    if c.kids:
        parts.append(GROUP_WORDS["kids"])
    if c.night:
        parts.append(GROUP_WORDS["night"])
    if c.quiet:
        parts.append(GROUP_WORDS["quiet"])
    details = p.get("place_details") or {}
    parts += [" ".join([m["name"],*m.get("components",[]),*m.get("aliases",[])]) for m in details.get("menu_items",[])]
    parts += [str(f["value"]) for f in details.get("facts",[]) if f["field"] in {"format","cuisine","cuisines","activities","services"}]
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
    services: list[dict] = field(default_factory=list)

    @property
    def size(self) -> int:
        return len(self.pois)


def load_store(embed_model: str | None = None) -> Store:
    import os
    from data.snapshot import resolve_snapshot
    selected = resolve_snapshot(CANONICAL_POIS_FILE.parent, legacy=os.getenv("DATA_SNAPSHOT_MODE", "") == "legacy")
    bound = selected.version != "legacy"
    canonical_path = selected.path / "pois.json" if bound else CANONICAL_POIS_FILE
    canonical = canonical_path.exists()
    gazetteer_file = selected.path / GAZETTEER_FILE.name if bound else GAZETTEER_FILE
    events_file = selected.path / EVENTS_FILE.name if bound else EVENTS_FILE
    river_file = selected.path / RIVER_FILE.name if bound else RIVER_FILE
    if canonical:
        from ayat_backend.app.team_data import load_team_snapshot
        review_path = selected.path / "quarantine.json" if bound else CANONICAL_QUARANTINE_FILE
        pois, gaz, meta = load_team_snapshot(canonical_path, quarantine_path=review_path if review_path.exists() else None)
        meta["snapshot_version"] = selected.version
        meta["snapshot_path"] = str(selected.path)
        meta["bundle_manifest"] = selected.manifest
        # Curated UI keys remain available alongside canonical source names.
        if gazetteer_file.exists():
            gaz += [g for g in json.loads(gazetteer_file.read_text()) if g.get("kind") == "landmark"]
    else:
        pois = [json.loads(line) for line in POIS_FILE.open(encoding="utf-8") if line.strip()]
        meta = json.loads(MANIFEST_FILE.read_text()) if MANIFEST_FILE.exists() else {}
        gaz = json.loads(gazetteer_file.read_text()) if gazetteer_file.exists() else []
    if not pois:
        raise ValueError("Recommendation snapshot is empty")
    docs = [stem_tokens(poi_document(p)) for p in pois]
    emb = None
    if canonical and embed_model not in (None, "", "off", "none"):
        from ayat_backend.app.canonical_index import load_index, policy_hashes
        index_dir = os.getenv("CANONICAL_INDEX_DIR") or str(selected.path if bound else selected.path / "canonical_index")
        try:
            emb = load_index(pois, embed_model, index_dir, policy_hashes=policy_hashes(selected.path))
            meta["dense_disabled"] = False
            meta["dense_disabled_reason"] = None
            meta["canonical_index_path"] = index_dir
        except (OSError, ValueError, KeyError, TypeError) as exc:
            log.warning("canonical index unavailable (%s); BM25 active", type(exc).__name__)
            meta["dense_disabled_reason"] = str(exc)[:160]
    if not canonical and embed_model not in (None, "", "off", "none") and EMBEDDINGS_FILE.exists():
        e = np.load(EMBEDDINGS_FILE)
        if (e.shape[0] == len(pois) and meta.get("embedding_model") == embed_model
                and meta.get("embedding_pois_sha") == meta.get("pois_sha")):
            emb = e.astype(np.float32)
        else:
            log.warning("embeddings file does not match POIs/model (%s vs %s), dense retrieval off",
                        meta.get("embedding_model"), embed_model)
    for g in gaz:
        g["keys"] = [fold(k) for k in g["keys"]]
    events = []
    if events_file.exists():
        events = [json.loads(line) for line in events_file.open(encoding="utf-8") if line.strip()]
    if canonical:
        venue_owners: dict[str, set[str]] = {}
        for p in pois:
            for alias in {p["id"], *p.get("id_aliases", []), *p.get("source_ids", [])}:
                venue_owners.setdefault(alias, set()).add(p["id"])
        collisions = meta.get("id_alias_collisions", {})
        counts = {"loaded": len(events), "active": 0, "remapped": 0, "excluded": 0,
                  "excluded_unmatched": 0, "excluded_ambiguous": 0}
        linked_events = []
        for event in events:
            source_id = event.get("poi_id")
            owners = venue_owners.get(source_id, set())
            if len(owners) != 1 or source_id in collisions:
                reason = "ambiguous" if len(owners) > 1 or source_id in collisions else "unmatched"
                counts["excluded"] += 1
                counts[f"excluded_{reason}"] += 1
                continue
            canonical_id = next(iter(owners))
            linked_events.append({**event, "poi_id": canonical_id, "source_poi_id": source_id})
            counts["remapped"] += source_id != canonical_id
        events = linked_events
        counts["active"] = len(events)
        meta["events"] = counts
    st = Store(
        pois=pois,
        lat=np.array([p["lat"] for p in pois], dtype=np.float64),
        lon=np.array([p["lon"] for p in pois], dtype=np.float64),
        cats=np.array([p["category"] for p in pois]),
        popularity=np.array([p.get("popularity", 0.0) for p in pois], dtype=np.float32),
        bm25=BM25Okapi(docs),
        gazetteer=gaz,
        river=json.loads(river_file.read_text()) if river_file.exists() else [],
        manifest=meta,
        events=events,
        emb=emb,
        by_id={p["id"]: i for i, p in enumerate(pois)},
    )
    service_path = selected.path / "city_services.json"
    if service_path.exists():
        from data.city_services import load_city_services
        st.services = [service.model_dump(mode="json") for service in load_city_services(service_path).services]
        st.manifest["city_services"] = len(st.services)
    log.info("store: %d POIs, %d gazetteer entries, dense=%s, events=%d", st.size, len(gaz), emb is not None, len(events))
    return st

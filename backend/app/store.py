"""In-memory POI store: loads the processed snapshot once at startup.

~2.5k POIs: numpy arrays for geo math, BM25 over Russian-stemmed documents and an
optional dense matrix (e5). No database service is needed at this scale.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

import numpy as np
import snowballstemmer
from rank_bm25 import BM25Okapi

from app.categories import CATEGORIES
from app.features import cuisine_ru, feature_labels
from app.paths import DATA_DIR, EMBEDDINGS_FILE, EVENTS_FILE, GAZETTEER_FILE, MANIFEST_FILE, POIS_FILE, RIVER_FILE
from app.textnorm import fold, tokens

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


# Overture rows named after a region or an address ("Северный Казахстан, Казахстан", "Fashion Park Almaty, Достык, 40")
JUNK_PLACE = re.compile(r"^(?:северн|южн|западн|восточн|центральн)\w*\s+казахстан|,\s*[^,]+,\s*\d+\w*\s*$|"
                        r"^(?:астана|алматы|almaty)\s+(?:ул|пр)\b", re.IGNORECASE)
_COUNTRY_SUFFIX = re.compile(r",\s*(?:казахстан|kazakhstan|қазақстан)\s*$", re.IGNORECASE)


def junk_place(p: dict) -> bool:
    """True for rows that are not places; also trims a trailing ", Казахстан" from real names."""
    if JUNK_PLACE.search(p["name"]):
        return True
    p["name"] = _COUNTRY_SUFFIX.sub("", p["name"]).strip() or p["name"]
    return False


# Astana only: an event whose title or venue names another city, or a trip out of town, is not shown
# (the address is not checked: Astana has an «улица Алматы»)
OUTSIDE_ASTANA = re.compile(r"алмат|almaty|шымкент|shymkent|караганд|karagand|актобе|aktobe|атырау|atyrau|павлодар|pavlodar|"
                            r"костанай|kostanay|усть-?каменогорск|oskemen|өскемен|\bсемей\b|\bsemey\b|тараз|taraz|кокшетау|kokshetau|"
                            r"петропавловск|petropavl|актау|aktau|уральск|кызылорд|kyzylord|талдыкорган|боровое|бурабай|burabay|borovoe|"
                            r"щучинск|балхаш|туркестан[еау]?\s+(?:город|city)|москв|moscow|бишкек|bishkek|ташкент|tashkent", re.I)


def outside_astana(event: dict) -> bool:
    return bool(OUTSIDE_ASTANA.search(f"{event.get('title') or ''} {event.get('venue') or ''}"))


def apply_facts(pois: list[dict], facts: dict[str, dict]) -> None:
    """Researched facts (descriptions in our own words, published hours, features) for the most recommended places.
    Official hours checked on a date win over older map data; a Wikipedia description keeps its attribution."""
    from urllib.parse import urlparse
    for p in pois:
        f = facts.get(p["id"])
        if not f:
            continue
        if f.get("status") == "closed_permanently":
            p["closed_permanently"] = True  # a source says it closed: never recommended
            continue
        if f.get("drop_website"):  # the domain is gone, parked or now someone else's (one served a casino)
            p["website"] = None
        if f.get("description_ru") and p.get("description_source") != "wikipedia":
            p.update(description=f["description_ru"], description_en=f.get("description_en"), description_source="research",
                     description_kind="research", description_url=f["description_url"])
        if f.get("opening_hours"):
            p.update(opening_hours=f["opening_hours"], hours_source=urlparse(f["hours_url"]).netloc.removeprefix("www."),
                     hours_source_url=f["hours_url"], check_date=f["checked"], hours_note=f.get("hours_note"))
        feats = p.setdefault("features", {})
        for k, v in (f.get("features") or {}).items():
            key = "free" if k == "free_entry" else k
            if feats.get(key) is None:
                feats[key] = v


# big indoor venues that open data leaves unflagged (a theme park category would read as outdoors at −25°C)
INDOOR_NAMES = re.compile(r"ailand|айленд|думан|happylon|хэппилон|fame city|хан шатыр|khan shatyr", re.IGNORECASE)


def display_name(p: dict, lang: str) -> str:
    """The place's name in the user's language (the map's own name:xx, else pipeline.place_names), else as mapped."""
    return (p.get("names") or {}).get(lang) or p["name"]


def courtyard_playground(p: dict) -> bool:
    """An unnamed playground labelled after the residential complex it stands in (pipeline.build.label_unnamed,
    «Детская площадка в ЖК …»): a courtyard playground, often behind the complex's gate — on the map, never a pick."""
    return p["category"] == "playground" and bool(p.get("yard") or (p.get("name_auto") and " в ЖК «" in p["name"]))


def _richness(p: dict) -> tuple:
    return (bool(p.get("description")), bool(p.get("opening_hours")), bool(p.get("wikidata")), p.get("popularity") or 0)


def _dedupe(idx: list[int], pois: list[dict], aliases: dict[str, str]) -> list[int]:
    """One record per venue: the same name within ~200 m is the same place (Ailand was mapped four times)."""
    groups: dict[str, list[int]] = {}
    out: list[int] = []
    for i in idx:
        p = pois[i]
        if INDOOR_NAMES.search(p["name"]) and p.get("indoor") is None:
            p["indoor"] = True
        if p.get("name_auto"):
            out.append(i)
            continue
        kept = groups.setdefault(fold(p["name"]), [])
        near = next((k for k, j in enumerate(kept) if abs(pois[j]["lat"] - p["lat"]) < 0.0018
                     and abs(pois[j]["lon"] - p["lon"]) < 0.0029), None)
        if near is None:
            kept.append(i)
            continue
        if _richness(p) > _richness(pois[kept[near]]):
            kept[near], i = i, kept[near]
        aliases[pois[i]["id"]] = pois[kept[near]]["id"]  # links to the dropped copy follow the kept one
    for a, b in list(aliases.items()):
        while b in aliases:
            b = aliases[b]
        aliases[a] = b
    return sorted(out + [i for kept in groups.values() for i in kept])


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
    from types import SimpleNamespace
    # Default: our pipeline snapshot (pois.jsonl, photos, descriptions, hotels). The team's canonical catalogue
    # (data/, Aslan) is opt-in with DATA_SNAPSHOT_MODE=canonical and needs the repository's data package.
    canonical_mode = os.getenv("DATA_SNAPSHOT_MODE", "legacy") == "canonical"
    if canonical_mode:
        from data.snapshot import resolve_snapshot
        selected = resolve_snapshot(CANONICAL_POIS_FILE.parent)
    else:
        selected = SimpleNamespace(version="legacy", path=POIS_FILE.parent, manifest=None)
    bound = selected.version != "legacy"
    canonical_path = selected.path / "pois.json" if bound else CANONICAL_POIS_FILE
    canonical = canonical_mode and canonical_path.exists()
    gazetteer_file = selected.path / GAZETTEER_FILE.name if bound else GAZETTEER_FILE
    events_file = selected.path / EVENTS_FILE.name if bound else EVENTS_FILE
    river_file = selected.path / RIVER_FILE.name if bound else RIVER_FILE
    if canonical:
        from app.team_data import load_team_snapshot
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
        from app.canonical_index import load_index, policy_hashes
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
    aliases: dict[str, str] = {}
    extra_file = POIS_FILE.parent / "photos_extra.json"  # pipeline.place_images: Commons near the place, venue sites
    if not canonical and extra_file.exists():
        extra = json.loads(extra_file.read_text())
        for p in pois:
            if not p.get("photo") and extra.get(p["id"]):
                p["photo"] = extra[p["id"]]
    facts_file = POIS_FILE.parent / "place_facts.json"  # pipeline.place_facts: researched, every fact with its source
    if not canonical and facts_file.exists():
        apply_facts(pois, json.loads(facts_file.read_text()))
    names_file = POIS_FILE.parent / "place_names.json"  # pipeline.place_names: ru/kk/en; the map's own names win
    if not canonical and names_file.exists():
        extra_names = json.loads(names_file.read_text())
        for p in pois:
            if (more := extra_names.get(p["id"])) and not p.get("name_auto"):
                p["names"] = {**more, **{k: v for k, v in (p.get("names") or {}).items() if v}}
        for g in gaz:  # «Старт: Бәйтерек / Baiterek»: curated landmarks are named in the user's language too
            if g.get("landmark_key") and (more := extra_names.get(f"landmark:{g['landmark_key']}")):
                g["names"] = more
    kk_file = POIS_FILE.parent / "place_descriptions_kk.json"  # pipeline.place_names: researched texts in Kazakh
    if not canonical and kk_file.exists():
        kk_text = json.loads(kk_file.read_text())
        for p in pois:
            if p.get("description_kind") == "research" and kk_text.get(p["id"]):
                p["description_kk"] = kk_text[p["id"]]
    from app.card_photos import apply_card_photos  # optional operator photos in S3 (docs/CARD_PHOTOS.md)
    apply_card_photos(pois)
    keep = _dedupe([i for i, p in enumerate(pois) if not junk_place(p) and not p.get("closed_permanently")], pois, aliases)
    if len(keep) < len(pois):  # region names, addresses and the same venue mapped several times
        log.info("dropped %d junk/duplicate places", len(pois) - len(keep))
        pois, docs = [pois[i] for i in keep], [docs[i] for i in keep]
        emb = emb[keep] if emb is not None else None
    for g in gaz:
        g["keys"] = [fold(k) for k in g["keys"]]
    events = []
    if events_file.exists():
        events = [e for line in events_file.open(encoding="utf-8") if line.strip() and not outside_astana(e := json.loads(line))]
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
    for dropped, kept in aliases.items():
        if kept in st.by_id:
            st.by_id.setdefault(dropped, st.by_id[kept])
    for e in st.events:
        if e.get("poi_id") in aliases:
            e["poi_id"] = aliases[e["poi_id"]]
    service_path = selected.path / "city_services.json"
    if service_path.exists():
        from data.city_services import load_city_services
        st.services = [service.model_dump(mode="json") for service in load_city_services(service_path).services]
        st.manifest["city_services"] = len(st.services)
    log.info("store: %d POIs, %d gazetteer entries, dense=%s, events=%d", st.size, len(gaz), emb is not None, len(events))
    return st

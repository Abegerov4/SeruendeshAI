"""Merge raw sources into the POI snapshot the API serves (data/processed/*)."""
from __future__ import annotations

import datetime as dt
import json
import logging
import math
import re
from collections import Counter, defaultdict

from rapidfuzz import fuzz
from shapely.geometry import Point, shape
from shapely.prepared import prep

from app.categories import CATEGORIES, category_from_osm, label
from app.features import cuisine_ru, feature_labels, features_from_osm
from app.paths import BOUNDARY_FILE, GAZETTEER_FILE, MANIFEST_FILE, POIS_FILE, RIVER_FILE
from app.textnorm import contains_name, fold, match_key, same_name
from pipeline.common import write_jsonl
from pipeline.landmarks import LANDMARKS
from pipeline.osm import element_latlon, element_url
from pipeline.wiki import wikidata_category

log = logging.getLogger("pipeline.build")


def hav(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * 6371008.8 * math.asin(math.sqrt(a))


class Grid:
    """Tiny spatial hash (~550 m cells) for radius lookups during merging."""

    def __init__(self, items, key=lambda x: (x["lat"], x["lon"])):
        self.key, self.cells = key, defaultdict(list)
        for it in items:
            self.add(it)

    def add(self, it):
        la, lo = self.key(it)
        self.cells[(round(la * 200), round(lo * 120))].append(it)

    def near(self, lat: float, lon: float, r: float):
        gy, gx = round(lat * 200), round(lon * 120)
        span = max(1, int(r // 500) + 1)
        for dy in range(-span, span + 1):
            for dx in range(-span, span + 1):
                for it in self.cells.get((gy + dy, gx + dx), ()):
                    la, lo = self.key(it)
                    d = hav(lat, lon, la, lo)
                    if d <= r:
                        yield d, it


def _addr(t: dict) -> str | None:
    street, num = t.get("addr:street"), t.get("addr:housenumber")
    if street and num:
        return f"{street}, {num}"
    return street or t.get("addr:full")


def _osm_id(e: dict) -> str:
    return f"osm:{e['type'][0]}{e['id']}"


GENERIC_NAMES = {"сквер", "парк", "skver", "park", "саябақ", "саябак", "гүлзар", "гулзар", "детская площадка",
                 "балалар алаңы", "балалар аланы", "playground", "площадка", "бульвар", "аллея", "square"}


def osm_to_pois(elements: list[dict], inside) -> list[dict]:
    pois = []
    for e in elements:
        t = e.get("tags", {})
        cat = category_from_osm(t)
        ll = element_latlon(e)
        if not cat or not ll or not inside(*ll):
            continue
        name = (t.get("name") or t.get("name:ru") or t.get("name:kk") or t.get("name:en") or "").strip()
        if fold(name) in GENERIC_NAMES:
            name = ""  # "Сквер", "Детская площадка" etc. are not real names: label them by location instead
        if not name and cat not in ("playground", "park", "garden"):
            continue
        feats = features_from_osm(t)
        pois.append({
            "id": _osm_id(e), "name": name, "name_auto": not name,
            "names": {k: t[f"name:{k}"] for k in ("ru", "kk", "en") if t.get(f"name:{k}")},
            "category": cat, "lat": round(ll[0], 6), "lon": round(ll[1], 6),
            "address": _addr(t), "opening_hours": (t.get("opening_hours") or "").strip() or None,
            "check_date": t.get("check_date:opening_hours") or t.get("check_date"),
            "features": feats, "cuisine": t.get("cuisine"), "brand": t.get("brand"),
            "website": t.get("website") or t.get("contact:website"), "phone": t.get("phone") or t.get("contact:phone"),
            "instagram": t.get("contact:instagram"), "wikidata": t.get("wikidata"),
            "description": (t.get("description") or "").strip() or None, "description_source": "osm" if t.get("description") else None,
            "indoor": True if feats.get("indoor") else None, "heritage": bool(t.get("heritage")),
            "osm_tags_count": len(t), "sources": ["osm"], "source_url": element_url(e),
        })
    log.info("OSM destinations: %d", len(pois))
    return pois


def dedupe(pois: list[dict]) -> list[dict]:
    """Drop node/way duplicates of the same place (same category, similar name, < 120 m)."""
    pois.sort(key=lambda p: -p["osm_tags_count"])
    kept, grid = [], Grid([])
    for p in pois:
        dup = False
        if not p["name_auto"]:
            k = match_key(p["name"])
            for _, q in grid.near(p["lat"], p["lon"], 120):
                if q["category"] == p["category"] and not q["name_auto"] and fuzz.token_set_ratio(k, match_key(q["name"])) >= 90:
                    dup = True
                    for f in ("opening_hours", "website", "phone", "address", "wikidata", "cuisine"):
                        q[f] = q[f] or p[f]
                    break
        else:  # unnamed parks/playgrounds: drop if another one of same category is within 40 m
            dup = any(q["category"] == p["category"] for _, q in grid.near(p["lat"], p["lon"], 40))
        if not dup:
            kept.append(p)
            grid.add(p)
    log.info("after dedupe: %d (-%d)", len(kept), len(pois) - len(kept))
    return kept


def label_unnamed(pois: list[dict], context: list[dict]) -> None:
    """Give unnamed playgrounds/parks a human label from the nearest named park / residential complex / street."""
    generic = {"сквер", "парк", "skver", "park", "саябақ", "гүлзар", "бульвар"}
    parks = Grid([p for p in pois if p["category"] in ("park", "garden") and not p["name_auto"]
                  and fold(p["name"]) not in generic])
    res, streets = [], []
    for e in context:
        t, ll = e.get("tags", {}), element_latlon(e)
        if not ll or not t.get("name"):
            continue
        item = {"lat": ll[0], "lon": ll[1], "name": t["name"]}
        if t.get("landuse") == "residential" or t.get("place"):
            res.append(item)
        elif t.get("highway"):
            streets.append(item)
    res_g, st_g = Grid(res), Grid(streets)
    stats = Counter()
    for p in pois:
        if not p["name_auto"]:
            continue
        base = {"playground": ("Детская площадка", "Балалар алаңы", "Playground"),
                "park": ("Сквер", "Саябақ", "Small park"), "garden": ("Сквер", "Гүлзар", "Garden square")}[p["category"]]
        anchor, kind = None, None
        for grid, r, k in ((parks, 300, "park"), (res_g, 250, "res"), (st_g, 200, "street")):
            hits = sorted(grid.near(p["lat"], p["lon"], r), key=lambda x: x[0])
            if hits:
                anchor, kind = hits[0][1]["name"], k
                break
        stats[kind or "none"] += 1
        if anchor:
            prep_ru = "в парке" if kind == "park" else ("в ЖК" if kind == "res" else "на")
            p["name"] = f"{base[0]} {prep_ru} «{anchor}»" if kind != "street" else f"{base[0]} ({anchor})"
            p["names"] = {"ru": p["name"], "kk": f"{base[1]} ({anchor})", "en": f"{base[2]} ({anchor})"}
        else:
            p["name"] = base[0]
            p["names"] = {"ru": base[0], "kk": base[1], "en": base[2]}
    log.info("auto-labelled unnamed places: %s", dict(stats))


SETTLEMENT = re.compile(r"\b(city|capital|human settlement|settlement|administrative|district|country|region|oblast|"
                        r"municipality|big city|million city|city of kazakhstan|neighborhood|neighbourhood|microdistrict)\b")


FOOD_NIGHT = {"cafe", "restaurant", "bar", "fast_food", "sweets", "hookah", "nightclub", "karaoke", "coworking"}


def wd_compatible(p: dict, it: dict) -> bool:
    """A café called "Mega" must not inherit the article about the Mega mall."""
    wc = wikidata_category(it["classes"])
    return (p["category"] in FOOD_NIGHT) == (wc in FOOD_NIGHT) if wc else p["category"] not in FOOD_NIGHT


def merge_wikidata(pois: list[dict], items: list[dict], inside) -> list[dict]:
    by_qid = {p["wikidata"]: p for p in pois if p.get("wikidata")}
    grid = Grid([p for p in pois if not p["name_auto"]])
    added, matched = [], 0
    for it in items:
        if not inside(it["lat"], it["lon"]):
            continue
        if SETTLEMENT.search(" | ".join(it["classes"]).lower()):
            continue  # a city/district/region is not a café (bug found by the team QA suite)
        target = by_qid.get(it["qid"])
        if target and not wd_compatible(target, it):
            target["wikidata"] = None  # OSM brand/operator tag pointing at an unrelated item
            target = None
        if not target:
            labels = [x for x in (it["label_ru"], it["label_en"], it["label_kk"]) if x]
            best = None
            for d, p in grid.near(it["lat"], it["lon"], 300):
                if not wd_compatible(p, it):
                    continue
                # same name, or a longer/shorter variant next door, or the same kind of place a few metres away
                # ("Парк Влюбленных" = "Ғашықтар саябағы")
                if (any(same_name(lb, p["name"]) for lb in labels) or d <= 100 and any(contains_name(lb, p["name"]) for lb in labels)
                        or d <= 40 and p["category"] == wikidata_category(it["classes"])) and (best is None or d < best[0]):
                    best = (d, p)
            target = best[1] if best else None
        if target:
            matched += 1
            target["wikidata"] = it["qid"]
            _apply_wd(target, it)
            continue
        cat = wikidata_category(it["classes"])
        name = it["label_ru"] or it["label_en"] or it["label_kk"]
        if not cat or not name or it["sitelinks"] < 2:
            continue
        p = {"id": f"wd:{it['qid']}", "name": name, "name_auto": False, "names": {}, "category": cat,
             "lat": round(it["lat"], 6), "lon": round(it["lon"], 6), "address": None, "opening_hours": None,
             "check_date": None, "features": {}, "cuisine": None, "brand": None, "website": it["website"], "phone": None,
             "instagram": None, "wikidata": it["qid"], "description": None, "description_source": None,
             "indoor": None, "heritage": False, "osm_tags_count": 0, "sources": [],
             "source_url": f"https://www.wikidata.org/wiki/{it['qid']}"}
        _apply_wd(p, it)
        added.append(p)
        by_qid[it["qid"]] = p
    log.info("wikidata: matched %d, added %d new landmarks", matched, len(added))
    return pois + added


def _apply_wd(p: dict, it: dict) -> None:
    for lang in ("ru", "kk", "en"):
        if it.get(f"label_{lang}") and lang not in p["names"]:
            p["names"][lang] = it[f"label_{lang}"]
    p["sitelinks"] = it["sitelinks"]
    p["website"] = p.get("website") or it.get("website")
    p["wikidata_desc"] = it.get("desc_ru") or it.get("desc_en")
    p["image"] = it.get("image")
    if "wikidata" not in p["sources"]:
        p["sources"].append("wikidata")


def merge_wikipedia(pois: list[dict], articles: dict[str, list[dict]]) -> None:
    by_qid = {p["wikidata"]: p for p in pois if p.get("wikidata")}
    n = Counter()
    for lang in ("ru", "en"):
        for a in articles.get(lang, []):
            p = by_qid.get(a.get("qid"))
            if not p or not a.get("extract"):
                continue
            p.setdefault("wiki", {})[lang] = {"url": a["url"], "pageviews": a.get("pageviews", 0)}
            p["pageviews"] = p.get("pageviews", 0) + a.get("pageviews", 0)
            if not p.get("description") or (p.get("description_source") == "wikipedia" and p.get("description_lang") != "ru" and lang == "ru"):
                p["description"] = _clean_extract(a["extract"])
                p["description_source"], p["description_lang"] = "wikipedia", lang
                p["description_url"] = a["url"]
                p["description_title"] = a["title"]
                p["description_license"] = "CC BY-SA 4.0 · Wikipedia contributors"
            if "wikipedia" not in p["sources"]:
                p["sources"].append("wikipedia")
            n[lang] += 1
    log.info("wikipedia extracts attached: %s", dict(n))


def add_sitelink_extracts(pois: list[dict], wd_items: list[dict]) -> None:
    """POIs with a Wikidata id but no Wikipedia text: fetch the article by sitelink (ru -> kk -> en).
    Method from the team's data pipeline (enrich_wiki.py by Denis)."""
    from pipeline.wiki import fetch_extract
    by_qid = {it["qid"]: it for it in wd_items}
    n = 0
    for p in pois:
        if p.get("description_source") == "wikipedia" or not p.get("wikidata") or p["wikidata"] not in by_qid:
            continue
        it = by_qid[p["wikidata"]]
        for lang in ("ru", "kk", "en"):
            url = it.get(f"{lang}wiki")
            art = fetch_extract(url) if url else None
            if art and art["extract"]:
                p["description"] = _clean_extract(art["extract"])
                p.update(description_source="wikipedia", description_lang=lang, description_url=url,
                         description_title=art["title"], description_license="CC BY-SA 4.0 · Wikipedia contributors")
                if "wikipedia" not in p["sources"]:
                    p["sources"].append("wikipedia")
                n += 1
                break
    log.info("wikipedia extracts via sitelinks: %d", n)


def apply_quarantine(pois: list[dict]) -> list[dict]:
    """Drop records reviewed as wrong (data/quarantine_pipeline.json: id + reason); idea from the team's quality_review.md."""
    from app.paths import DATA_DIR
    qf = DATA_DIR / "quarantine_pipeline.json"  # data/quarantine.json is the team catalogue's review file
    if not qf.exists():
        return pois
    bad = {q["id"]: q["reason"] for q in json.loads(qf.read_text())}
    kept = [p for p in pois if p["id"] not in bad]
    log.info("quarantine: dropped %d records", len(pois) - len(kept))
    return kept


def _clean_extract(s: str) -> str:
    s = re.sub(r"\s*\([^()]*\)", "", s)  # drop parenthesised pronunciations/dates
    s = re.sub(r"\s+", " ", s).strip()
    return s[:420].rsplit(" ", 1)[0] + "…" if len(s) > 420 else s


ANCHOR_CATS = {"landmark", "museum", "theatre", "mall", "park", "garden", "event_venue", "zoo_aquarium",
               "theme_park", "monument", "viewpoint"}


def nearest_anchor(p: dict, anchors: Grid) -> tuple[float, dict] | None:
    """A well-known place within 500 m (closer and more famous wins), to say where a small place is."""
    best = None
    for d, a in anchors.near(p["lat"], p["lon"], 500):
        if a is p or fold(a["name"]) == fold(p["name"]) or (a["name"] in (p.get("name") or "")):
            continue
        score = d * (1.4 - a["popularity"])
        if best is None or score < best[0]:
            best = (score, d, a)
    return best[1:] if best else None


def template_description(p: dict, near: tuple[float, dict] | None = None) -> str:
    """Factual text built only from tags and geometry (no invented details)."""
    parts = [label(p["category"], "ru")]
    cz = cuisine_ru(p.get("cuisine"))
    if cz:
        parts.append("Кухня: " + ", ".join(cz))
    fl = feature_labels(p.get("features", {}), "ru")
    if fl:
        parts.append("Удобства: " + ", ".join(fl))
    if p.get("wikidata_desc"):
        parts.append(p["wikidata_desc"][:1].upper() + p["wikidata_desc"][1:])
    if near:
        d, a = near
        parts.append(f"Рядом с «{a['name']}»" if d < 80 else f"В {int(round(d / 50) * 50)} м от «{a['name']}»")
    if p.get("address"):
        parts.append("Адрес: " + p["address"])
    return ". ".join(parts) + "."


def compute_popularity(pois: list[dict]) -> None:
    info = ("opening_hours", "website", "phone", "cuisine", "wikidata", "address", "instagram")
    for p in pois:
        wd = math.log1p(p.get("sitelinks", 0)) / math.log1p(40)
        wp = math.log1p(p.get("pageviews", 0)) / math.log1p(12000)
        rich = (sum(bool(p.get(k)) for k in info) + len(p.get("features", {}))) / (len(info) + 4)
        p["popularity"] = round(min(1.0, 0.45 * wd + 0.35 * wp + 0.2 * min(rich, 1.0)), 3)


OV_GAZ_KINDS = {"train_station": ("station", 0.6), "airport": ("airport", 0.6), "stadium_arena": ("stadium", 0.5),
               "college_university": ("university", 0.5), "government_office": ("government", 0.65)}


def merge_directory_layer(pois: list[dict], directory: list[dict]) -> list[dict]:
    from pipeline.team_data import merge_directory
    return merge_directory(pois, directory) if directory else pois


def build_gazetteer(pois: list[dict], context: list[dict], overture: list[dict] | None = None,
                    anchors: list[dict] | None = None) -> list[dict]:
    entries = list(anchors or [])  # hotels, universities, hospitals... (team big-data layer): origins only
    for o in overture or []:
        kind, min_conf = OV_GAZ_KINDS.get(o.get("basic_category") or "", (None, 1))
        if kind and o.get("name") and (o.get("confidence") or 0) >= min_conf:
            entries.append({"name": o["name"], "lat": round(o["lat"], 6), "lon": round(o["lon"], 6), "kind": kind,
                            "keys": [fold(o["name"])]})
    for p in pois:
        if p["name_auto"]:
            continue
        names = {p["name"], *p["names"].values()}
        entries.append({"name": p["name"], "lat": p["lat"], "lon": p["lon"], "kind": "poi", "poi_id": p["id"],
                        "category": p["category"], "keys": sorted({fold(n) for n in names if n})})
    for e in context:
        t, ll = e.get("tags", {}), element_latlon(e)
        if not ll or not t.get("name") or (t.get("highway") and t.get("highway") != "pedestrian"):
            continue
        b = t.get("building", "")
        kind = ("station" if t.get("railway") else "airport" if t.get("aeroway")
                else "stadium" if t.get("leisure") == "stadium" or b == "stadium"
                else "university" if t.get("amenity") == "university" or b == "university"
                else "government" if b == "government" or t.get("office") == "government"
                else "boulevard" if t.get("highway") == "pedestrian" else "place")
        names = {t["name"], t.get("name:ru"), t.get("name:kk"), t.get("name:en")}
        entries.append({"name": t["name"], "lat": round(ll[0], 6), "lon": round(ll[1], 6), "kind": kind,
                        "keys": sorted({fold(n) for n in names if n})})
    # curated landmarks resolved against the collected names
    resolved = 0
    for lm in LANDMARKS:
        best = None
        for en in entries:
            for k in en["keys"]:
                for a in lm["aliases"]:
                    a = fold(a)
                    sc = 3 if k == a else 2 if k.startswith(a) or a.startswith(k) and len(k) > 4 else 1 if a in k else 0
                    if not sc:
                        continue
                    if lm.get("prefer"):
                        if en["kind"] == lm["prefer"] or en.get("category") in lm.get("prefer_cats", ()):
                            sc += 2
                        else:
                            continue  # strict: a café called "Astana Arena" is not the stadium
                    if en.get("category") in ("landmark", "museum", "mall", "worship", "park", "theatre", "zoo_aquarium", "monument"):
                        sc += 0.5
                    elif en.get("category") in ("cafe", "restaurant", "fast_food", "bar", "karaoke", "hookah", "sweets"):
                        sc -= 1
                    if lm.get("fallback") and hav(en["lat"], en["lon"], *lm["fallback"]) > 2500:
                        sc = 0
                    if sc > 0 and (best is None or sc > best[0]):
                        best = (sc, en)
        if best:
            lat, lon = best[1]["lat"], best[1]["lon"]
        elif lm.get("fallback"):
            lat, lon = lm["fallback"]
        else:
            log.warning("landmark not resolved: %s", lm["key"])
            continue
        resolved += 1
        entries.append({"name": lm["label"], "lat": lat, "lon": lon, "kind": "landmark", "landmark_key": lm["key"],
                        "keys": sorted({fold(a) for a in lm["aliases"]} | {fold(lm["label"])})})
    log.info("gazetteer: %d entries, %d/%d curated landmarks resolved", len(entries), resolved, len(LANDMARKS))
    return entries


def boundary_checker():
    poly = prep(shape(json.loads(BOUNDARY_FILE.read_text())["geometry"]))
    return lambda lat, lon: poly.contains(Point(lon, lat))


def build(osm_pois: dict, osm_context: dict, river: list, wd_items: list[dict], wp: dict[str, list[dict]],
          overture: list[dict] | None = None, gaz_extra: list[dict] | None = None) -> dict:
    inside = boundary_checker()
    pois = dedupe(osm_to_pois(osm_pois["elements"], inside))
    label_unnamed(pois, osm_context["elements"])
    if overture:  # before Wikidata, so Overture-only places (e.g. Nur Alem) also get descriptions/popularity
        from pipeline.overture import merge_overture
        pois = merge_overture(pois, overture)
    pois = merge_wikidata(pois, wd_items, inside)
    merge_wikipedia(pois, wp)
    add_sitelink_extracts(pois, wd_items)
    pois = apply_quarantine(pois)
    from pipeline import team_data
    team = team_data.load()
    pois = merge_directory_layer(pois, team["directory"])
    compute_popularity(pois)
    anchors = Grid([p for p in pois if not p["name_auto"] and p["category"] in ANCHOR_CATS and p["popularity"] >= 0.2])
    for p in pois:
        near = nearest_anchor(p, anchors)
        if near:  # kept as data too, so the API can phrase it in kk/en
            p["near"] = {"name": near[1]["name"], "m": int(round(near[0] / 50) * 50)}
        if not p.get("description"):
            p["description"] = template_description(p, near)
            p["description_source"] = "template"
        p.pop("osm_tags_count", None)
    from pipeline.photos import attach_photos
    attach_photos(pois, {f"osm:{e['type'][0]}{e['id']}": e["tags"]["wikimedia_commons"]
                         for e in osm_pois["elements"] if e.get("tags", {}).get("wikimedia_commons")})
    pois.sort(key=lambda p: p["id"])
    write_jsonl(POIS_FILE, pois)
    gaz = build_gazetteer(pois, osm_context["elements"] + (gaz_extra or []), overture,
                          team_data.gazetteer_anchors(team["anchors"]))
    GAZETTEER_FILE.write_text(json.dumps(gaz, ensure_ascii=False, separators=(",", ":")))
    RIVER_FILE.write_text(json.dumps(river))
    import hashlib
    old = json.loads(MANIFEST_FILE.read_text()) if MANIFEST_FILE.exists() else {}
    manifest = {
        "built_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "pois_sha": hashlib.sha1("\n".join(p["id"] + p["name"] for p in pois).encode()).hexdigest()[:16],
        "poi_count": len(pois),
        "by_category": dict(Counter(p["category"] for p in pois).most_common()),
        "by_source": dict(Counter(s for p in pois for s in p["sources"])),
        "with_opening_hours": sum(bool(p["opening_hours"]) for p in pois),
        "description_sources": dict(Counter(p["description_source"] for p in pois)),
        "sources": {
            "osm": "© OpenStreetMap contributors, ODbL 1.0 (Overpass API, Astana admin boundary R3087155)",
            "wikidata": "Wikidata, CC0",
            "wikipedia": "Wikipedia (ru/en) intro extracts, CC BY-SA 4.0 — linked per POI",
            **({"overture": "Overture Maps Foundation Places, CDLA-Permissive-2.0 / Apache-2.0 / CC0 per record"} if overture else {}),
            **({"team_bigdata": "Team collection (branch big-data, Aslan, 2026-10-18): CityPass Astana and mall directory "
                                "facts with links (licence not specified - facts only), anchors from OSM ODbL / Overture"}
               if team["directory"] or team["anchors"] else {}),
        },
    }
    for k in ("embedding_model", "embedding_dim", "embedding_pois_sha"):  # keep embeddings valid if POIs unchanged
        if k in old:
            manifest[k] = old[k]
    MANIFEST_FILE.write_text(json.dumps(manifest, ensure_ascii=False, indent=1))
    log.info("built %d POIs: %s", len(pois), manifest["by_category"])
    return manifest


_ = CATEGORIES  # keep import for type reference in docs

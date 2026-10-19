"""Wikidata (landmarks, multilingual labels, sitelinks) and Wikipedia (short descriptions, pageviews)."""
from __future__ import annotations

import logging
import re

from ayat_backend.pipeline.common import get_json

log = logging.getLogger("pipeline.wiki")

CENTER = (51.1605, 71.4460)

SPARQL = """
SELECT ?item ?coord ?sitelinks ?image ?website
       (SAMPLE(?lru) AS ?label_ru) (SAMPLE(?lkk) AS ?label_kk) (SAMPLE(?len) AS ?label_en)
       (SAMPLE(?dru) AS ?desc_ru) (SAMPLE(?den) AS ?desc_en)
       (GROUP_CONCAT(DISTINCT ?classLabel; separator="|") AS ?classes)
       (SAMPLE(?ruwiki) AS ?ruwiki) (SAMPLE(?enwiki) AS ?enwiki) (SAMPLE(?kkwiki) AS ?kkwiki)
WHERE {
  SERVICE wikibase:around {
    ?item wdt:P625 ?coord .
    bd:serviceParam wikibase:center "Point(71.4460 51.1605)"^^geo:wktLiteral ; wikibase:radius "25" .
  }
  ?item wikibase:sitelinks ?sitelinks .
  OPTIONAL { ?item wdt:P31 ?class . ?class rdfs:label ?classLabel FILTER(LANG(?classLabel)="en") }
  OPTIONAL { ?item rdfs:label ?lru FILTER(LANG(?lru)="ru") }
  OPTIONAL { ?item rdfs:label ?lkk FILTER(LANG(?lkk)="kk") }
  OPTIONAL { ?item rdfs:label ?len FILTER(LANG(?len)="en") }
  OPTIONAL { ?item schema:description ?dru FILTER(LANG(?dru)="ru") }
  OPTIONAL { ?item schema:description ?den FILTER(LANG(?den)="en") }
  OPTIONAL { ?item wdt:P18 ?image }
  OPTIONAL { ?item wdt:P856 ?website }
  OPTIONAL { ?ruwiki schema:about ?item ; schema:isPartOf <https://ru.wikipedia.org/> }
  OPTIONAL { ?enwiki schema:about ?item ; schema:isPartOf <https://en.wikipedia.org/> }
  OPTIONAL { ?kkwiki schema:about ?item ; schema:isPartOf <https://kk.wikipedia.org/> }
}
GROUP BY ?item ?coord ?sitelinks ?image ?website
"""

# Wikidata P31 classes (English labels) that make an item a walkable destination
POI_CLASS_PATTERNS = [
    (r"\bart museum|museum\b", "museum"), (r"\bgallery\b", "gallery"),
    (r"opera house|theatre|theater|concert hall|circus", "theatre"),
    (r"mosque|cathedral|church|synagogue|temple|place of worship|orthodox", "worship"),
    (r"\bpark\b|botanical garden|urban park", "park"), (r"\bgarden\b|square\b|boulevard", "garden"),
    (r"monument|memorial|statue|sculpture|obelisk", "monument"),
    (r"observation tower|tower\b|landmark|palace|tourist attraction|pyramid", "landmark"),
    (r"aquarium|oceanarium|\bzoo\b", "zoo_aquarium"), (r"shopping (center|centre|mall)", "mall"),
    (r"library", "library"), (r"planetarium", "museum"), (r"fountain", "artwork"),
]
NON_POI = r"district|neighbourhood|human settlement|street|company|business|university|school|bank|hospital|airport|railway station|stadium|residential|office building|hotel|ministry|government|embassy|bridge|road"


def fetch_wikidata() -> list[dict]:
    data = get_json("https://query.wikidata.org/sparql", params={"query": SPARQL, "format": "json"},
                    kind="wikidata", max_age_h=24 * 7, timeout=120)
    out = []
    for b in data["results"]["bindings"]:
        v = {k: x["value"] for k, x in b.items()}
        m = re.match(r"Point\(([-\d.]+) ([-\d.]+)\)", v.get("coord", ""))
        if not m:
            continue
        out.append({
            "qid": v["item"].rsplit("/", 1)[-1], "lat": float(m.group(2)), "lon": float(m.group(1)),
            "sitelinks": int(v.get("sitelinks", 0)), "image": v.get("image"), "website": v.get("website"),
            "label_ru": v.get("label_ru"), "label_kk": v.get("label_kk"), "label_en": v.get("label_en"),
            "desc_ru": v.get("desc_ru"), "desc_en": v.get("desc_en"),
            "classes": [c for c in v.get("classes", "").split("|") if c],
            "ruwiki": v.get("ruwiki"), "enwiki": v.get("enwiki"), "kkwiki": v.get("kkwiki"),
        })
    log.info("wikidata items: %d", len(out))
    return out


def wikidata_category(classes: list[str]) -> str | None:
    s = " | ".join(classes).lower()
    if not s or re.search(NON_POI, s) and not re.search(r"museum|theatre|mosque|cathedral|monument|park", s):
        return None
    for pat, cat in POI_CLASS_PATTERNS:
        if re.search(pat, s):
            return cat
    return None


def _geosearch(lang: str) -> dict[int, dict]:
    """Articles with coordinates around Astana: 7 circles of 10 km (API max radius)."""
    pages: dict[int, dict] = {}
    lat0, lon0 = CENTER
    for dlat, dlon in [(0, 0), (0.08, 0.11), (0.08, -0.11), (-0.08, 0.11), (-0.08, -0.11), (0, 0.2), (-0.13, 0.03)]:
        d = get_json(f"https://{lang}.wikipedia.org/w/api.php", params={
            "action": "query", "list": "geosearch", "gscoord": f"{lat0 + dlat}|{lon0 + dlon}",
            "gsradius": 10000, "gslimit": 500, "format": "json", "formatversion": 2},
            kind=f"wp_{lang}", max_age_h=24 * 7, delay=0.3)
        for p in d.get("query", {}).get("geosearch", []):
            pages[p["pageid"]] = {"pageid": p["pageid"], "title": p["title"], "lat": p["lat"], "lon": p["lon"]}
    return pages


def fetch_wikipedia(lang: str) -> list[dict]:
    pages = _geosearch(lang)
    ids = list(pages)
    for i in range(0, len(ids), 20):
        batch = ids[i:i + 20]
        d = get_json(f"https://{lang}.wikipedia.org/w/api.php", params={
            "action": "query", "pageids": "|".join(map(str, batch)), "prop": "extracts|pageprops|pageviews",
            "exintro": 1, "explaintext": 1, "exsentences": 3, "exlimit": 20, "ppprop": "wikibase_item",
            "pvipdays": 60, "format": "json", "formatversion": 2}, kind=f"wp_{lang}", max_age_h=24 * 7, delay=0.3)
        for p in d.get("query", {}).get("pages", []):
            rec = pages.get(p["pageid"])
            if not rec:
                continue
            rec["extract"] = (p.get("extract") or "").strip()
            rec["qid"] = (p.get("pageprops") or {}).get("wikibase_item")
            rec["pageviews"] = sum(v or 0 for v in (p.get("pageviews") or {}).values())
            rec["url"] = f"https://{lang}.wikipedia.org/?curid={p['pageid']}"
    out = list(pages.values())
    log.info("wikipedia %s articles: %d", lang, len(out))
    return out


def fetch_extract(url: str) -> dict | None:
    """Intro extract of one Wikipedia article given its URL (any language edition)."""
    from urllib.parse import unquote, urlparse
    u = urlparse(url)
    lang = u.netloc.split(".")[0]
    title = unquote(u.path.rsplit("/", 1)[-1])
    d = get_json(f"https://{lang}.wikipedia.org/w/api.php", params={
        "action": "query", "prop": "extracts", "titles": title, "exintro": 1, "explaintext": 1, "exsentences": 3,
        "redirects": 1, "format": "json", "formatversion": 2}, kind=f"wp_{lang}", max_age_h=24 * 7, delay=0.3)
    pages = d.get("query", {}).get("pages", [])
    if not pages or pages[0].get("missing"):
        return None
    return {"title": pages[0].get("title", title), "extract": (pages[0].get("extract") or "").strip()}

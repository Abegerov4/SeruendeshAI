"""Real photos for well-known places: Wikimedia Commons files linked from Wikidata (P18), OSM
(`wikimedia_commons`) or the place's Wikipedia article (page image). Each photo keeps its author,
licence and file page so the card can credit it; places without one get a category cover in the UI.
"""
from __future__ import annotations

import html
import logging
import re
from urllib.parse import unquote, urlparse

from pipeline.common import get_json

log = logging.getLogger("pipeline.photos")

COMMONS_API = "https://commons.wikimedia.org/w/api.php"
FREE = re.compile(r"^(cc0|cc[ -]by|public domain|pd|attribution|gfdl|fal)", re.I)


def _file_name(ref: str | None) -> str | None:
    """'http://commons.wikimedia.org/wiki/Special:FilePath/Kazakh%20Eli.jpg' or 'File:X.jpg' -> 'X.jpg'."""
    if not ref:
        return None
    name = unquote(urlparse(ref).path.rsplit("/", 1)[-1]) if ref.startswith("http") else ref
    name = re.sub(r"^(File|Файл|Category):", "", name).strip()
    return name if re.search(r"\.(jpe?g|png|webp|tiff?)$", name, re.I) else None


def _page_image(url: str) -> str | None:
    """Lead image of a Wikipedia article (prop=pageimages), as a Commons file name."""
    u = urlparse(url)
    lang = u.netloc.split(".")[0]
    params = {"action": "query", "prop": "pageprops", "ppprop": "page_image_free|page_image", "redirects": 1,
              "format": "json", "formatversion": 2}
    m = re.search(r"curid=(\d+)", u.query)
    params.update({"pageids": m[1]} if m else {"titles": unquote(u.path.rsplit("/", 1)[-1])})
    pages = get_json(f"https://{lang}.wikipedia.org/w/api.php", params=params, kind=f"wp_{lang}", max_age_h=24 * 30,
                     delay=0.2).get("query", {}).get("pages", [])
    pp = pages[0].get("pageprops", {}) if pages else {}
    return pp.get("page_image_free") or pp.get("page_image")  # a local non-free file is not on Commons -> dropped later


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", s or ""))).strip()


def commons_info(files: list[str]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for i in range(0, len(files), 40):
        batch = files[i:i + 40]
        d = get_json(COMMONS_API, params={
            "action": "query", "titles": "|".join("File:" + f for f in batch), "prop": "imageinfo",
            "iiprop": "url|extmetadata|size", "iiurlwidth": 960, "format": "json", "formatversion": 2},
            kind="commons", max_age_h=24 * 30, delay=0.3)
        norm = {n["to"]: n["from"] for n in d.get("query", {}).get("normalized", [])}
        for pg in d.get("query", {}).get("pages", []):
            ii = (pg.get("imageinfo") or [None])[0]
            if not ii:
                continue
            meta = ii.get("extmetadata", {})
            lic = _clean(meta.get("LicenseShortName", {}).get("value", ""))
            if not FREE.search(lic):
                continue
            title = norm.get(pg["title"], pg["title"]).split(":", 1)[1]
            out[title] = {"url": ii.get("thumburl") or ii["url"], "width": ii.get("thumbwidth"), "height": ii.get("thumbheight"),
                          "author": _clean(meta.get("Artist", {}).get("value", ""))[:120] or "Wikimedia Commons",
                          "license": lic, "page": ii.get("descriptionurl"), "source": "Wikimedia Commons"}
    return out


def wikidata_images(qids: list[str]) -> dict[str, str]:
    """P18 (image) of Wikidata items that came from OSM tags rather than our SPARQL query."""
    out = {}
    for i in range(0, len(qids), 50):
        d = get_json("https://www.wikidata.org/w/api.php", params={
            "action": "wbgetentities", "ids": "|".join(qids[i:i + 50]), "props": "claims", "format": "json"},
            kind="wikidata_api", max_age_h=24 * 30, delay=0.3)
        for qid, ent in d.get("entities", {}).items():
            claims = ent.get("claims", {})
            if claims.get("P18"):
                out[qid] = claims["P18"][0]["mainsnak"].get("datavalue", {}).get("value")
            elif claims.get("P373"):  # no lead image: first photo of the item's own Commons category
                out[qid] = _category_photo(claims["P373"][0]["mainsnak"].get("datavalue", {}).get("value"))
    return out


def _category_photo(category: str | None) -> str | None:
    if not category:
        return None
    d = get_json(COMMONS_API, params={"action": "query", "list": "categorymembers", "cmtitle": "Category:" + category,
                                      "cmtype": "file", "cmlimit": 20, "format": "json", "formatversion": 2},
                 kind="commons", max_age_h=24 * 30, delay=0.3)
    files = [m["title"].split(":", 1)[1] for m in d.get("query", {}).get("categorymembers", [])]
    # the file name must mention the place itself: categories also hold banknotes, maps and neighbours
    words = {w for w in re.findall(r"[a-zа-яё]{4,}", category.lower())} - GENERIC_WORDS
    return next((f for f in files if re.search(r"\.jpe?g$", f, re.I) and any(w in f.lower() for w in words)), None)


GENERIC_WORDS = {"astana", "kazakhstan", "park", "sultan", "national", "museum", "mosque", "monument", "palace", "republic",
                 "square", "center", "centre", "theatre", "theater", "state", "city", "church", "cathedral", "building",
                 "astana's", "interior", "exterior", "view"}
# people, money, stamps and maps are not a photo of the place
NOT_A_PLACE = re.compile(r"stamp|banknote|tenge|coin|\bmap\b|logo|flag|medvedev|putin|minnikhanov|nazarbayev|tokayev|"
                         r"wikimedian|staff|meeting|visit|minister|\bpresident\b|signing|delegat|portrait", re.I)


def attach_photos(pois: list[dict], osm_commons: dict[str, str] | None = None) -> None:
    want: dict[str, str] = {}  # poi id -> Commons file
    try:
        wd = wikidata_images(sorted({p["wikidata"] for p in pois if p.get("wikidata") and not p.get("image")}))
    except RuntimeError as e:
        log.warning("wikidata images: %s", e)
        wd = {}
    for p in pois:
        f = (_file_name(p.get("image")) or _file_name(wd.get(p.get("wikidata") or "")) or
             _file_name((osm_commons or {}).get(p["id"])))
        if not f and p.get("description_source") == "wikipedia" and p.get("description_url"):
            try:
                f = _file_name(_page_image(p["description_url"]))
            except RuntimeError as e:
                log.warning("page image: %s", e)
        if f:
            want[p["id"]] = f
    try:
        info = commons_info(sorted(set(want.values())))
    except RuntimeError as e:
        log.warning("commons unavailable: %s", e)
        return
    n = 0
    for p in pois:
        ph = info.get(want.get(p["id"], ""))
        if ph and (ph.get("width") or 0) >= 400 and not NOT_A_PLACE.search(want[p["id"]]):
            p["photo"] = ph
            n += 1
    log.info("photos with attribution: %d (of %d candidates)", n, len(want))

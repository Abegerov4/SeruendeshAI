"""More real pictures for the cards, collected automatically (`python -m pipeline.place_images`).

1. Wikimedia Commons files photographed next to a sight whose file title names the place (geosearch + name
   match across Cyrillic/Latin spellings), with author and licence — the same free-licence filter as photos.py.
2. The picture a venue publishes for link previews on its own website (og:image / twitter:image), credited to
   the site; logos, icons and small or oddly shaped images are rejected after reading the image header.

Writes data/processed/photos_extra.json {poi_id: photo}. The API attaches it only to places without a photo, so
curated Wikidata/Wikipedia photos always win. Nothing is re-hosted: cards link to the original file or site.
"""
from __future__ import annotations

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from difflib import SequenceMatcher
from html import unescape
from urllib.parse import urljoin, urlparse

from app.paths import PROCESSED_DIR
from pipeline.common import cache_path, get_json, session
from pipeline.photos import COMMONS_API, NOT_A_PLACE, commons_info

log = logging.getLogger("pipeline.place_images")

POIS_FILE = PROCESSED_DIR / "pois.jsonl"
OUT_FILE = PROCESSED_DIR / "photos_extra.json"

# how far from the point a photo of the place may be taken
SIGHT_RADIUS = {"monument": 60, "artwork": 60, "landmark": 150, "worship": 120, "museum": 120, "theatre": 120,
                "arts_centre": 120, "viewpoint": 120, "library": 100, "mall": 160, "zoo_aquarium": 150, "theme_park": 200,
                "water_park": 200, "park": 220, "garden": 220, "event_venue": 150}
GENERIC = {"парк", "сквер", "сад", "памятник", "монумент", "музей", "мечеть", "церковь", "собор", "центр", "торговый",
           "развлекательный", "театр", "площадь", "бульвар", "аллея", "имени", "казахстан", "астана", "республики",
           "национальный", "государственный", "дворец", "park", "square", "garden", "monument", "museum", "mosque",
           "church", "center", "centre", "mall", "theatre", "theater", "astana", "kazakhstan", "national", "state",
           "palace", "саябағы", "ескерткіші", "мешіті", "орталығы", "алаңы"}
# a view taken from the place is not a picture of it («Вид с монумента Байтерек», «Вид на Астану от Хан Шатыр»)
VIEW_FROM = re.compile(r"\bвид\s+(?:с|со|из)\b|\bот\s|\bview\s+from\b|\bfrom\s+the\b|\bpanorama\b|\binterior\b|\bвнутри\b|интерьер", re.I)
SOCIAL = re.compile(r"instagram\.|facebook\.|vk\.com|wa\.me|t\.me|telegram|2gis\.|linktr\.ee|taplink|youtube\.|tiktok\.|"
                    r"google\.|yandex\.|whatsapp|ok\.ru|twitter\.|x\.com", re.I)
LOCAL_SITE = re.compile(r"\.kz$|astana", re.I)
BAD_IMAGE = re.compile(r"logo|favicon|icon|sprite|placeholder|default|blank|\.svg|\.ico|avatar|banner-?ad", re.I)

_TR = str.maketrans({"а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh", "з": "z", "и": "i",
                     "й": "i", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t",
                     "у": "u", "ф": "f", "х": "h", "ц": "c", "ч": "ch", "ш": "sh", "щ": "sh", "ъ": "", "ы": "i", "ь": "",
                     "э": "e", "ю": "yu", "я": "ya", "ә": "a", "ғ": "g", "қ": "k", "ң": "n", "ө": "o", "ұ": "u", "ү": "u",
                     "һ": "h", "і": "i"})


def _norm(word: str) -> str:
    """One spelling for Cyrillic and Latin variants: Байтерек ~ Bayterek ~ Baiterek, Хан ~ Khan."""
    w = word.lower().translate(_TR)
    for a, b in (("kh", "h"), ("y", "i"), ("q", "k"), ("w", "v"), ("x", "h"), ("j", "zh"), ("ts", "c"), ("ee", "e")):
        w = w.replace(a, b)
    return w


def _tokens(text: str) -> set[str]:
    return {_norm(t) for t in re.findall(r"[a-zа-яёәғқңөұүһі]{4,}", text.lower()) if t not in GENERIC}


def _names(p: dict) -> set[str]:
    out = _tokens(p["name"])
    for n in (p.get("names") or {}).values():
        out |= _tokens(n or "")
    return out


def _title_match(names: set[str], title: str) -> float:
    words = _tokens(re.sub(r"[_\-.,()]", " ", title.rsplit(".", 1)[0]))
    best = 0.0
    for n in names:
        for w in words:
            best = max(best, 1.0 if n == w else SequenceMatcher(None, n, w).ratio() if min(len(n), len(w)) >= 5 else 0.0)
    return best


def commons_near(p: dict) -> str | None:
    """A Commons file taken near the place whose title names it."""
    names = _names(p) or {"-"}
    d = get_json(COMMONS_API, params={"action": "query", "list": "geosearch", "gscoord": f"{p['lat']}|{p['lon']}",
                                      "gsradius": SIGHT_RADIUS[p["category"]], "gsnamespace": 6, "gslimit": 50,
                                      "format": "json", "formatversion": 2},
                 kind="commons_geo", max_age_h=24 * 30, delay=0.2)
    best = None
    for f in d.get("query", {}).get("geosearch", []):
        title = f["title"].split(":", 1)[1]
        if not re.search(r"\.jpe?g$", title, re.I) or NOT_A_PLACE.search(title) or VIEW_FROM.search(title):
            continue
        score = _title_match(names, title)
        if score >= 0.82 and (best is None or (score, -f["dist"]) > best[0]):
            best = ((score, -f["dist"]), title)
        elif score < 0.82 and f["dist"] <= min(80, SIGHT_RADIUS[p["category"]]) and best is None:
            best = ((0.0, -f["dist"]), title)  # the nearest photo, kept only if the vision check sees this kind of place
    return best[1] if best else None


def _image_size(url: str) -> tuple[int, int] | None:
    from PIL import ImageFile
    try:
        with session.get(url, timeout=8, stream=True, headers={"Range": "bytes=0-131071"}) as r:
            if r.status_code >= 400 or "image" not in r.headers.get("content-type", "image"):
                return None
            parser = ImageFile.Parser()
            for chunk in r.iter_content(8192):
                parser.feed(chunk)
                if parser.image:
                    return parser.image.size
    except Exception:
        return None
    return None


def _page_images(html: str) -> list[str]:
    """Preview image first (og:image, twitter:image, image_src, JSON-LD), then photos uploaded into the page."""
    out = []
    for tag in re.findall(r'<meta[^>]+(?:property|name)=["\'](?:og:image(?::url|:secure_url)?|twitter:image(?::src)?)["\'][^>]*>', html, re.I):
        if m := re.search(r'content=["\']([^"\']+)', tag):
            out.append(m.group(1))
    out += re.findall(r'<link[^>]+rel=["\']image_src["\'][^>]+href=["\']([^"\']+)', html, re.I)
    out += re.findall(r'"image"\s*:\s*"(https?://[^"]+)"', html)
    out += [u for u in re.findall(r'<img[^>]+src=["\']([^"\']+\.(?:jpe?g|webp)(?:\?[^"\']*)?)["\']', html, re.I)
            if re.search(r"upload|storage|media|photo|gallery|wp-content|images?/", u, re.I)]
    return list(dict.fromkeys(out))


def site_image(p: dict) -> dict | None:
    """The venue's own preview picture (og:image), if it is a real photo-sized image."""
    site = (p.get("website") or "").strip()
    if not site.startswith("http") or SOCIAL.search(site):
        return None
    cache = cache_path("og_image", site)
    if cache.exists():
        found = json.loads(cache.read_text())
    else:
        found = None
        try:
            r = session.get(site, timeout=8, headers={"Accept": "text/html"})
            html = r.text[:400_000] if r.ok and "html" in r.headers.get("content-type", "") else ""
            for img in _page_images(html)[:4]:
                img = urljoin(r.url, unescape(img).strip())
                size = None if BAD_IMAGE.search(img) or not img.startswith("http") else _image_size(img)
                if size and size[0] >= 400 and size[1] >= 250 and 0.6 <= size[0] / size[1] <= 2.4:
                    found = {"url": img, "width": size[0], "height": size[1]}
                    break
        except Exception as exc:  # unreachable sites simply keep the category cover
            log.debug("og:image %s: %s", site, type(exc).__name__)
        cache.write_text(json.dumps(found))
    if not found:
        return None
    domain = urlparse(site).netloc.removeprefix("www.")
    return {**found, "author": domain, "license": "© " + domain, "page": site, "source": "website"}


def _one_venue(points: list[tuple[float, float]]) -> bool:
    """Records within ~300 m are one venue mapped twice; farther apart they are branches of a chain."""
    lat0, lon0 = points[0]
    return all(abs(lat - lat0) < 0.0027 and abs(lon - lon0) < 0.0043 for lat, lon in points)


def collect(pois: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    sights = [p for p in pois if not p.get("photo") and not p.get("name_auto") and p["category"] in SIGHT_RADIUS]
    files: dict[str, str] = {}
    for p in sights:
        try:
            if f := commons_near(p):
                files[p["id"]] = f
        except RuntimeError as exc:
            log.warning("commons geosearch: %s", exc)
    info = commons_info(sorted(set(files.values()))) if files else {}
    for pid, f in files.items():
        if (ph := info.get(f)) and (ph.get("width") or 0) >= 400:
            out[pid] = ph
    log.info("commons near the place: %d of %d sights", len(out), len(sights))
    venues = [p for p in pois if not p.get("photo") and p["id"] not in out and p.get("website")]
    with ThreadPoolExecutor(max_workers=12) as pool:
        for p, ph in zip(venues, pool.map(site_image, venues)):
            if ph:
                out[p["id"]] = ph
    # Astana only, one place per picture: a picture used by several places is a chain or group banner that may
    # come from another city; a site outside .kz (a foreign chain) cannot show an Astana branch either
    users: dict[str, list] = {}
    for p in venues:
        if (ph := out.get(p["id"])) and ph["source"] == "website":
            users.setdefault(ph["url"], []).append((p["lat"], p["lon"]))
    for p in venues:
        if (ph := out.get(p["id"])) and ph["source"] == "website" and (
                not _one_venue(users[ph["url"]]) or not LOCAL_SITE.search(urlparse(ph["page"]).netloc)):
            out.pop(p["id"])
    log.info("site preview images: %d of %d venues with a website", sum(1 for v in out.values() if v["source"] == "website"), len(venues))
    return out


VISION_PROMPT = """You check photos for place cards of a city guide. Given the place name and type, decide what the image shows.
kind: exterior (the building/monument/park itself), interior (inside a venue: hall, tables, shop floor), food (dishes or drinks
as served), logo (logo, text, flat graphic), ad (advertisement, app screenshot, promo banner), people (a person or group is
the subject), blank (empty, black, unreadable), unrelated (another place, a street, an animal, stock objects).
fits: true only if a visitor would accept it as a picture of THIS kind of place (exterior/interior; food only for cafés,
restaurants, bars, sweets). Be strict."""


def verify(out: dict[str, dict], pois_by_id: dict[str, dict]) -> dict[str, dict]:
    """Keep only pictures a vision model accepts as the place itself (not a logo, an ad, a person, a banner)."""
    import os
    from typing import Literal

    from openai import OpenAI
    from pydantic import BaseModel

    from app.config import get_settings

    class Verdict(BaseModel):
        kind: Literal["exterior", "interior", "food", "logo", "ad", "people", "blank", "unrelated"]
        fits: bool

    s = get_settings()
    key = s.openai_api_key or os.getenv("OPENAI_API_KEY", "")
    if not key:
        log.warning("no OpenAI key: photos are not verified")
        return out
    client = OpenAI(api_key=key, timeout=40)

    def check(item):
        pid, ph = item
        p = pois_by_id[pid]
        cache = cache_path("photo_verdict", ph["url"])
        if cache.exists():
            return pid, json.loads(cache.read_text())
        try:
            r = client.responses.parse(model=s.llm_parse_model, store=False, reasoning={"effort": "none"}, text_format=Verdict, input=[
                {"role": "system", "content": VISION_PROMPT},
                {"role": "user", "content": [{"type": "input_text", "text": f"Place: {p['name']} ({p['category']})"},
                                             {"type": "input_image", "image_url": ph["url"], "detail": "low"}]}])
            v = r.output_parsed.model_dump()
        except Exception as exc:  # the model could not fetch or read it: not shown
            v = {"kind": "blank", "fits": False, "error": type(exc).__name__}
        cache.write_text(json.dumps(v))
        return pid, v

    food = {"cafe", "restaurant", "bar", "fast_food", "sweets", "hookah"}
    kept = {}
    with ThreadPoolExecutor(max_workers=6) as pool:
        for pid, v in pool.map(check, list(out.items())):
            cat = pois_by_id[pid]["category"]
            if v.get("fits") and (v["kind"] in ("exterior", "interior") or (v["kind"] == "food" and cat in food)):
                kept[pid] = out[pid]
    log.info("vision check kept %d of %d photos", len(kept), len(out))
    return kept


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    pois = [json.loads(line) for line in POIS_FILE.open(encoding="utf-8") if line.strip()]
    out = verify(collect(pois), {p["id"]: p for p in pois})
    OUT_FILE.write_text(json.dumps(out, ensure_ascii=False, indent=0))
    log.info("wrote %s: %d photos (before: %d places had one)", OUT_FILE.name, len(out), sum(1 for p in pois if p.get("photo")))


if __name__ == "__main__":
    main()

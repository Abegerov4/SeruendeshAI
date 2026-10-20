"""Local events from Ticketon and Sxodim (schema.org JSON-LD already embedded in their pages).

Both sites allow crawling in robots.txt; Sxodim requires an attribution link. We crawl
politely (1 req/s, honest UA), keep only facts + link, and refresh every few hours.
Venue coordinates come from matching the venue to our POI dataset (Ticketon reuses a
placeholder point for many venues, so its own coordinates are a last resort).
"""
from __future__ import annotations

import datetime as dt
import hashlib
import http.cookiejar
import json
import logging
import re
import time
import urllib.request

from rapidfuzz import fuzz

from app.paths import EVENTS_FILE, POIS_FILE, RAW_DIR
from app.textnorm import match_key
from pipeline.common import USER_AGENT, write_jsonl

log = logging.getLogger("pipeline.events")
DL = RAW_DIR / "events_html"
PLACEHOLDER = (51.129547, 71.443112)
TICKETON_LISTINGS = ["astana", "astana/theatres", "astana/museums", "astana/entertainment", "astana/concerts",
                     "astana/children", "astana/stand-up", "astana/exhibitions", "astana/shows", "astana/sports",
                     "astana/knowledge-skills"]

_cj = http.cookiejar.CookieJar()  # Ticketon sits behind a Queue-it waiting room: cookies + redirects pass it
_op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(_cj))
_op.addheaders = [("User-Agent", USER_AGENT), ("Accept-Language", "ru")]


def _fetch(url: str, max_age_h: float = 6) -> str:
    DL.mkdir(parents=True, exist_ok=True)
    p = DL / (hashlib.md5(url.encode()).hexdigest()[:14] + ".html")
    if p.exists() and time.time() - p.stat().st_mtime < max_age_h * 3600:
        return p.read_text(encoding="utf-8", errors="replace")
    time.sleep(1.0)
    with _op.open(url, timeout=30) as r:
        html = r.read().decode("utf-8", errors="replace")
    p.write_text(html, encoding="utf-8")
    return html


def _jsonld(html: str) -> list[dict]:
    out = []
    for block in re.findall(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', html, re.S):
        try:
            d = json.loads(block)
        except ValueError:
            continue
        out.extend(d if isinstance(d, list) else [d])
    return out


def _first(x):
    return (x[0] if x else {}) if isinstance(x, list) else (x or {})


def _norm(d: dict, source: str, url: str | None, extra: dict | None = None) -> dict:
    loc, off = _first(d.get("location")), _first(d.get("offers"))
    addr = loc.get("address") or {}
    if isinstance(addr, str):
        addr = {"streetAddress": addr}
    subs = d.get("subEvent") or []
    sessions = []
    for s in subs[:40]:
        so = _first(s.get("offers"))
        if "SoldOut" not in str(so.get("availability", "")) and s.get("startDate"):
            sessions.append(s["startDate"])
    if not subs and d.get("startDate"):
        sessions = [d["startDate"]]
    geo = loc.get("geo") or {}
    rec = {
        "source": source, "url": d.get("url") or url, "type": str(d.get("@type", "Event")),
        "title": re.sub(r"\s+", " ", (d.get("name") or "")).strip(), "venue": (loc.get("name") or "").strip(),
        "address": addr.get("streetAddress"), "start": d.get("startDate"), "end": d.get("endDate"),
        "sessions": sessions, "price_from": off.get("price") or off.get("lowPrice"), "currency": off.get("priceCurrency"),
        "availability": str(off.get("availability") or "").rsplit("/", 1)[-1],
        "lat": float(geo["latitude"]) if geo.get("latitude") else None,
        "lon": float(geo["longitude"]) if geo.get("longitude") else None,
    }
    rec.update(extra or {})
    return rec


def collect_ticketon(max_events: int = 400) -> list[dict]:
    urls: set[str] = set()
    for page in TICKETON_LISTINGS:
        try:
            urls |= set(re.findall(r"([a-z-]+/event/tckt2-[a-z0-9-]+)", _fetch("https://ticketon.kz/" + page)))
        except Exception as e:
            log.warning("ticketon listing %s failed: %s", page, e)
    urls = sorted(u for u in urls if not u.startswith("cinema/"))
    recs, place_geo = [], {}
    for u in urls[:max_events]:
        try:
            html = _fetch("https://ticketon.kz/" + u)
        except Exception as e:
            log.warning("ticketon %s: %s", u, e)
            continue
        place = (re.findall(r"/place/([a-z0-9-]+)", html) or [None])[0]
        for d in _jsonld(html):
            if not str(d.get("@type", "")).endswith("Event"):
                continue
            rec = _norm(d, "ticketon", "https://ticketon.kz/" + u, {"category": u.split("/")[0]})
            if rec["lat"] is None and place:
                if place not in place_geo:
                    try:
                        pj = [x for x in _jsonld(_fetch("https://ticketon.kz/place/" + place, 72)) if x.get("geo")]
                        place_geo[place] = pj[0]["geo"] if pj else None
                    except Exception:
                        place_geo[place] = None
                g = place_geo[place]
                if g:
                    rec["lat"], rec["lon"] = float(g["latitude"]), float(g["longitude"])
            recs.append(rec)
    log.info("ticketon events: %d", len(recs))
    return recs


def collect_sxodim(pages: int = 6) -> list[dict]:
    recs = []
    for page in range(1, pages + 1):
        try:
            html = _fetch(f"https://sxodim.com/astana/afisha?page={page}")
        except Exception as e:
            log.warning("sxodim page %d: %s", page, e)
            break
        evs = [d for d in _jsonld(html) if str(d.get("@type", "")).endswith("Event")]
        if not evs:
            break
        for d in evs:
            rec = _norm(d, "sxodim", None, {"attribution": "Sxodim.com"})
            if rec["address"] and "," in rec["address"]:  # venue is the address prefix on Sxodim
                rec["venue"], rec["address"] = [x.strip() for x in rec["address"].split(",", 1)]
            recs.append(rec)
    log.info("sxodim events: %d", len(recs))
    return recs


def match_event_venue(event: dict, pois: list[dict]) -> dict:
    """Resolve only a unique branch; retain source values and ranked evidence."""
    from rag.geo import haversine_m
    result = dict(event)
    for key in ("venue", "lat", "lon", "address"):
        result.setdefault("source_" + key, event.get(key))
    result["matcher_version"] = "venue-identity-v2"
    result.pop("poi_id", None)
    key = match_key(event.get("venue") or "")
    address = match_key(event.get("address") or "")
    located = event.get("lat") is not None and event.get("lon") is not None
    candidates = []
    for poi in pois:
        distance = haversine_m(event["lat"], event["lon"], poi["lat"], poi["lon"]) if located else None
        if distance is not None and distance > 400:
            continue
        score = fuzz.token_set_ratio(key, match_key(poi["name"])) if key else 0
        if score < 88:
            continue
        same_address = bool(address and address == match_key(poi.get("address") or ""))
        candidates.append({"id": poi["id"], "score": score, "distance_m": distance,
                           "address_match": same_address, "name": poi["name"],
                           "address": poi.get("address")})
    candidates.sort(key=lambda p: (-p["address_match"], -p["score"], p["id"]))
    result["match_candidates"] = candidates
    best = candidates[0] if candidates else None
    address_winners = [p for p in candidates if p["address_match"]]
    if len(address_winners) == 1:
        best = address_winners[0]
        method = "name_and_exact_address"
    elif best and (len(candidates) == 1 or best["score"] - candidates[1]["score"] >= 8):
        method = "unique_name_near_coordinates" if located else "unique_name"
    else:
        result.update(match_status="ambiguous" if candidates else "unmatched", match_method=None)
        return result
    poi = next(p for p in pois if p["id"] == best["id"])
    result.update(poi_id=poi["id"], lat=poi["lat"], lon=poi["lon"], venue=poi["name"],
                  match_status="matched", match_method=method)
    return result


def _match_near_building(event: dict, pois: list[dict], radius_m: float = 80) -> dict:
    """After geocoding: the one catalogue place next to that building whose name (in any of our languages) is
    like the venue's, e.g. «Национальный музей РК» = «Qazaqstan Respýblıkasynyń Ulttyq muzeıi» / its RU name."""
    from rag.geo import haversine_m
    key = match_key(event.get("venue") or "")
    if not key:
        return event
    near = []
    for poi in pois:
        if haversine_m(event["lat"], event["lon"], poi["lat"], poi["lon"]) > radius_m:
            continue
        names = [poi["name"], *((poi.get("names") or {}).values())]
        score = max(fuzz.token_set_ratio(key, match_key(n)) for n in names if n)
        if score >= 60:
            near.append((score, poi))
    if len(near) != 1:
        return event
    poi = near[0][1]
    return {**event, "poi_id": poi["id"], "lat": poi["lat"], "lon": poi["lon"], "venue": poi["name"],
            "match_status": "matched", "match_method": "geocoded_building_and_name"}


def _geocode_address(address: str | None) -> tuple[float, float] | None:
    """A venue that is not in our catalogue: its street address through OSM Nominatim (cached, 1 req/s, Astana only).
    A bare «г. Астана» or a meeting point without a house number is not an address."""
    if not address or not re.search(r"\d", address) or len(address) < 6:
        return None
    from pipeline.common import get_json
    q = re.sub(r"\s*(?:[A-ZА-Я]\d+(?:\.\d+)?|этаж.*|\d+\s*этаж.*)$", "", address).strip(" ,")
    try:
        res = get_json("https://nominatim.openstreetmap.org/search", kind="nominatim", max_age_h=24 * 30, delay=1.1,
                       params={"q": f"{q}, Астана", "format": "jsonv2", "limit": 1, "countrycodes": "kz",
                               "viewbox": "71.20,51.30,71.75,50.95", "bounded": 1})
    except Exception as exc:
        log.info("geocode %s failed: %s", address, type(exc).__name__)
        return None
    # only a building or a venue: a street, district or city answer can be kilometres off
    if res and res[0].get("addresstype") in ("building", "amenity", "shop", "tourism", "office", "leisure", "house") \
            and 50.85 < float(res[0]["lat"]) < 51.36 and 71.2 < float(res[0]["lon"]) < 71.8:
        return round(float(res[0]["lat"]), 6), round(float(res[0]["lon"]), 6)
    return None


def collect_events() -> dict:
    pois = [json.loads(line) for line in POIS_FILE.open(encoding="utf-8")]
    named = [p for p in pois if not p["name_auto"]]
    events = collect_ticketon() + collect_sxodim()
    now = dt.datetime.now(dt.timezone(dt.timedelta(hours=5)))
    out, unresolved, seen = [], [], set()
    for e in events:
        if not e["title"]:
            continue
        for key in ("venue", "lat", "lon", "address"):
            e.setdefault("source_" + key, e.get(key))
        if e["lat"] is not None and (round(e["lat"], 6), round(e["lon"], 6)) == PLACEHOLDER:
            e["lat"] = e["lon"] = None
        e = match_event_venue(e, named)
        if e["match_status"] != "matched":
            unresolved.append(e)
            if e["lat"] is None and (g := _geocode_address(e.get("address"))):  # the venue's address, not a guess
                e["lat"], e["lon"], e["coords_source"] = g[0], g[1], "nominatim"
                e = _match_near_building(e, named)
        if e["lat"] is None or not (50.85 < e["lat"] < 51.36 and 71.2 < e["lon"] < 71.8):
            continue
        end = e.get("end") or (e["sessions"][-1] if e["sessions"] else e.get("start"))
        try:
            if end and dt.datetime.fromisoformat(end.replace("Z", "+00:00")).astimezone(now.tzinfo) < now - dt.timedelta(hours=3):
                continue
        except ValueError:
            pass
        k = (match_key(e["title"]), e.get("poi_id") or e["venue"], (e["start"] or "")[:10])
        if k in seen:
            continue
        seen.add(k)
        e["id"] = "ev:" + hashlib.sha1(("|".join(map(str, k))).encode()).hexdigest()[:10]
        e["fetched_at"] = now.isoformat(timespec="minutes")
        out.append(e)
    write_jsonl(EVENTS_FILE, out)
    review_path = EVENTS_FILE.with_name("events_unresolved.json")
    review_path.write_text(json.dumps(unresolved, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    info = {"events": len(out), "matched_to_poi": sum(1 for e in out if e.get("poi_id"))}
    log.info("events saved: %s", info)
    return info

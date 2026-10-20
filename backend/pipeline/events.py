"""Archive-preserving Astana event collection from Ticketon and Sxodim.

Use ordinary, rate-limited requests with an honest user agent. Source access errors
are reported rather than bypassed. POI matching is optional for the feed; only a
uniquely resolved venue supplies trusted map coordinates.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import html as html_lib
import http.cookiejar
import json
import logging
import math
import os
import re
import tempfile
import time
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

from rapidfuzz import fuzz

from app.paths import EVENTS_FILE, POIS_FILE, RAW_DIR
from app.textnorm import match_key, same_name
from pipeline.common import USER_AGENT

log = logging.getLogger("pipeline.events")
DL = RAW_DIR / "events_html"
PLACEHOLDER = (51.129547, 71.443112)
TICKETON_LISTINGS = ["astana", "astana/theatres", "astana/museums", "astana/entertainment", "astana/concerts",
                     "astana/children", "astana/stand-up", "astana/exhibitions"]

_cj = http.cookiejar.CookieJar()
_op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(_cj))
_op.addheaders = [("User-Agent", USER_AGENT), ("Accept-Language", "ru")]


class SourceEvents(list):
    """Keep a list-compatible collector result and its source access diagnostics."""

    def __init__(self):
        super().__init__()
        self.errors: list[str] = []

    def failure(self, label: str, error: Exception | str) -> None:
        message = f"{label}: {error}"
        self.errors.append(message)
        log.warning("%s", message)


def _fetch(url: str, max_age_h: float = 0.25) -> str:
    DL.mkdir(parents=True, exist_ok=True)
    p = DL / (hashlib.md5(url.encode()).hexdigest()[:14] + ".html")
    if p.exists() and time.time() - p.stat().st_mtime < max_age_h * 3600:
        return p.read_text(encoding="utf-8", errors="replace")
    time.sleep(1.0)
    with _op.open(url, timeout=30) as r:
        html = r.read().decode("utf-8", errors="replace")
    p.write_text(html, encoding="utf-8")
    return html


class _PageData(HTMLParser):
    def __init__(self, html: str):
        super().__init__(convert_charrefs=False)
        self.scripts: list[str] = []
        self.meta: dict[str, str] = {}
        self.canonical: str | None = None
        self.publication: list[str] = []
        self._publication_depth = 0
        self._script: list[str] | None = None
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "link" and "canonical" in (attrs.get("rel") or "").lower().split():
            self.canonical = attrs.get("href")
        if "publication" in (attrs.get("class") or "").split() or self._publication_depth:
            if tag not in {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}:
                self._publication_depth += 1
        if tag == "script" and (attrs.get("type") or "").lower() == "application/ld+json":
            self._script = []
        if tag == "meta":
            key = (attrs.get("property") or attrs.get("name") or "").lower()
            if key and attrs.get("content"):
                self.meta[key] = html_lib.unescape(attrs["content"])

    def handle_data(self, data):
        if self._script is not None:
            self._script.append(data)
        if self._publication_depth:
            self.publication.append(data)

    def handle_endtag(self, tag):
        if self._publication_depth:
            self._publication_depth -= 1
        if tag == "script" and self._script is not None:
            self.scripts.append("".join(self._script))
            self._script = None


def _jsonld(html: str) -> list[dict]:
    """Flatten graph/list wrappers, keeping subEvent sessions on their parent."""
    out = []

    def visit(node):
        if isinstance(node, list):
            for child in node:
                visit(child)
        elif isinstance(node, dict):
            if node.get("@type") or node.get("geo"):
                out.append(node)
            for key, child in node.items():
                if key not in ("subEvent", "subEvents", "superEvent"):
                    visit(child)

    for block in _PageData(html).scripts:
        try:
            visit(json.loads(block))
        except ValueError:
            continue
    return out


def _first(value):
    return (value[0] if value else {}) if isinstance(value, list) else (value or {})


def _event_type(value) -> str | None:
    for kind in value if isinstance(value, list) else [value]:
        name = str(kind or "").rsplit("/", 1)[-1]
        if name.endswith("Event"):
            return name
    return None


def _text(value) -> str | None:
    if not isinstance(value, str):
        return None
    return re.sub(r"\s+", " ", html_lib.unescape(re.sub(r"<[^>]+>", " ", value))).strip() or None


def _image(value, base_url: str | None) -> str | None:
    for item in value if isinstance(value, list) else [value]:
        if isinstance(item, dict):
            item = item.get("contentUrl") or item.get("url")
        if isinstance(item, str) and item.strip():
            absolute = urllib.parse.urljoin(base_url or "", item.strip())
            if urllib.parse.urlsplit(absolute).scheme in ("http", "https"):
                return absolute
    return None


def _coordinate(value, limit: float) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) and abs(number) <= limit else None
    except (TypeError, ValueError):
        return None


def _norm(d: dict, source: str, url: str | None, extra: dict | None = None) -> dict:
    loc, off = _first(d.get("location")), _first(d.get("offers"))
    loc = loc if isinstance(loc, dict) else {"name": loc}
    off = off if isinstance(off, dict) else {}
    addr = loc.get("address") or {}
    if isinstance(addr, str):
        addr = {"streetAddress": addr}
    addr = addr if isinstance(addr, dict) else {}
    explicit_sessions = any(field in d and d[field] is not None for field in ("subEvent", "subEvents"))
    subs = d.get("subEvent") or d.get("subEvents") or []
    subs = [subs] if isinstance(subs, dict) else subs
    sessions = []
    for sub in subs:
        if not isinstance(sub, dict):
            continue
        offer = _first(sub.get("offers"))
        offer = offer if isinstance(offer, dict) else {}
        if "SoldOut" not in str(offer.get("availability", "")) and sub.get("startDate"):
            sessions.append(sub["startDate"])
    if not explicit_sessions and d.get("startDate"):
        sessions = [d["startDate"]]
    geo = loc.get("geo") or {}
    geo = geo if isinstance(geo, dict) else {}
    price = off.get("price")
    if price is None or price == "":
        price = off.get("lowPrice")
    event_url = d.get("url") or url
    rec = {
        "source": source, "url": event_url, "source_id": d.get("@id"),
        "type": _event_type(d.get("@type")) or "Event",
        "title": _text(d.get("name")) or "", "venue": _text(loc.get("name")) or "",
        "address": _text(addr.get("streetAddress")), "source_city": _text(addr.get("addressLocality")),
        "start": d.get("startDate"), "end": d.get("endDate"),
        "schedule_kind": "sessions" if explicit_sessions else "continuous",
        "sessions": sorted(set(sessions)), "price_from": price, "currency": off.get("priceCurrency"),
        "availability": str(off.get("availability") or "").rsplit("/", 1)[-1],
        "lat": _coordinate(geo.get("latitude"), 90), "lon": _coordinate(geo.get("longitude"), 180),
        "description": _text(d.get("description")), "image_url": _image(d.get("image"), event_url),
        "published_at": d.get("datePublished"),
    }
    rec.update(extra or {})
    return rec


def _page_metadata(html: str, url: str) -> dict:
    meta = _PageData(html).meta
    return {"published_at": meta.get("article:published_time") or meta.get("datepublished") or meta.get("pubdate"),
            "description": _text(meta.get("description") or meta.get("og:description")),
            "image_url": _image(meta.get("og:image"), url)}


def _publication_date(value) -> str | None:
    """Validate explicit ISO source dates without adding precision or a timezone."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            dt.date.fromisoformat(value)
        elif re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:[0-5]\d)?", value):
            dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        else:
            return None
    except ValueError:
        return None
    return value


def _sxodim_event_url(value) -> str | None:
    """Only official Astana event pages may supply publication metadata."""
    if not isinstance(value, str):
        return None
    try:
        parts = urllib.parse.urlsplit(value.strip())
    except ValueError:
        return None
    if parts.scheme != "https" or parts.netloc.lower() != "sxodim.com" or not re.fullmatch(r"/astana/event/[a-z0-9-]+/?", parts.path):
        return None
    return "https://sxodim.com" + parts.path.rstrip("/")


def _sxodim_publication(html: str, url: str) -> str | None:
    """Read matching Article metadata, then an explicit visible publication day."""
    expected = _sxodim_event_url(url)
    if expected is None:
        return None
    page = _PageData(html)
    if page.canonical and _sxodim_event_url(page.canonical) != expected:
        raise ValueError("Event detail canonical URL does not match requested event")
    invalid = False
    for doc in _jsonld(html):
        kinds = doc.get("@type")
        if not any(str(kind).rsplit("/", 1)[-1] == "Article" for kind in (kinds if isinstance(kinds, list) else [kinds])):
            continue
        identity = doc.get("mainEntityOfPage") or doc.get("url") or doc.get("@id")
        if isinstance(identity, dict):
            identity = identity.get("@id") or identity.get("url")
        if _sxodim_event_url(identity) != expected or doc.get("datePublished") is None:
            continue
        publication = _publication_date(doc["datePublished"])
        if publication:
            return publication
        invalid = True
    for key in ("article:published_time", "datepublished", "pubdate"):
        if key in page.meta:
            publication = _publication_date(page.meta[key])
            if publication:
                return publication
            invalid = True
    visible = re.search(r"Дата\s+публикации\s*:\s*(\d{2}\.\d{2}\.\d{4})", " ".join(page.publication), re.I)
    if visible:
        try:
            return dt.datetime.strptime(visible[1], "%d.%m.%Y").date().isoformat()
        except ValueError:
            invalid = True
    if invalid:
        raise ValueError("Invalid explicit publication date on event detail page")
    return None


def collect_ticketon(max_events: int = 120) -> list[dict]:
    urls: set[str] = set()
    recs = SourceEvents()
    for page in TICKETON_LISTINGS:
        try:
            urls |= set(re.findall(r"([a-z-]+/event/tckt2-[a-z0-9-]+)", _fetch("https://ticketon.kz/" + page)))
        except Exception as error:
            recs.failure("ticketon listing " + page, error)
    urls = sorted(u for u in urls if not u.startswith("cinema/"))
    if not urls and not recs.errors:
        recs.failure("ticketon listings", "No supported event links found; source markup may have changed")
    place_geo = {}
    for path in urls[:max_events]:
        url = "https://ticketon.kz/" + path
        try:
            html = _fetch(url)
            docs = [d for d in _jsonld(html) if _event_type(d.get("@type"))]
            if not docs:
                recs.failure(url, "No Event JSON-LD found")
            place = (re.findall(r"/place/([a-z0-9-]+)", html) or [None])[0]
            meta = _page_metadata(html, url)
            for doc in docs:
                rec = _norm(doc, "ticketon", url, {"category": path.split("/")[0]})
                for key, value in meta.items():
                    if not rec.get(key) and value:
                        rec[key] = value
                if rec["lat"] is None and place:
                    if place not in place_geo:
                        try:
                            nodes = [d for d in _jsonld(_fetch("https://ticketon.kz/place/" + place, 72)) if d.get("geo")]
                            place_geo[place] = nodes[0]["geo"] if nodes else None
                        except Exception as error:
                            recs.failure("ticketon venue " + place, error)
                            place_geo[place] = None
                    geo = place_geo[place]
                    if isinstance(geo, dict):
                        rec["lat"] = _coordinate(geo.get("latitude"), 90)
                        rec["lon"] = _coordinate(geo.get("longitude"), 180)
                recs.append(rec)
        except Exception as error:
            recs.failure(url, error)
    log.info("ticketon events: %d", len(recs))
    return recs


def collect_sxodim(pages: int = 6) -> list[dict]:
    recs = SourceEvents()
    seen = set()
    publications = {}
    for page in range(1, pages + 1):
        url = f"https://sxodim.com/astana/afisha?page={page}"
        try:
            docs = [d for d in _jsonld(_fetch(url)) if _event_type(d.get("@type"))]
            if not docs:
                if page == 1:
                    recs.failure(url, "No Event JSON-LD found; source may be empty or markup changed")
                break
            added = 0
            for doc in docs:
                rec = _norm(doc, "sxodim", None, {"attribution": "Sxodim.com"})
                if rec["address"] and "," in rec["address"]:
                    rec["venue"], rec["address"] = [x.strip() for x in rec["address"].split(",", 1)]
                key = _identity(rec)
                if key not in seen:
                    seen.add(key)
                    rec["published_at"] = _publication_date(rec.get("published_at"))
                    detail_url = _sxodim_event_url(rec.get("url"))
                    if detail_url and detail_url not in publications:
                        publications[detail_url] = None
                        try:
                            publications[detail_url] = _sxodim_publication(_fetch(detail_url, 72), detail_url)
                        except Exception as error:
                            recs.failure("sxodim publication " + detail_url, error)
                    if publications.get(detail_url):
                        rec["published_at"] = publications[detail_url]
                    recs.append(rec)
                    added += 1
            if not added:
                break
        except Exception as error:
            recs.failure(url, error)
            break
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
        if score < 88 or not same_name(event.get("venue") or "", poi["name"], threshold=88):
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


def _identity(event: dict) -> tuple:
    """A source page identifies a series; exact venue/time facts backstop missing URLs."""
    source = event.get("source") or ""
    url = event.get("url")
    if isinstance(url, str) and url.strip():
        parts = urllib.parse.urlsplit(url.strip())
        return source, "url", urllib.parse.urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), parts.query, ""))
    if event.get("source_id"):
        return source, "source_id", str(event["source_id"])
    return (source, "facts", event.get("title"), event.get("source_venue", event.get("venue")),
            event.get("source_address", event.get("address")), event.get("start"))


def _atomic_json(path: Path, rows, *, jsonl: bool = False) -> None:
    """Replace only a completely serialized file, leaving the previous file on error."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix="." + path.name + ".", delete=False) as stream:
            temporary = Path(stream.name)
            if jsonl:
                for row in rows:
                    stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
            else:
                stream.write(json.dumps(rows, ensure_ascii=False, indent=2) + "\n")
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _schedule_problem(event: dict) -> str | None:
    """Validate occurrence facts without inventing an end or a replacement start."""
    def parse(value, *, end_of_day=False):
        if not isinstance(value, str) or not value.strip():
            return None
        try:
            parsed = dt.datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
            if end_of_day and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value.strip()):
                parsed = parsed.replace(hour=23, minute=59, second=59, microsecond=999999)
            return parsed.replace(tzinfo=dt.timezone(dt.timedelta(hours=5))) if parsed.tzinfo is None else parsed
        except ValueError:
            return None

    start, end = parse(event.get("start")), parse(event.get("end"), end_of_day=True)
    for key, parsed in (("start", start), ("end", end)):
        if event.get(key) not in (None, "") and parsed is None:
            return f"Unparseable {key} date"
    sessions = event.get("sessions") or []
    if not isinstance(sessions, list) or any(parse(value) is None for value in sessions):
        return "Unparseable session dates"
    if start is not None and end is not None and end < start:
        return "End precedes start"
    if event.get("schedule_kind") == "sessions":
        return None if sessions else "No explicit session dates"
    return None if start is not None or sessions else "No parseable occurrence dates"


def collect_events() -> dict:
    """Upsert source records while retaining the existing archive on partial failures."""
    # Read existing data before doing any network work. Corrupt input must never be erased.
    previous = [json.loads(line) for line in EVENTS_FILE.read_text(encoding="utf-8").splitlines() if line.strip()] if EVENTS_FILE.exists() else []
    pois = [json.loads(line) for line in POIS_FILE.read_text(encoding="utf-8").splitlines() if line.strip()]
    named = [poi for poi in pois if not poi.get("name_auto")]
    now = dt.datetime.now(dt.timezone(dt.timedelta(hours=5))).isoformat(timespec="seconds")
    collected, sources = [], {}
    for source, collector in (("ticketon", collect_ticketon), ("sxodim", collect_sxodim)):
        try:
            rows = collector()
            errors = list(getattr(rows, "errors", []))
        except Exception as error:
            log.warning("%s collection failed: %s", source, error)
            rows, errors = [], [str(error)]
        sources[source] = {"status": ("partial" if rows else "failed") if errors else ("ok" if rows else "empty"),
                           "collected": len(rows), "accepted": 0, "errors": errors}
        collected.extend(rows)
    out = list(previous)
    index = {_identity(row): number for number, row in enumerate(out)}
    refreshed = set()
    new_count = rejected = degraded = 0
    for original in collected:
        if not original.get("title"):
            rejected += 1
            continue
        event = dict(original)
        for key in ("venue", "lat", "lon", "address"):
            event.setdefault("source_" + key, event.get(key))
        city = match_key(event.get("source_city") or "")
        if city and city not in {match_key(name) for name in ("Астана", "Astana", "Нур-Султан", "Nur-Sultan")}:
            rejected += 1
            continue
        lat, lon = _coordinate(event.get("lat"), 90), _coordinate(event.get("lon"), 180)
        # Invalid, partial and known placeholder source points cannot constrain venue matching.
        if lat is None or lon is None or (round(lat, 6), round(lon, 6)) == PLACEHOLDER:
            lat = lon = None
        elif not (50.85 < lat < 51.36 and 71.2 < lon < 71.8):
            if city:
                lat = lon = None
            else:
                rejected += 1
                continue
        event.update(lat=lat, lon=lon)
        event = match_event_venue(event, named)
        key = _identity(event)
        number = index.get(key)
        prior = out[number] if number is not None else {}
        schedule_problem = _schedule_problem(event)
        if schedule_problem:
            message = f"{event.get('url') or event.get('title')}: {schedule_problem}"
            source_report = sources.get(event.get("source"))
            if source_report is not None:
                source_report["errors"].append(message)
            log.warning("%s", message)
            if not prior or _schedule_problem(prior):
                rejected += 1
                continue
            degraded += 1
        merged = {**prior, **event}
        if schedule_problem:
            for field in ("start", "end", "sessions", "schedule_kind"):
                if field in prior:
                    merged[field] = prior[field]
                else:
                    merged.pop(field, None)
        # A sparse refresh cannot erase already collected editorial metadata.
        for field in ("description", "image_url", "published_at"):
            if not event.get(field) and prior.get(field):
                merged[field] = prior[field]
        merged["id"] = prior.get("id") or "ev:" + hashlib.sha1(json.dumps(key, ensure_ascii=False).encode()).hexdigest()[:12]
        merged["first_seen_at"] = prior.get("first_seen_at") or prior.get("fetched_at") or now
        merged["fetched_at"] = now
        # A formerly linked venue must be resolved again using current evidence.
        if not event.get("poi_id"):
            merged.pop("poi_id", None)
        if number is None:
            index[key] = len(out)
            out.append(merged)
            new_count += 1
        else:
            out[number] = merged
        refreshed.add(key)
        if event.get("source") in sources:
            sources[event["source"]]["accepted"] += 1
    if refreshed:
        for row in out:
            row["first_seen_at"] = row.get("first_seen_at") or row.get("fetched_at") or now
        _atomic_json(EVENTS_FILE, out, jsonl=True)
    unresolved = [row for row in out if row.get("match_status") in ("unmatched", "ambiguous")]
    _atomic_json(EVENTS_FILE.with_name("events_unresolved.json"), unresolved)
    for source in sources.values():
        if source["errors"]:
            source["status"] = "partial" if source["accepted"] else "failed"
    failed = [source for source in sources.values() if source["errors"]]
    status = "failed" if failed and not refreshed else "partial" if failed else "ok"
    info = {"status": status, "refreshed_at": now, "events": len(out), "new_events": new_count,
            "updated_events": len(refreshed) - new_count,
            "retained_events": sum(_identity(row) not in refreshed for row in previous),
            "rejected_events": rejected, "degraded_events": degraded,
            "matched_to_poi": sum(bool(row.get("poi_id")) for row in out),
            "sources": sources}
    _atomic_json(EVENTS_FILE.with_name("events_refresh.json"), info)
    log.info("events refresh %s: %s", status, info)
    return info

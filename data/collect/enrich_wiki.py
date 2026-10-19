"""Collect Astana Wikimedia places and enrich linked POIs with attributed text.

Only public Wikimedia APIs are used. Discovery is uncapped, with finite SPARQL
pages. A tiled Wikipedia GeoSearch fallback is explicitly incomplete because it
cannot discover entities without Wikipedia coordinates. Wikidata labels and
short entity descriptions are CC0; article extracts carry separate attribution.

References:
https://www.mediawiki.org/wiki/Wikidata_Query_Service/User_Manual
https://www.mediawiki.org/wiki/API:Geosearch
https://www.wikidata.org/w/api.php?action=help&modules=wbgetentities

Usage:
    python -m data.collect.enrich_wiki --raw-dir data/raw/wikimedia
    python -m data.collect.enrich_wiki --input pois.json --output enriched.json
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
import json
import math
import os
from pathlib import Path
import re
import threading
import time
from urllib.parse import quote, unquote, urlparse

import httpx

DEFAULT_BBOX = (50.9, 71.0, 51.4, 71.9)  # south, west, north, east
PAGE_SIZE = 250
REQUEST_INTERVAL = 1.1
LANGUAGES = ("ru", "kk", "en")
USER_AGENT = "SeruendeshAI-POICollector/1.0 (Astana educational open-data research; respectful cached access)"
WIKIDATA_API = "https://www.wikidata.org/w/api.php"
SPARQL_API = "https://query.wikidata.org/sparql"
CATEGORY_CLASSES = {
    "Q33506": "museum", "Q1007870": "gallery", "Q24354": "theatre",
    "Q41253": "cinema", "Q22698": "park", "Q4989906": "monument",
    "Q570116": "attraction", "Q9259": "attraction", "Q16970": "attraction",
    "Q12280": "attraction", "Q483110": "sport", "Q7075": "library",
    "Q11315": "mall", "Q182832": "viewpoint", "Q41176": "other",
}
EXCLUDED_CLASSES = {"Q5", "Q515", "Q56061", "Q123705", "Q82794", "Q4022", "Q34442"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{threading.get_ident()}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


class WikimediaClient:
    """Disk-cached finite-retry HTTP client, with one active request per host."""

    def __init__(self, raw_dir: Path, refresh: bool = False):
        self.raw_dir = Path(raw_dir)
        self.refresh = refresh
        self.client = httpx.Client(headers={"User-Agent": USER_AGENT, "Accept": "application/json"}, timeout=httpx.Timeout(35, connect=10), follow_redirects=True)
        self.requests = 0
        self.cache_hits = 0
        self.errors: list[dict] = []
        self.request_log: list[dict] = []
        self._state_lock = threading.Lock()
        self._host_locks: dict[str, threading.Lock] = {}
        self._last_request: dict[str, float] = {}
        self._failed_hosts: set[str] = set()
        self._response_metadata: dict[str, dict] = {}
        self._entity_cache: dict[str, dict] = {}
        self._entity_metadata: dict[str, dict] = {}
        self._used_entity_metadata: dict[str, dict] = {}
        self._article_cache: dict[tuple, dict] = {}
        self.semantic_entity_hits = 0
        self.semantic_article_hits = 0
        self._cooldown_path = self.raw_dir / "provider_cooldowns.json"
        try:
            self._cooldowns = json.loads(self._cooldown_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self._cooldowns = {}
        # Rebuild a semantic view from successful canonical raw envelopes. An
        # entity/article must remain reusable when a later batch has new peers.
        for cache in sorted((self.raw_dir / "cache").glob("*.json")):
            try:
                self._remember_cache(json.loads(cache.read_text(encoding="utf-8")), cache)
            except (OSError, ValueError, TypeError, KeyError):
                continue

    def close(self):
        self.client.close()

    def _remember_cache(self, envelope: dict, cache: Path):
        url, params, data = envelope.get("url", ""), envelope.get("params", {}), envelope.get("response", {})
        if not isinstance(data, dict) or "error" in data:
            return
        metadata = {"fetched_at": envelope.get("fetched_at"), "raw_cache": cache.relative_to(self.raw_dir).as_posix(), "stale_cache": False}
        if url == WIKIDATA_API and params.get("action") == "wbgetentities":
            props = {value.split("/", 1)[0] for value in str(params.get("props", "")).split("|")}
            if {"labels", "descriptions", "claims", "sitelinks"} <= props:
                with self._state_lock:
                    for key, value in data.get("entities", {}).items():
                        qid = _qid(key)
                        if not qid or not isinstance(value, dict) or "missing" in value:
                            continue
                        if qid not in self._entity_cache or str(metadata.get("fetched_at") or "") >= str(self._entity_metadata[qid].get("fetched_at") or ""):
                            self._entity_cache[qid] = deepcopy(value)
                            self._entity_metadata[qid] = deepcopy(metadata)
        host = urlparse(url).netloc
        language = re.fullmatch(r"([a-z-]+)\.wikipedia\.org", host)
        if language and params.get("action") == "query" and "extracts" in str(params.get("prop", "")).split("|"):
            articles = _parse_article_response(data, language.group(1), str(params.get("titles", "")).split("|"), metadata)
            with self._state_lock:
                for key, value in articles.items():
                    old = self._article_cache.get(key)
                    if old is None or (bool(value.get("text")), str(value.get("fetched_at") or "")) >= (bool(old.get("text")), str(old.get("fetched_at") or "")):
                        self._article_cache[key] = deepcopy(value)

    def cached_entities(self, ids, *, fallback=False) -> dict:
        with self._state_lock:
            found = {qid: deepcopy(self._entity_cache[qid]) for qid in ids if qid in self._entity_cache}
            self.semantic_entity_hits += len(found)
            for qid in found:
                self._used_entity_metadata[qid] = {**self._entity_metadata[qid], "stale_cache": fallback}
        return found

    def cached_articles(self, titles: dict, *, fallback=False) -> dict:
        found = {}
        with self._state_lock:
            for lang, values in titles.items():
                for title in values:
                    value = self._article_cache.get((lang, title.replace("_", " ").strip()))
                    if value is not None:
                        found[(lang, title)] = {**deepcopy(value), "stale_cache": fallback}
            self.semantic_article_hits += len(found)
        return found

    def metadata(self, url: str, params: dict) -> dict:
        key = hashlib.sha256(json.dumps([url, params], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        return deepcopy(self._response_metadata.get(key, {}))

    def get(self, url: str, params: dict) -> dict:
        key = hashlib.sha256(json.dumps([url, params], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        cache = self.raw_dir / "cache" / (key + ".json")
        cached = None
        if cache.exists():
            try:
                cached = json.loads(cache.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                pass
        if cached is not None and not self.refresh:
            self._response_metadata[key] = {"fetched_at": cached.get("fetched_at"), "raw_cache": cache.relative_to(self.raw_dir).as_posix(), "stale_cache": False}
            self._remember_cache(cached, cache)
            with self._state_lock:
                self.cache_hits += 1
                self.request_log.append({"url": url, "params": params, "cache": cache.relative_to(self.raw_dir).as_posix(), "cache_hit": True})
            return cached["response"]
        host = urlparse(url).netloc
        with self._state_lock:
            lock = self._host_locks.setdefault(host, threading.Lock())
        error = None
        with lock:
            if self._cooldowns.get(host, 0) > time.time():
                error = RuntimeError(f"Provider {host} Retry-After window is still active; live request skipped")
            elif host in self._failed_hosts:
                error = RuntimeError(f"Provider {host} already failed in this run; further live requests skipped")
            else:
                for attempt in range(3):
                    delay = REQUEST_INTERVAL - (time.monotonic() - self._last_request.get(host, 0))
                    if delay > 0:
                        time.sleep(delay)
                    try:
                        self._last_request[host] = time.monotonic()
                        with self._state_lock:
                            self.requests += 1
                        response = self.client.get(url, params=params)
                        response.raise_for_status()
                        data = response.json()
                        if not isinstance(data, dict):
                            raise ValueError("Wikimedia response is not an object")
                        if "error" in data:
                            api_error = data["error"]
                            raise RuntimeError(f"MediaWiki API error: {api_error}")
                        envelope = {"url": url, "params": params, "fetched_at": _now(), "response": data}
                        _write_json(cache, envelope)
                        self._response_metadata[key] = {"fetched_at": envelope["fetched_at"], "raw_cache": cache.relative_to(self.raw_dir).as_posix(), "stale_cache": False}
                        self._remember_cache(envelope, cache)
                        with self._state_lock:
                            self.request_log.append({"url": url, "params": params, "cache": cache.relative_to(self.raw_dir).as_posix(), "cache_hit": False})
                        return data
                    except (httpx.HTTPError, ValueError, RuntimeError) as exc:
                        error = exc
                        code = getattr(getattr(exc, "response", None), "status_code", None)
                        retryable = code in (429, 500, 502, 503, 504) or isinstance(exc, httpx.TransportError) or (isinstance(exc, RuntimeError) and "maxlag" in str(exc))
                        retry_after = getattr(getattr(exc, "response", None), "headers", {}).get("Retry-After", "")
                        try:
                            retry_delay = max(2 ** attempt, float(retry_after))
                        except ValueError:
                            try:
                                retry_delay = max(2 ** attempt, parsedate_to_datetime(retry_after).timestamp() - time.time())
                            except (TypeError, ValueError, OverflowError):
                                retry_delay = 60 if code == 429 else 2 ** attempt
                        if code == 429 and "1 req / min" in str(exc):
                            retry_delay = 60
                        if code == 429:
                            self._cooldowns[host] = time.time() + retry_delay
                            _write_json(self._cooldown_path, self._cooldowns)
                        # Long rate-limit windows end this provider's run rather
                        # than sending retries during an announced outage.
                        if retryable and attempt < 2 and retry_delay <= 30:
                            time.sleep(retry_delay)
                            continue
                        self._failed_hosts.add(host)
                        break
        record = {"url": url, "params": params, "error": str(error), "stale_cache_used": cached is not None}
        with self._state_lock:
            self.errors.append(record)
        if cached is not None:
            self._response_metadata[key] = {"fetched_at": cached.get("fetched_at"), "raw_cache": cache.relative_to(self.raw_dir).as_posix(), "stale_cache": True}
            with self._state_lock:
                self.cache_hits += 1
            return cached["response"]
        raise RuntimeError(str(error))

    def report(self) -> dict:
        return {"http_requests": self.requests, "cache_hits": self.cache_hits,
                "semantic_entity_hits": self.semantic_entity_hits, "semantic_article_hits": self.semantic_article_hits,
                "indexed_entities": len(self._entity_cache), "indexed_article_keys": len(self._article_cache),
                "errors": list(self.errors), "requests": list(self.request_log)}


def _chunks(values: list, size: int = 50):
    for start in range(0, len(values), size):
        yield values[start:start + size]


def _qid(value) -> str | None:
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r"(?:https?://(?:www\.)?wikidata\.org/(?:wiki|entity)/|wikidata:)?(Q[1-9][0-9]*)", value.strip())
    return match.group(1) if match else None


def _entities(client: WikimediaClient, ids) -> dict[str, dict]:
    ids = set(filter(None, ids))
    found = {} if client.refresh else client.cached_entities(ids)
    pending = ids if client.refresh else ids - set(found)
    for batch in _chunks(sorted(pending, key=lambda value: int(value[1:]))):
        params = {"action": "wbgetentities", "ids": "|".join(batch), "props": "labels|descriptions|claims|sitelinks/urls", "languages": "ru|kk|en", "format": "json", "formatversion": 2, "maxlag": 5}
        try:
            data = client.get(WIKIDATA_API, params)
            values = {key: value for key, value in data.get("entities", {}).items() if isinstance(value, dict) and "missing" not in value}
            found.update(values)
            for qid in values:
                client._used_entity_metadata[qid] = client.metadata(WIKIDATA_API, params)
        except RuntimeError:
            found.update(client.cached_entities(batch, fallback=True))
    return found


def _claim_values(entity: dict, prop: str) -> list:
    return [statement.get("mainsnak", {}).get("datavalue", {}).get("value") for statement in entity.get("claims", {}).get(prop, []) if statement.get("rank") != "deprecated" and "datavalue" in statement.get("mainsnak", {})]


def _coordinates(entity: dict, bbox: tuple) -> tuple[float, float] | None:
    for value in _claim_values(entity, "P625"):
        if not isinstance(value, dict) or value.get("globe", "http://www.wikidata.org/entity/Q2").rsplit("/", 1)[-1] != "Q2":
            continue
        lat, lon = value.get("latitude"), value.get("longitude")
        if isinstance(lat, (int, float)) and isinstance(lon, (int, float)) and math.isfinite(lat) and math.isfinite(lon) and bbox[0] <= lat <= bbox[2] and bbox[1] <= lon <= bbox[3]:
            return float(lat), float(lon)
    return None


def _label(entity: dict, lang: str) -> str | None:
    text = entity.get("labels", {}).get(lang, {}).get("value")
    return text.strip() if isinstance(text, str) and text.strip() else None


def _descriptions(entity: dict) -> dict:
    return {lang: value["value"] for lang, value in entity.get("descriptions", {}).items() if lang in LANGUAGES and isinstance(value.get("value"), str) and value["value"].strip()}


def _category(entity: dict, discovered_kinds=()) -> str:
    types = {value.get("id") for value in _claim_values(entity, "P31") if isinstance(value, dict)}
    categories = [CATEGORY_CLASSES[kind] for kind in list(discovered_kinds) + sorted(types) if kind in CATEGORY_CLASSES]
    return next((category for category in categories if category != "other"), "other")


def _sparql_query(bbox: tuple, offset: int) -> str:
    south, west, north, east = bbox
    classes = " ".join("wd:" + kind for kind in CATEGORY_CLASSES)
    return f'''SELECT DISTINCT ?item ?coord ?kind WHERE {{
  SERVICE wikibase:box {{ ?item wdt:P625 ?coord .
    bd:serviceParam wikibase:cornerWest "Point({west} {south})"^^geo:wktLiteral .
    bd:serviceParam wikibase:cornerEast "Point({east} {north})"^^geo:wktLiteral . }}
  VALUES ?kind {{ {classes} }}
  ?item wdt:P31/wdt:P279* ?kind .
}} ORDER BY ?item ?kind ?coord LIMIT {PAGE_SIZE} OFFSET {offset}'''


def _discover_sparql(client: WikimediaClient, bbox: tuple, found: dict | None = None) -> tuple[dict, bool]:
    found = found if found is not None else {}
    offset = 0
    seen_pages = set()
    while True:
        data = client.get(SPARQL_API, {"query": _sparql_query(bbox, offset), "format": "json"})
        if "results" not in data:
            raise RuntimeError("SPARQL response is missing results")
        rows = data["results"].get("bindings", [])
        fingerprint = json.dumps(rows, sort_keys=True)
        if rows and fingerprint in seen_pages:
            raise RuntimeError("SPARQL repeated a page; pagination stopped to avoid an infinite request loop")
        seen_pages.add(fingerprint)
        for row in rows:
            qid = _qid(row.get("item", {}).get("value"))
            if qid:
                found.setdefault(qid, set()).add(row.get("kind", {}).get("value", "").rsplit("/", 1)[-1])
        if len(rows) < PAGE_SIZE:
            return found, True
        offset += PAGE_SIZE


def _grid(bbox: tuple):
    south, west, north, east = bbox
    rows, cols = max(1, math.ceil((north - south) / .12)), max(1, math.ceil((east - west) / .18))
    for row in range(rows):
        for col in range(cols):
            yield (south + (north - south) * (row + .5) / rows, west + (east - west) * (col + .5) / cols)


def _geosearch_poi(lang: str, row: dict) -> dict:
    title = row["title"]
    url = f"https://{lang}.wikipedia.org/wiki/" + quote(title.replace(" ", "_"))
    return {"id": f"wikipedia:{lang}:{row['pageid']}", "name": title,
            "name_en": title if lang == "en" else None, "name_kk": title if lang == "kk" else None,
            "lat": row["lat"], "lon": row["lon"], "category": "other", "tags": [],
            "description": None, "description_source": None, "source": "wikipedia",
            "source_url": url, "source_license": "CC-BY-SA-4.0", "wikipedia": f"{lang}:{title}",
            "updated_at": _now()[:10], "source_refs": [{"source": "wikipedia", "id": str(row["pageid"]), "url": url, "license": "CC-BY-SA-4.0", "origin": "wikipedia_geosearch", "language": lang}]}


def _discover_geosearch(client: WikimediaClient, bbox: tuple, report: dict, article_pois: dict | None = None) -> dict:
    titles: dict[str, set] = {lang: set() for lang in LANGUAGES}
    article_pois = article_pois if article_pois is not None else {}
    for lang in LANGUAGES:
        for lat, lon in _grid(bbox):
            try:
                params = {"action": "query", "list": "geosearch", "gscoord": f"{lat:.7f}|{lon:.7f}", "gsradius": 10000, "gslimit": 500, "gsnamespace": 0, "format": "json", "formatversion": 2, "maxlag": 5}
                data = client.get(f"https://{lang}.wikipedia.org/w/api.php", params)
                rows = data.get("query", {}).get("geosearch", [])
                if len(rows) >= 500:
                    report.setdefault("warnings", []).append(f"{lang} geosearch cell saturated at {lat},{lon}; fallback coverage incomplete")
                for row in rows:
                    if bbox[0] <= row.get("lat", -999) <= bbox[2] and bbox[1] <= row.get("lon", -999) <= bbox[3] and row.get("title"):
                        titles[lang].add(row["title"])
                        if row.get("pageid"):
                            article = _geosearch_poi(lang, row)
                            article_pois[article["id"]] = article
            except RuntimeError:
                break  # A blocked language provider is not hit once per tile.
    # Resolve sitelinks on Wikidata itself: this also works when a Wikipedia
    # provider becomes unavailable after returning some GeoSearch tiles.
    found = {}
    for lang, values in titles.items():
        for batch in _chunks(sorted(values)):
            try:
                data = client.get(WIKIDATA_API, {"action": "wbgetentities", "sites": lang + "wiki", "titles": "|".join(batch), "props": "info", "format": "json", "formatversion": 2, "maxlag": 5})
                for key, entity in data.get("entities", {}).items():
                    if "missing" not in entity and (qid := _qid(entity.get("id", key))):
                        found[qid] = set()
            except RuntimeError:
                break
    return found


def _poi(entity: dict, bbox: tuple, kinds=()) -> dict | None:
    qid = _qid(entity.get("id"))
    coord = _coordinates(entity, bbox)
    name = next((_label(entity, lang) for lang in LANGUAGES if _label(entity, lang)), None)
    types = {value.get("id") for value in _claim_values(entity, "P31") if isinstance(value, dict)}
    if not qid or not coord or not name or types.intersection(EXCLUDED_CLASSES):
        return None
    url = f"https://www.wikidata.org/wiki/{qid}"
    website = next((value for value in _claim_values(entity, "P856") if isinstance(value, str) and value.startswith(("http://", "https://"))), None)
    return {
        "id": f"wikidata:{qid}", "name": name, "name_en": _label(entity, "en"), "name_kk": _label(entity, "kk"),
        "lat": coord[0], "lon": coord[1], "category": _category(entity, kinds), "tags": [],
        "description": None, "description_source": None, "wikidata_descriptions": _descriptions(entity),
        "wikidata_ids": [qid], "wikidata_types": sorted(types), "wikidata_sitelinks": entity.get("sitelinks", {}),
        "address": None, "opening_hours": None, "phone": None, "website": website,
        "rating": None, "rating_count": None, "wheelchair": None, "kid_friendly": None,
        "source": "wikidata", "source_url": url, "source_license": "CC0-1.0", "updated_at": _now()[:10],
        "source_refs": [{"source": "wikidata", "id": qid, "url": url, "license": "CC0-1.0", "origin": "wikidata_entity"}],
    }


def collect(raw_dir: Path, bbox: tuple | None = None, refresh: bool = False) -> dict:
    """Discover all returned cultural/landmark entities in south/west/north/east bbox."""
    raw_dir = Path(raw_dir)
    bbox = tuple(bbox or DEFAULT_BBOX)
    if len(bbox) != 4 or not all(math.isfinite(value) for value in bbox) or not (-90 <= bbox[0] < bbox[2] <= 90 and -180 <= bbox[1] < bbox[3] <= 180):
        raise ValueError("bbox must be (south, west, north, east) with increasing finite bounds")
    report = {"source": "wikimedia", "bbox": list(bbox), "started_at": _now(), "complete": False, "method": "wikidata_sparql", "licenses": {"wikidata_entities": "CC0-1.0", "wikipedia_articles": "CC-BY-SA-4.0"}, "limit": None}
    client = WikimediaClient(raw_dir, refresh)
    try:
        found = {}
        article_pois = {}
        try:
            found, complete = _discover_sparql(client, bbox, found)
            report["complete"] = complete
        except RuntimeError as exc:
            report["discovery_error"] = str(exc)
            report["fallback"] = "tiled_wikipedia_geosearch_ru_kk_en"
            report["coverage_note"] = "Incomplete: Wikipedia GeoSearch finds only articles with coordinates, not all Wikidata cultural entities. Full SPARQL discovery unavailable."
            found.update(_discover_geosearch(client, bbox, report, article_pois))
        entities = _entities(client, set(found) | {"Q1520"} if found else set())
        astana = entities.get("Q1520", {})
        report["astana_osm_relation_ids"] = [str(value) for value in _claim_values(astana, "P402") if str(value).isdigit()]
        pois = [poi for qid in sorted(found, key=lambda value: int(value[1:])) if (poi := _poi(entities.get(qid, {}), bbox, sorted(found[qid])))]
        pois.extend(article_pois.values())
        report.update(client.report())
        report.update({"discovered_entities": len(found), "fetched_entities": len(set(entities).intersection(found)), "fallback_article_candidates": len(article_pois), "candidate_count": len(pois), "finished_at": _now()})
        report["complete"] = report["complete"] and not report["errors"] and set(found).issubset(entities)
        # Partial provider failures must not discard other previously acquired records.
        previous = raw_dir / "candidates.json"
        if not report["complete"] and previous.exists():
            old = json.loads(previous.read_text(encoding="utf-8"))
            if isinstance(old, list) and old:
                current = {poi["id"]: poi for poi in pois}
                retained = [poi for poi in old if poi["id"] not in current]
                pois = sorted([*current.values(), *retained], key=lambda poi: poi["id"])
                report["retained_previous_candidates"] = len(retained)
                report["candidate_count"] = len(pois)
        _write_json(previous, pois)
        _write_json(raw_dir / "report.json", report)
        return {"pois": pois, "report": report}
    finally:
        client.close()


def _wiki_link(value: str) -> tuple[str, str] | None:
    if not isinstance(value, str):
        return None
    if value.startswith(("https://", "http://")):
        parsed = urlparse(value)
        match = re.fullmatch(r"([a-z-]+)\.wikipedia\.org", parsed.netloc)
        if match and parsed.path.startswith("/wiki/"):
            return match.group(1), unquote(parsed.path[6:]).replace("_", " ")
    match = re.fullmatch(r"([a-z-]+):(.+)", value.strip())
    return (match.group(1), match.group(2).replace("_", " ")) if match else None


def _references(poi: dict) -> tuple[set, set]:
    if poi.get("skip_wikimedia_enrichment"):
        return set(), set()
    ids, links = set(), set()
    for field in (poi.get("id"), poi.get("wikidata"), poi.get("source_url")):
        if value := _qid(field):
            ids.add(value)
    raw = poi.get("raw_tags") or {}
    for value in str(raw.get("wikidata", "")).split(";"):
        if qid := _qid(value):
            ids.add(qid)
    for value in poi.get("wikidata_ids") or []:
        if qid := _qid(value):
            ids.add(qid)
    for value in (raw.get("wikipedia"), poi.get("wikipedia"), poi.get("source_url")):
        if link := _wiki_link(value):
            links.add(link)
    refs = poi.get("source_refs") or []
    if isinstance(refs, dict):
        refs = list(refs.values())
    for ref in refs:
        values = (ref.get("id"), ref.get("url"), ref.get("source_url"), ref.get("wikidata")) if isinstance(ref, dict) else (ref,)
        for value in values:
            if qid := _qid(value):
                ids.add(qid)
            if link := _wiki_link(value):
                links.add(link)
    for site, value in (poi.get("wikidata_sitelinks") or {}).items():
        lang = site.removesuffix("wiki")
        if lang in LANGUAGES and isinstance(value, dict) and value.get("title"):
            links.add((lang, value["title"]))
    return ids, links


def _intro(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    # Retain verbatim sentences; no invented connective text or factual templates.
    return " ".join(re.split(r"(?<=[.!?])\s+(?=[А-ЯЁA-ZӘҒҚҢӨҰҮҺІ])", text, maxsplit=2)[:2]).strip()


def _parse_article_response(data: dict, lang: str, titles: list, metadata: dict) -> dict:
    """Parse canonical extracts plus API normalization/redirect aliases."""
    query = data.get("query", {})
    pages = query.get("pages", [])
    if isinstance(pages, dict):
        pages = list(pages.values())
    found = {}
    for page in pages:
        if "missing" in page or "invalid" in page or not page.get("title") or page.get("pageprops", {}).get("disambiguation") is not None:
            continue
        title = page["title"]
        url = page.get("fullurl") or f"https://{lang}.wikipedia.org/wiki/" + quote(title.replace(" ", "_"))
        found[(lang, title)] = {"title": title, "text": _intro(page.get("extract", "")), "url": url, "language": lang, "page_id": page.get("pageid"), "wikidata_id": page.get("pageprops", {}).get("wikibase_item"), "origin": "wikipedia_article", "license": "CC-BY-SA-4.0", "license_url": "https://creativecommons.org/licenses/by-sa/4.0/", "attribution": f"Wikipedia contributors, {title}", "history_url": f"https://{lang}.wikipedia.org/w/index.php?title={quote(title.replace(' ', '_'))}&action=history", "revision_id": page.get("lastrevid"), **metadata}
    aliases = {item["from"]: item["to"] for item in query.get("normalized", []) + query.get("redirects", [])}
    for requested in titles:
        current, seen = requested, set()
        while current in aliases and current not in seen:
            seen.add(current)
            current = aliases[current]
        if (lang, current) in found:
            found[(lang, requested)] = {**found[(lang, current)], "requested_title": requested}
    return found



def _article_batch(client: WikimediaClient, lang: str, titles: list) -> dict:
    url = f"https://{lang}.wikipedia.org/w/api.php"
    params = {"action": "query", "prop": "extracts|pageprops|info", "titles": "|".join(titles), "exintro": 1, "explaintext": 1, "exlimit": "max", "inprop": "url", "redirects": 1, "format": "json", "formatversion": 2, "maxlag": 5}
    try:
        data = client.get(url, params)
    except RuntimeError:
        return client.cached_articles({lang: titles}, fallback=True)
    return _parse_article_response(data, lang, titles, client.metadata(url, params))


def _articles(client: WikimediaClient, titles: dict, workers: int) -> dict:
    found = {} if client.refresh else client.cached_articles(titles)
    jobs = [(lang, batch) for lang, values in titles.items()
            for batch in _chunks(sorted(set(value for value in values if client.refresh or (lang, value) not in found)), 20)]
    # At most two provider jobs; client also serializes each language host.
    with ThreadPoolExecutor(max_workers=max(1, min(int(workers), 2))) as executor:
        for result in executor.map(lambda job: _article_batch(client, *job), jobs):
            found.update(result)
    return found


def enrich(pois: list[dict], raw_dir: Path, refresh: bool = False, workers: int = 4) -> dict:
    """Enrich explicit Wikimedia links, preferring Russian then Kazakh/English.

    Original factual descriptions are preserved. Empty or explicitly generated
    descriptions can be replaced by a sourced article intro. Entity descriptions
    stay in wikidata_descriptions, since the shared enum has no Wikidata origin.
    """
    raw_dir = Path(raw_dir)
    client = WikimediaClient(raw_dir, refresh)
    output = deepcopy(pois)
    references = [_references(poi) for poi in output]
    report = {"source": "wikimedia_enrichment", "started_at": _now(), "input_count": len(output), "language_priority": list(LANGUAGES), "entity_description_note": "CC0 Wikidata short descriptions remain separate from Wikipedia article text; they are not attributed to Wikipedia."}
    try:
        entities = _entities(client, {qid for ids, _ in references for qid in ids})
        direct_titles: dict[str, set] = {}
        for _, links in references:
            for lang, title in links:
                if lang in LANGUAGES:
                    direct_titles.setdefault(lang, set()).add(title)
        articles = _articles(client, direct_titles, workers)
        # Resolve OSM wikipedia-only links to Wikidata, then use preferred sitelinks.
        resolved_ids = set()
        for ids, links in references:
            for link in links:
                if qid := _qid(articles.get(link, {}).get("wikidata_id")):
                    ids.add(qid)
                    resolved_ids.add(qid)
        entities.update(_entities(client, resolved_ids - set(entities)))
        for ids, links in references:
            for qid in ids:
                for lang in LANGUAGES:
                    title = entities.get(qid, {}).get("sitelinks", {}).get(lang + "wiki", {}).get("title")
                    if title:
                        links.add((lang, title))
        titles: dict[str, set] = {}
        for _, links in references:
            for lang, title in links:
                if lang in LANGUAGES and (lang, title) not in articles:
                    titles.setdefault(lang, set()).add(title)
        articles.update(_articles(client, titles, workers))
        enriched = article_linked = 0
        for poi, (ids, links) in zip(output, references):
            if ids:
                poi["wikidata_ids"] = sorted(ids, key=lambda value: int(value[1:]))
            for qid in sorted(ids):
                ent = entities.get(qid, {})
                for field, lang in (("name_en", "en"), ("name_kk", "kk")):
                    if not poi.get(field) and _label(ent, lang):
                        poi[field] = _label(ent, lang)
                if _descriptions(ent):
                    poi.setdefault("wikidata_descriptions", {}).update(_descriptions(ent))
                if ent:
                    ref = {"source": "wikidata", "id": qid, "url": f"https://www.wikidata.org/wiki/{qid}", "license": "CC0-1.0", "origin": "wikidata_entity"}
                    refs = poi.setdefault("source_refs", [])
                    if isinstance(refs, list) and not any(isinstance(existing, dict) and existing.get("source") == "wikidata" and existing.get("id") == qid for existing in refs):
                        refs.append(ref)
            choices = [articles[link] for lang in LANGUAGES for link in sorted(links) if link[0] == lang and link in articles and articles[link].get("text")]
            if not choices:
                continue
            article = choices[0]
            article_linked += 1
            poi["wikipedia_attribution"] = {key: value for key, value in article.items() if key != "text"}
            article_ref = {"source": "wikipedia", "id": str(article.get("page_id") or article["title"]), "url": article["url"], "license": article["license"], "origin": "wikipedia_article", "language": article["language"]}
            refs = poi.setdefault("source_refs", [])
            if isinstance(refs, list) and article_ref not in refs:
                refs.append(article_ref)
            if not poi.get("description") or poi.get("description_source") == "llm_generated":
                if poi.get("description"):
                    poi["previous_description"] = {"text": poi["description"], "source": poi.get("description_source")}
                poi["description"] = article["text"]
                poi["description_source"] = "wikipedia"
                poi["description_attribution"] = deepcopy(poi["wikipedia_attribution"])
                poi["description_url"] = article["url"]
                poi["description_license"] = article["license"]
                enriched += 1
        report.update(client.report())
        report.update({"complete": not client.errors, "linked_entity_count": len(entities), "article_linked_pois": article_linked, "descriptions_added": enriched, "output_count": len(output), "finished_at": _now()})
        _write_json(raw_dir / "enrichment_report.json", report)
        return {"pois": output, "report": report}
    finally:
        client.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw/wikimedia"))
    parser.add_argument("--input", type=Path, help="POI JSON list to enrich; omit for spatial discovery")
    parser.add_argument("--output", type=Path, help="Output JSON list")
    parser.add_argument("--bbox", type=float, nargs=4, metavar=("SOUTH", "WEST", "NORTH", "EAST"))
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    result = enrich(json.loads(args.input.read_text(encoding="utf-8")), args.raw_dir, args.refresh, args.workers) if args.input else collect(args.raw_dir, tuple(args.bbox) if args.bbox else None, args.refresh)
    if args.output:
        _write_json(args.output, result["pois"])
    summary = {key: value for key, value in result["report"].items() if key not in ("requests", "errors")}
    summary["errors"] = len(result["report"].get("errors", []))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

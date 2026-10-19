"""Resumable, public-only source audit; evidence candidates never mutate POIs.

Usage: python -m data.catalog_audit --output eval/runs/.../source-audit
The user-requested as-of date and actual acquisition clock are deliberately distinct.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import ipaddress
import json
import math
from pathlib import Path
import re
import socket
import time
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

from bs4 import BeautifulSoup
import httpx

from data.collect.identity import addresses_compatible, name_keys
from data.collect.normalize import _distance

USER_AGENT = "SeruendeshAI-CatalogAudit/1.0 (public factual research; no authentication)"
FOOD = {"cafe", "restaurant", "bar", "nightlife"}
TIMED = FOOD | {"museum", "gallery", "theatre", "cinema", "library", "mall", "coworking", "sport", "attraction", "other"}
BASE_FIELDS = {"name", "lat", "lon", "category", "address", "website", "description", "source_description", "wheelchair", "kid_friendly"}
LOCAL_TYPES = {"LocalBusiness", "Place", "CafeOrCoffeeShop", "Restaurant", "BarOrPub", "NightClub", "Store", "ShoppingCenter", "ShoppingMall", "Museum", "ArtGallery", "MovieTheater", "Library", "Park", "TouristAttraction", "SportsActivityLocation", "FoodEstablishment", "HealthAndBeautyBusiness", "MedicalBusiness", "ProfessionalService", "AutoRepair", "GasStation", "Pharmacy", "Dentist", "Hotel", "LodgingBusiness", "BankOrCreditUnion", "Bakery", "HairSalon", "BeautySalon", "DryCleaningOrLaundry", "ExerciseGym", "PerformingArtsTheater", "GroceryStore", "JewelryStore", "ClothingStore", "ElectronicsStore", "FurnitureStore", "TravelAgency", "RealEstateAgent"}
DOCUMENTED_APIS = {("overpass-api.de", "/api/interpreter"), ("overpass.private.coffee", "/api/interpreter"), ("maps.mail.ru", "/osm/tools/overpass/api/interpreter")}
API_POLICY = "https://wiki.openstreetmap.org/wiki/Overpass_API#Public_Overpass_API_instances"


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def normalize_url(value):
    if not isinstance(value, str) or any(c.isspace() or ord(c) < 32 for c in value):
        raise ValueError("invalid_url")
    p = urlsplit(value)
    host = (p.hostname or "").rstrip(".").lower()
    if p.scheme.lower() not in {"http", "https"} or not host or p.username or p.password:
        raise ValueError("unsafe_scheme_host_or_credentials")
    if p.port not in {None, 80, 443} or (p.port and p.port != {"http": 80, "https": 443}[p.scheme.lower()]):
        raise ValueError("unsafe_port")
    if "." not in host or host.endswith((".local", ".internal", ".localhost", ".lan", ".home", ".test", ".invalid")):
        raise ValueError("internal_hostname")
    try:
        if not ipaddress.ip_address(host).is_global:
            raise ValueError("nonpublic_ip")
    except ValueError as exc:
        if str(exc) == "nonpublic_ip" or ":" in host or re.fullmatch(r"[\d.]+", host):
            raise ValueError("nonpublic_or_invalid_ip") from exc
    if any(re.search(r"^(?:access_token|auth|authorization|password|secret|api_key|apikey|token)$", k, re.I) for k, _ in parse_qsl(p.query)):
        raise ValueError("credential_query")
    host = host.encode("idna").decode("ascii")
    return urlunsplit((p.scheme.lower(), host, p.path or "/", p.query, ""))


def read_jsonl(path):
    if not Path(path).exists():
        return
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            yield json.loads(line)
        except ValueError:
            if i != len(lines) - 1:
                raise ValueError(f"Corrupt nonfinal JSONL line {i + 1}: {path}")


def load_fetch_results(log, cache, targets):
    """Restore requested URLs even for older observations that logged final URLs."""
    result = {}
    for observation in read_jsonl(log):
        url = observation.get("requested_url", observation.get("url"))
        if url in targets:
            result[url] = observation
    for url in targets:
        path = Path(cache) / (hashlib.sha256(url.encode()).hexdigest() + ".json")
        if not path.exists():
            continue
        try:
            cached = json.loads(path.read_text())
        except ValueError:  # A concurrent write is not a completed observation.
            continue
        if cached.get("fetched_at", "") >= result.get(url, {}).get("fetched_at", ""):
            repaired = {**cached, "url": url, "requested_url": url}
            if cached.get("url") != url:
                repaired["audit_metadata_repair"] = "requested_url_restored_from_sha256_cache_key"
            result[url] = repaired
    return result


def _walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) and not isinstance(value, bool) else None
    except (TypeError, ValueError):
        return None


def _address(raw):
    if isinstance(raw, str):
        return raw.strip() or None
    if isinstance(raw, dict):
        # Street address is the branch discriminator; locality is retained in raw.
        return raw.get("streetAddress") or None
    return None


def _hours(value):
    days = {day: short for day, short in zip(("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"), ("Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"))}
    if isinstance(value, dict):
        value = [value]
    if not isinstance(value, list):
        return None
    parts = []
    for entry in value:
        if not isinstance(entry, dict) or entry.get("validFrom") or entry.get("validThrough"):
            return None
        start, end = entry.get("opens"), entry.get("closes")
        if not all(isinstance(t, str) and re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d(?::00)?", t) for t in (start, end)) or start == end:
            return None
        raw_days = entry.get("dayOfWeek", [])
        raw_days = raw_days if isinstance(raw_days, list) else [raw_days]
        day_values = [days.get(str(d).rsplit("/", 1)[-1]) for d in raw_days]
        if not day_values or None in day_values:
            return None
        parts.append(",".join(day_values) + " " + start[:5] + "-" + end[:5])
    return "; ".join(parts) or None


def extract_page(html, url):
    soup = BeautifulSoup(html, "html.parser")
    businesses, public_links, jsonld_errors = [], {}, 0
    for script in soup.find_all("script", type=re.compile(r"^application/ld\+json", re.I)):
        try:
            payload = json.loads(script.string or script.get_text())
        except (ValueError, TypeError):
            jsonld_errors += 1
            continue
        for node in _walk(payload):
            types = node.get("@type", [])
            types = [types] if isinstance(types, str) else types
            if not isinstance(types, list) or not (set(str(t).rsplit("/", 1)[-1] for t in types) & LOCAL_TYPES):
                continue
            name = node.get("name")
            if not isinstance(name, str) or not name.strip():
                continue
            geo = node.get("geo") if isinstance(node.get("geo"), dict) else {}
            facts = {key: node[src] for key, src in (("phone", "telephone"), ("price_range", "priceRange"), ("cuisine", "servesCuisine"), ("accepts_reservations", "acceptsReservations")) if node.get(src) is not None}
            hours = _hours(node.get("openingHoursSpecification"))
            if hours:
                facts["opening_hours"] = hours
            if node.get("openingHours"):
                facts["opening_hours_source_text"] = node["openingHours"]
            rating = node.get("aggregateRating")
            if isinstance(rating, dict):
                value = _number(rating.get("ratingValue"))
                count = _number(rating.get("reviewCount", rating.get("ratingCount")))
                low, high = _number(rating.get("worstRating", 1)), _number(rating.get("bestRating", 5))
                if value is not None and high == 5 and low in {0, 1} and 0 <= value <= 5:
                    facts["rating"] = value
                    if count is not None and count.is_integer() and count >= 0:
                        facts["rating_count"] = int(count)
            for field in ("hasMenu", "menu"):
                values = node.get(field, [])
                values = values if isinstance(values, list) else [values]
                for value in values:
                    value = value.get("url", value.get("@id")) if isinstance(value, dict) else value
                    if isinstance(value, str):
                        try:
                            link = normalize_url(urljoin(url, value))
                            public_links[link] = {"url": link, "kind": "menu", "basis": "jsonld:" + field}
                            facts.setdefault("menu_url", link)
                        except ValueError:
                            pass
            businesses.append({"name": name.strip(), "address": _address(node.get("address")),
                               "lat": _number(geo.get("latitude")), "lon": _number(geo.get("longitude")),
                               "facts": facts, "raw_jsonld": node})
    for anchor in soup.find_all("a", href=True):
        label = anchor.get_text(" ", strip=True)[:150]
        href = anchor.get("href", "")
        if re.search(r"menu|меню|price|прайс|тариф|стоимост", label + " " + href, re.I):
            try:
                link = normalize_url(urljoin(url, href))
                public_links.setdefault(link, {"url": link, "kind": "menu_or_price", "basis": "public_anchor", "label": label})
            except ValueError:
                pass
    title = soup.title.get_text(" ", strip=True)[:300] if soup.title else None
    text = (title or "") + " " + soup.get_text(" ", strip=True)[:100_000]
    flags = []
    if re.search(r"verify you are human|checking your browser|cloudflare.{0,40}challenge|just a moment.{0,40}enable javascript|captcha", text, re.I):
        flags.append("antibot_challenge")
    if re.search(r"онлайн[ -]*казино|игровые автоматы|ставки на спорт|online casino|slots bonus|1xbet|pin.?up casino", text, re.I):
        flags.append("possible_gambling_or_seo_content")
    return {"title": title, "businesses": businesses, "public_links": list(public_links.values())[:100], "jsonld_parse_errors": jsonld_errors, "content_flags": flags}


def extract_source_payload(body, url, content_type=""):
    """Reuse tested explicit public directory parsers; never infer SPA API routes."""
    from data.collect.web_sources import parse_citypass, parse_dodo, parse_marwin
    html = body.decode("utf-8", errors="replace")
    result = extract_page(html, url) if "html" in content_type or body.lstrip().startswith(b"<") else {"businesses": [], "public_links": [], "content_flags": []}
    host = urlsplit(url).hostname
    records = []
    try:
        if host == "publicapi.dodois.io" and urlsplit(url).path == "/KZ/api/v1/unitinfo/all":
            records = parse_dodo(json.loads(html))
        elif host in {"marwin.kz", "www.marwin.kz"} and urlsplit(url).path.rstrip("/") == "/shops":
            records = parse_marwin(html)
        elif host == "astana.citypass.kz":
            records = parse_citypass(html, url)
    except (ValueError, TypeError, AttributeError, KeyError) as exc:
        result["directory_parser_error"] = type(exc).__name__
    for record in records:
        result["businesses"].append({"name": record.get("name"), "address": record.get("address"),
            "lat": record.get("lat"), "lon": record.get("lon"), "source_id": record["id"],
            "source_license": record.get("source_license", "not_specified"), "parser": "official_directory_structured",
            "facts": {k: record[k] for k in ("opening_hours", "phone", "website", "address", "wheelchair", "kid_friendly") if record.get(k) is not None},
            "raw_directory_record": record})
    return result


def identity_match(poi, candidate):
    name_match = bool(name_keys(poi) & name_keys(candidate))
    both_address = bool(poi.get("address") and candidate.get("address"))
    address_match = bool(both_address and addresses_compatible(poi["address"], candidate["address"]))
    geo = all(_number(p.get(k)) is not None and -limit <= float(p[k]) <= limit
              for p in (poi, candidate) for k, limit in (("lat", 90), ("lon", 180)))
    distance = _distance(poi, candidate) if geo else None
    matched = name_match and not (both_address and not address_match) and (address_match or (distance is not None and distance <= 150)) and (distance is None or distance <= 150)
    return {"matched": bool(matched), "name_match": name_match, "address_match": address_match,
            "address_conflict": bool(both_address and not address_match), "distance_m": round(distance, 2) if distance is not None else None,
            "method": "exact_explicit_name_and_address_or_geo_150m"}


def applicable_fields(poi):
    result = set(BASE_FIELDS)
    if poi.get("category") in TIMED:
        result |= {"opening_hours", "phone"}
    if poi.get("category") in FOOD:
        result |= {"menu_url", "price_range", "cuisine"}
    return sorted(result)


def field_gaps(poi):
    fields = {**poi, "source_description": poi.get("description") if poi.get("description_kind") == "source" else None}
    return [key for key in applicable_fields(poi) if fields.get(key) is None or fields.get(key) == "" or fields.get(key) == []]


class PublicFetcher:
    """HTTPS SNI and Host are preserved while connecting to validated public IPs.

    No proxy environment, automatic redirects, credentials, or private DNS targets.
    Robots failure is incomplete, not permission to crawl. Each host is serialized.
    """
    def __init__(self, cache, *, concurrency=8, timeout=10, delay=.8, max_bytes=2_000_000, transport=None, resolver=None):
        self.cache = Path(cache)
        self.cache.mkdir(parents=True, exist_ok=True)
        self.sem = asyncio.Semaphore(min(concurrency, 8))
        self.dns_sem = asyncio.Semaphore(min(concurrency, 8))
        self.timeout, self.delay, self.max_bytes = timeout, delay, max_bytes
        # IP pinning makes the pool's URL host an IP. Reuse across virtual hosts
        # would reuse the first host's TLS session, so every request closes it.
        self.client = httpx.AsyncClient(transport=transport, trust_env=False, follow_redirects=False, timeout=httpx.Timeout(timeout), headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/ld+json,application/json;q=0.9,*/*;q=0.1", "Connection": "close"}, limits=httpx.Limits(max_connections=8, max_keepalive_connections=0))
        self.resolver = resolver or self._resolve
        self.host_locks, self.robots_locks = defaultdict(asyncio.Lock), defaultdict(asyncio.Lock)
        self.last, self.robots, self.crawl_delays = {}, {}, {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.client.aclose()

    async def _resolve(self, host):
        answers = await asyncio.wait_for(asyncio.get_running_loop().getaddrinfo(host, None, type=socket.SOCK_STREAM), self.timeout)
        return sorted({answer[4][0] for answer in answers}, key=lambda ip: (":" in ip, ip))

    async def _request(self, url, *, robots_check=False, max_bytes=None, api_policy=False):
        chain, retained = [], b""
        current = url
        for _ in range(6):
            current = normalize_url(current)
            p = urlsplit(current)
            # Queueing time must not consume the DNS operation's own timeout.
            async with self.dns_sem:
                ips = await self.resolver(p.hostname)
            if not ips or any(not ipaddress.ip_address(ip).is_global for ip in ips):
                raise ValueError("nonpublic_dns_address")
            ip = ips[0]
            pinned = urlunsplit((p.scheme, "[" + ip + "]" if ":" in ip else ip, p.path, p.query, ""))
            async with self.host_locks[p.hostname]:
                pause = max(self.delay, self.crawl_delays.get(p.hostname, 0)) - (time.monotonic() - self.last.get(p.hostname, 0))
                if pause > 0:
                    await asyncio.sleep(pause)
                async with self.sem, asyncio.timeout(self.timeout):
                    try:
                        async with self.client.stream("GET", pinned, headers={"Host": p.hostname, "Cookie": ""}, extensions={"sni_hostname": p.hostname}) as response:
                            info = {"url": current, "http_status": response.status_code, "resolved_ip": ip,
                                    "content_type": response.headers.get("content-type"), "headers": {k: v for k, v in response.headers.items() if k in {"last-modified", "etag", "content-type", "location", "content-length"}}}
                            if response.status_code in {301, 302, 303, 307, 308}:
                                target = urljoin(current, response.headers.get("location", ""))
                                chain.append(info)
                                try:
                                    target = normalize_url(target)
                                except ValueError:
                                    return {"status": "blocked_unsafe_url", "redirect_chain": chain, "final_url": current}, b""
                                retained = b""
                            else:
                                limit = max_bytes if max_bytes is not None else self.max_bytes
                                over = False
                                async for chunk in response.aiter_bytes():
                                    remaining = limit - len(retained)
                                    if len(chunk) > remaining:
                                        retained += chunk[:remaining]
                                        over = True
                                        break
                                    retained += chunk
                                status = "incomplete_body_limit" if over else ("successful_fetch" if 200 <= response.status_code < 300 else "http_error")
                                return {**info, "status": status, "redirect_chain": chain, "final_url": current,
                                        "bytes_retained": len(retained), "body_complete": not over}, retained
                    finally:
                        self.last[p.hostname] = time.monotonic()
            target_parts = urlsplit(target)
            target_api = api_policy and target_parts.scheme == "https" and (target_parts.hostname, target_parts.path) in DOCUMENTED_APIS
            if robots_check and not target_api:
                permission = await self._robots(target)
                if permission["status"] != "allowed":
                    return {"status": permission["status"], "robots": permission, "redirect_chain": chain, "final_url": target}, b""
            current = target
        return {"status": "incomplete_redirect_limit", "redirect_chain": chain, "final_url": current}, b""

    async def _robots(self, url):
        p = urlsplit(url)
        origin = urlunsplit((p.scheme, p.netloc, "", "", ""))
        async with self.robots_locks[origin]:
            if origin not in self.robots:
                robots_url = origin + "/robots.txt"
                try:
                    info, body = await self._request(robots_url, max_bytes=250_000)
                    code = info.get("http_status")
                    if info["status"] == "successful_fetch":
                        parser = RobotFileParser(robots_url)
                        parser.parse(body.decode("utf-8", errors="replace").splitlines())
                        crawl_delay = parser.crawl_delay(USER_AGENT) or parser.crawl_delay("*")
                        if crawl_delay:
                            self.crawl_delays[p.hostname] = max(self.crawl_delays.get(p.hostname, 0), crawl_delay)
                        self.robots[origin] = (parser, {"url": robots_url, "http_status": code, "checked_at": utcnow(), "crawl_delay": crawl_delay})
                    elif code in {404, 410}:
                        self.robots[origin] = (None, {"url": robots_url, "http_status": code, "checked_at": utcnow()})
                    else:
                        self.robots[origin] = (False, {"url": robots_url, "http_status": code, "checked_at": utcnow(), "status": "blocked_robots" if code in {401, 403} else "incomplete_robots_unavailable"})
                except (ValueError, httpx.HTTPError, OSError, asyncio.TimeoutError) as exc:
                    self.robots[origin] = (False, {"url": robots_url, "checked_at": utcnow(), "status": "incomplete_robots_unavailable", "error": type(exc).__name__})
            parser, metadata = self.robots[origin]
            if parser is False:
                return metadata
            if parser is not None and not parser.can_fetch(USER_AGENT, url):
                return {**metadata, "status": "blocked_robots"}
            return {**metadata, "status": "allowed"}

    async def fetch(self, url, *, refresh=False, documented_api=False):
        p = urlsplit(url)
        api_allowed = documented_api and p.scheme == "https" and (p.hostname, p.path) in DOCUMENTED_APIS
        key = hashlib.sha256((url + ("|documented-api" if api_allowed else "")).encode()).hexdigest()
        cache_path = self.cache / (key + ".json")
        if cache_path.exists() and not refresh:
            return {**json.loads(cache_path.read_text()), "url": url, "requested_url": url, "cache_hit": True}
        result = {"url": url, "requested_url": url, "started_at": utcnow(), "cache_hit": False}
        body = b""
        try:
            normalized = normalize_url(url)
            # This is data retrieval through an expressly documented read-only API,
            # rather than indexing API URLs as web pages. Never applies to sites.
            permission = {"status": "documented_read_only_api_policy", "policy_url": API_POLICY,
                          "purpose": "bounded_one_off_source_ids_read", "limits": "sequential; <10000 queries; <1GB; <10min server work/day"} if api_allowed else await self._robots(normalized)
            result["robots"] = permission
            if permission["status"] in {"allowed", "documented_read_only_api_policy"}:
                detail, body = await self._request(normalized, robots_check=True, api_policy=api_allowed)
                result.update(detail)
                if result["status"] == "successful_fetch":
                    result["extracted"] = extract_source_payload(body, result["final_url"], result.get("content_type") or "")
            else:
                result["status"] = permission["status"]
        except (ValueError, httpx.InvalidURL) as exc:
            result.update(status="blocked_unsafe_url", error=str(exc))
        except (httpx.HTTPError, OSError, asyncio.TimeoutError) as exc:
            result.update(status="network_error", error=type(exc).__name__, error_detail=str(exc)[:300])
        except Exception as exc:
            # An untrusted page or parser defect cannot cancel thousands of
            # independent source checks. Preserve its body and explicit failure.
            result.update(status="incomplete_extraction_error" if body else "incomplete_client_error",
                          error=type(exc).__name__, error_detail=str(exc)[:300])
        result["fetched_at"] = utcnow()
        result["url"] = url
        if body:
            body_hash = hashlib.sha256(body).hexdigest()
            raw_path = self.cache / (key + "-" + body_hash + ".body")
            raw_path.write_bytes(body)
            result.update(raw_cache=str(raw_path), raw_sha256=body_hash)
        cache_path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        return result


def build_rows(pois, fetches, source_checks, *, user_as_of="2026-10-19"):
    result = []
    for poi in pois:
        website = poi.get("website")
        try:
            key = normalize_url(website) if website else None
        except ValueError:
            key = website
        fetch = fetches.get(key, {})
        status = fetch.get("status") or ("pending" if website else "no_url")
        content_flags = (fetch.get("extracted") or {}).get("content_flags", [])
        matched = [identity_match(poi, c) for _, _, f in _row_fetches(poi, fetches)
                   if not (f.get("extracted") or {}).get("content_flags")
                   for c in (f.get("extracted") or {}).get("businesses", [])]
        confirmed = any(m["matched"] for m in matched)
        source = source_checks.get(poi["id"], {})
        if not source:
            try:
                source_fetch = fetches.get(normalize_url(poi.get("source_url")), {})
            except (ValueError, TypeError):
                source_fetch = {}
            if source_fetch:
                source = {"status": source_fetch["status"], "source_url": poi.get("source_url"), "fetched_at": source_fetch.get("fetched_at")}
        confirmed = confirmed or source.get("branch_identity_confirmed", False)
        confirmation = "branch_identity_confirmed" if confirmed else ("unmatched" if status == "successful_fetch" and not content_flags else "incomplete")
        gaps = field_gaps(poi)
        result.append({"canonical_id": poi["id"], "name": poi.get("name"), "category": poi.get("category"),
                       "source": poi.get("source"), "source_url": poi.get("source_url"), "listed_website": website,
                       "website_check_status": status, "website_http_status": fetch.get("http_status"),
                       "website_previous_observation_status": fetch.get("previous_observation_status"),
                       "website_fetched_at": fetch.get("fetched_at"), "confirmation_status": confirmation,
                       "website_content_flags": content_flags,
                       "operating_status": "unknown", "source_check": source or {"status": "not_refetched", "reason": "catalog_source_metadata_only"},
                       "applicable_fields": applicable_fields(poi), "missing_fields": gaps,
                       "field_data_complete": not gaps, "branch_match_count": sum(m["matched"] for m in matched),
                       "search_complete": False, "deletion_eligible": False, "user_as_of": user_as_of,
                       "search_scope": "catalog_listed_website_and_available_structured_sources_only"})
    return result


def _row_fetches(poi, fetches):
    found = set()
    for field, kind in (("website", "catalog_listed_website_jsonld"), ("source_url", "exact_catalog_source_jsonld")):
        try:
            key = normalize_url(poi.get(field))
        except (ValueError, TypeError):
            continue
        if key in fetches and key not in found:
            found.add(key)
            yield kind, key, fetches[key]


def make_candidates(pois, fetches, user_as_of):
    result = []
    for poi in pois:
        for kind, key, fetch in _row_fetches(poi, fetches):
            for i, business in enumerate((fetch.get("extracted") or {}).get("businesses", [])):
                match = identity_match(poi, business)
                if business.get("source_id"):
                    match["source_id_match"] = business["source_id"] in {poi["id"]} | {r.get("id") for r in poi.get("source_records", [])}
                if (fetch.get("extracted") or {}).get("content_flags"):
                    match = {**match, "matched": False, "held_for_content_review": True}
                result.append({"candidate_id": hashlib.sha256(f"{poi['id']}:{key}:{i}".encode()).hexdigest()[:24],
                               "canonical_id": poi["id"], "source_url": fetch.get("final_url", key),
                               "source_kind": business.get("parser", kind), "source_id": business.get("source_id"),
                               "source_license": business.get("source_license", "not_specified"), "fetched_at": fetch.get("fetched_at"),
                               "user_as_of": user_as_of, "valid_from": None, "valid_until": None,
                               "identity_evidence": match, "publication_status": "candidate_requires_review",
                               "operating_status": "unknown", "facts": business.get("facts", {}),
                               "source_identity": {k: business.get(k) for k in ("name", "address", "lat", "lon")},
                               "raw_jsonld": business.get("raw_jsonld"), "raw_cache": fetch.get("raw_cache"),
                               "raw_directory_record": business.get("raw_directory_record"),
                               "raw_sha256": fetch.get("raw_sha256"), "public_links": (fetch.get("extracted") or {}).get("public_links", [])})
    return result


def _osm_refs(poi):
    return [r["id"] for r in (poi.get("source_records") or [poi])
            if r.get("source") == "osm" and re.fullmatch(r"osm:(?:node|way|relation)/\d+", r.get("id", ""))]


def osm_id_batches(pois, batch_size=100):
    ids = sorted({ident for poi in pois for ident in _osm_refs(poi)})
    result = []
    for start in range(0, len(ids), batch_size):
        batch = ids[start:start + batch_size]
        selections = []
        for kind in ("node", "way", "relation"):
            values = [ident.split("/", 1)[1] for ident in batch if ident.startswith("osm:" + kind + "/")]
            if values:
                selections.append(kind + "(id:" + ",".join(values) + ");")
        query = "[out:json][timeout:8];(" + "".join(selections) + ");out meta center;"
        result.append({"batch_id": hashlib.sha256(query.encode()).hexdigest()[:16], "ids": batch, "query": query})
    return result


def osm_observations(pois, ids, payload, fetch):
    by_id = {f"osm:{e.get('type')}/{e.get('id')}": e for e in payload.get("elements", [])}
    branches = defaultdict(list)
    for poi in pois:
        for ident in _osm_refs(poi):
            branches[ident].append(poi)
    observations, candidates, checks = [], [], {}
    for ident in ids:
        element = by_id.get(ident)
        tags = (element or {}).get("tags", {})
        geo = element if element and element.get("type") == "node" else (element or {}).get("center", {})
        lifecycle = {k: v for k, v in tags.items() if k.startswith(("disused", "abandoned", "demolished", "removed", "closed", "end_date")) or (k == "opening_hours" and str(v).lower() in {"closed", "off", "permanently closed"})}
        status = "current_object_present" if element else ("object_not_returned" if fetch["status"] == "successful_fetch" and not payload.get("remark") else "incomplete")
        observation = {"source_id": ident, "canonical_ids": [p["id"] for p in branches[ident]], "status": status,
                       "source_url": "https://www.openstreetmap.org/" + ident.split(":", 1)[1], "query_url": fetch.get("url"),
                       "fetched_at": fetch.get("fetched_at"), "source_updated_at": (element or {}).get("timestamp"),
                       "source_version": (element or {}).get("version"), "raw_tags": tags,
                       "lat": geo.get("lat"), "lon": geo.get("lon"), "raw_cache": fetch.get("raw_cache"),
                       "lifecycle_review_required": bool(lifecycle), "lifecycle_tags": lifecycle,
                       "operating_status": "unknown", "deletion_eligible": False}
        observations.append(observation)
        if not element:
            for poi in branches[ident]:
                checks[poi["id"]] = {"status": status, "source_id": ident, "branch_identity_confirmed": False, "fetched_at": fetch.get("fetched_at")}
            continue
        address = tags.get("addr:full") or ", ".join(str(tags[k]) for k in ("addr:street", "addr:place", "addr:housenumber", "addr:unit") if tags.get(k)) or None
        source_identity = {"name": tags.get("name") or tags.get("name:ru") or tags.get("name:kk"), "name_en": tags.get("name:en"),
                           "name_kk": tags.get("name:kk"), "address": address, "lat": geo.get("lat"), "lon": geo.get("lon")}
        facts = {field: tags[key] for field, key in (("opening_hours", "opening_hours"), ("phone", "phone"), ("website", "website"), ("wheelchair", "wheelchair"), ("cuisine", "cuisine"), ("internet_access", "internet_access"), ("fee", "fee"), ("access", "access"), ("diet_vegetarian", "diet:vegetarian"), ("diet_vegan", "diet:vegan"), ("delivery", "delivery"), ("takeaway", "takeaway"), ("outdoor_seating", "outdoor_seating"), ("smoking", "smoking"), ("menu_url", "website:menu")) if tags.get(key) is not None}
        for field in ("phone", "website"):
            if field not in facts and tags.get("contact:" + field):
                facts[field] = tags["contact:" + field]
        if address:
            facts["address"] = address
        for poi in branches[ident]:
            match = identity_match(poi, source_identity)
            checks[poi["id"]] = {"status": status, "source_id": ident, "branch_identity_confirmed": bool(match["matched"] and not lifecycle),
                                "identity_evidence": match, "fetched_at": fetch.get("fetched_at"), "source_updated_at": element.get("timestamp"), "lifecycle_review_required": bool(lifecycle)}
            candidates.append({"candidate_id": hashlib.sha256(f"{poi['id']}:{ident}:osm-current".encode()).hexdigest()[:24], "canonical_id": poi["id"],
                               "source_id": ident, "source_url": observation["source_url"], "source_kind": "current_osm_tags", "source_license": "ODbL-1.0",
                               "fetched_at": fetch.get("fetched_at"), "source_updated_at": element.get("timestamp"), "identity_evidence": match,
                               "source_identity": source_identity, "facts": facts, "raw_tags": tags, "lifecycle_review_required": bool(lifecycle),
                               "publication_status": "candidate_requires_review", "operating_status": "unknown", "raw_cache": fetch.get("raw_cache")})
    return observations, candidates, checks


async def run_osm(args):
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    baseline = output / "input-pois.json"
    if not baseline.exists():
        baseline.write_bytes(Path(args.input).read_bytes())
    pois = json.loads(baseline.read_text())
    batches = osm_id_batches(pois, batch_size=args.osm_batch_size)
    (output / "audit-osm-batches.json").write_text(json.dumps(batches, ensure_ascii=False, indent=2), encoding="utf-8")
    prior = {b["batch_id"]: b for b in read_jsonl(output / "audit-osm-fetches.jsonl")}
    endpoints = ["https://overpass-api.de/api/interpreter", "https://overpass.private.coffee/api/interpreter", "https://maps.mail.ru/osm/tools/overpass/api/interpreter"]
    state_path = output / "audit-osm-endpoint-state.json"
    overloads = Counter(json.loads(state_path.read_text()) if state_path.exists() else {})
    if not state_path.exists():
        # Recover failures from earlier interrupted runs rather than hammering a
        # known overloaded endpoint again after restarting the audit.
        history = defaultdict(list)
        for path in (output / "osm-cache").glob("*.json"):
            response = json.loads(path.read_text())
            parsed = urlsplit(response["url"])
            endpoint = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
            history[endpoint].append(response)
        for endpoint, responses in history.items():
            for response in sorted(responses, key=lambda r: r.get("fetched_at", "")):
                if response.get("http_status") in {406, 429, 500, 502, 503, 504} or response.get("status") == "network_error":
                    overloads[endpoint] += 1
                elif response.get("status") == "successful_fetch":
                    overloads[endpoint] = 0
    all_observations, all_candidates, all_checks = [], [], {}
    async with PublicFetcher(output / "osm-cache", concurrency=1, timeout=args.timeout, delay=max(args.delay, 1.1), max_bytes=4_000_000) as fetcher:
        for index, batch in enumerate(batches):
            fetched = prior.get(batch["batch_id"])
            if fetched and (fetched["fetch"].get("status") != "successful_fetch" or not isinstance(fetched.get("payload", {}).get("elements"), list)):
                fetched = None
            if fetched:
                info, payload = fetched["fetch"], fetched.get("payload", {})
            else:
                payload, info = {}, {"status": "incomplete_source_unavailable", "fetched_at": utcnow(), "reason": "all_endpoints_stopped_after_repeated_overload"}
                for endpoint in endpoints:
                    if overloads[endpoint] >= 3:
                        continue
                    url = endpoint + "?" + urlencode({"data": batch["query"]})
                    info = await fetcher.fetch(url, documented_api=True)
                    if info.get("http_status") in {406, 429, 500, 502, 503, 504} or info.get("status") == "network_error":
                        overloads[endpoint] += 1
                    else:
                        overloads[endpoint] = 0
                    if info.get("http_status") in {406, 429}:
                        await asyncio.sleep(30)
                    if info["status"] == "successful_fetch" and info.get("raw_cache"):
                        try:
                            payload = json.loads(Path(info["raw_cache"]).read_text())
                            if isinstance(payload.get("elements"), list) and not payload.get("remark"):
                                break
                        except (ValueError, UnicodeError, AttributeError):
                            payload = {}
                with (output / "audit-osm-fetches.jsonl").open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps({"batch_id": batch["batch_id"], "fetch": info, "payload": payload}, ensure_ascii=False) + "\n")
            observations, candidates, checks = osm_observations(pois, batch["ids"], payload, info)
            all_observations.extend(observations)
            all_candidates.extend(candidates)
            # Keep a confirmed match when another source ID in the same canonical row failed.
            for ident, check in checks.items():
                if check.get("branch_identity_confirmed") or not all_checks.get(ident, {}).get("branch_identity_confirmed"):
                    all_checks[ident] = check
            print(json.dumps({"event": "osm_progress", "at": utcnow(), "batch": index + 1, "batches": len(batches), "objects": len(all_observations), "last_status": info.get("status")}), flush=True)
            for name, data in (("audit-osm-observations.jsonl", all_observations), ("audit-osm-candidates.jsonl", all_candidates)):
                (output / name).write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in data), encoding="utf-8")
            (output / "audit-osm-checks.json").write_text(json.dumps(all_checks, ensure_ascii=False, indent=2), encoding="utf-8")
            state_path.write_text(json.dumps(dict(overloads), ensure_ascii=False, indent=2), encoding="utf-8")
    summary = {"generated_at": utcnow(), "source_objects": len(all_observations), "batches": len(batches),
               "api_policy_url": API_POLICY, "api_policy_rationale": "One-off documented read-only API consumer retrieval; sequential bounded source-ID batches, no indexing/API credential use; stop endpoints after three repeated overload failures.",
               "statuses": dict(Counter(o["status"] for o in all_observations)), "canonical_rows_with_checks": len(all_checks),
               "canonical_identity_matches": sum(c.get("branch_identity_confirmed", False) for c in all_checks.values()),
               "lifecycle_review_observations": sum(o["lifecycle_review_required"] for o in all_observations),
               "limitations": ["Current OSM objects are crowdsourced identity/source observations, not proof of active business operation.", "Missing objects and source failures never establish closure.", "All current fields remain candidates requiring review."]}
    (output / "audit-osm-summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"event": "osm_complete", **summary}), flush=True)


def write_report(pois, fetches, output, *, user_as_of, source_checks=None):
    output = Path(output)
    outage_path = output / "audit-host-outage.json"
    outage = json.loads(outage_path.read_text()) if outage_path.exists() else {}
    if outage:
        fetches = dict(fetches)
        for deferred in outage.get("deferred", []):
            url = deferred["url"]
            if url in fetches:
                fetches[url] = {**fetches[url], "previous_observation_status": fetches[url]["status"],
                                "status": "retry_not_completed_host_outage"}
    rows = build_rows(pois, fetches, source_checks or {}, user_as_of=user_as_of)
    candidates = make_candidates(pois, fetches, user_as_of)
    for name, data in (("rows.jsonl", rows), ("candidates.jsonl", candidates)):
        (output / name).write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in data), encoding="utf-8")
    category = {}
    for cat in sorted({p.get("category") for p in pois}):
        cat_rows = [r for r in rows if r["category"] == cat]
        category[cat] = {"records": len(cat_rows), "missing_fields": dict(Counter(k for r in cat_rows for k in r["missing_fields"])),
                         "applicable_field_denominators": dict(Counter(k for r in cat_rows for k in r["applicable_fields"]))}
    summary = {"schema_version": 1, "generated_at": utcnow(), "user_as_of": user_as_of,
               "network_pass_status": outage.get("network_pass_status", "known_source_observations"),
               "deferred_retry_count": outage.get("deferred_retry_count", 0),
               "deferred_retry_domains": outage.get("deferred_domains", {}),
               "known_url_targets_with_bounded_outcomes": len(fetches) - outage.get("deferred_retry_count", 0),
               "records": len(rows), "listed_website_rows": sum(bool(p.get("website")) for p in pois),
               "distinct_fetched_urls": len(fetches), "fetch_statuses": dict(Counter(f["status"] for f in fetches.values())),
               "row_website_statuses": dict(Counter(r["website_check_status"] for r in rows)),
               "confirmation_statuses": dict(Counter(r["confirmation_status"] for r in rows)),
               "source_check_statuses": dict(Counter(r["source_check"]["status"] for r in rows)),
               "field_missing_counts": dict(Counter(k for r in rows for k in r["missing_fields"])),
               "field_applicable_denominators": dict(Counter(k for r in rows for k in r["applicable_fields"])),
               "rows_with_missing_applicable_fields": sum(bool(r["missing_fields"]) for r in rows),
               "rows_without_current_branch_confirmation": sum(r["confirmation_status"] != "branch_identity_confirmed" for r in rows),
               "fresh_exact_branch_identity_rows": sum(r["confirmation_status"] == "branch_identity_confirmed" for r in rows),
               "fetched_sources_without_branch_match_rows": sum(r["confirmation_status"] == "unmatched" for r in rows),
               "incomplete_branch_checks_rows": sum(r["confirmation_status"] == "incomplete" for r in rows),
               "branch_matched_fact_rows": len({c["canonical_id"] for c in candidates if c["identity_evidence"]["matched"] and c["facts"]}),
               "branch_matched_fact_values": sum(len(c["facts"]) for c in candidates if c["identity_evidence"]["matched"]),
               "verified_operating_rows": 0,
               "rows_incomplete_website_check": sum(r["website_check_status"] != "successful_fetch" for r in rows),
               "rows_completed_exhaustive_search": 0, "deletion_eligible": 0, "confirmed_permanent_closures": 0,
               "no_data_after_completed_search": 0,
               "candidate_records": len(candidates), "branch_matched_candidates": sum(c["identity_evidence"]["matched"] for c in candidates),
               "per_category": category,
               "limitations": ["A successful HTTP fetch is not proof of current operation.", "Listed websites include chain homepages and social profiles; official ownership is not independently established.", "No-URL, robots denial, HTTP or network failures are incomplete checks, never a closure or proof of absence.", "This pass checks known source URLs only; it is not an exhaustive web search and authorizes no deletions.", "No exhaustive 2GIS or general web search/index is available in this pass; public listed 2GIS URLs alone do not close that coverage gap.", "Overture STAC catalog links are release-level references, not exact branch pages; no generic SPA requests are issued per row.", "Raw JSON-LD may describe other branches; all candidate facts require identity review and source rights review.", "Availability/closure is unknown unless a separate branch-specific source explicitly establishes it."]}
    osm_summary_path = output / "audit-osm-summary.json"
    if osm_summary_path.exists():
        summary["current_osm_audit"] = json.loads(osm_summary_path.read_text())
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# Whole-catalog public-source audit", "", f"Generated: {summary['generated_at']}. User as-of label: {user_as_of}.", "",
             f"Records covered: **{len(rows):,}**. Listed website rows: **{summary['listed_website_rows']:,}**. Distinct source fetch results: **{len(fetches):,}**.", "",
             f"Rows with missing applicable fields: **{summary['rows_with_missing_applicable_fields']:,}**. Rows without current branch confirmation: **{summary['rows_without_current_branch_confirmation']:,}**.",
             f"Rows with incomplete or unavailable website checks: **{summary['rows_incomplete_website_check']:,}**. Completed exhaustive searches: **0**. Deletion eligible: **0**. Confirmed permanent closures: **0**.", "",
             f"Fresh exact branch identity matches: **{summary['fresh_exact_branch_identity_rows']:,}**; fetched generic/unmatched source rows: **{summary['fetched_sources_without_branch_match_rows']:,}**; incomplete branch checks: **{summary['incomplete_branch_checks_rows']:,}**. Current operation is separately unproved: **0** verified operating rows.", "",
             "## Fetch outcomes", "", "| Outcome | Distinct URLs |", "|---|---:|"]
    lines.extend(f"| {status} | {count:,} |" for status, count in sorted(summary["fetch_statuses"].items()))
    lines += ["", "## Applicable field gaps", "", "| Field | Missing | Applicable rows |", "|---|---:|---:|"]
    lines.extend(f"| {field} | {summary['field_missing_counts'].get(field, 0):,} | {count:,} |" for field, count in sorted(summary["field_applicable_denominators"].items()))
    lines += ["", "## Interpretation", ""] + ["- " + text for text in summary["limitations"]]
    if outage:
        lines += ["", "## Uncompleted retry tail", "", f"Network pass status: **{summary['network_pass_status']}**. **{summary['deferred_retry_count']:,}** URL retries were not completed after repeated host outages: {json.dumps(summary['deferred_retry_domains'])}.",
                  "Earlier per-target observations remain archived. These rows are explicitly `retry_not_completed_host_outage`; this report does not claim that every target was successfully fetched or freshly rechecked."]
    if "current_osm_audit" in summary:
        osm = summary["current_osm_audit"]
        lines += ["", "## Current OSM source checks", "", f"Source IDs: {osm['source_objects']:,}; canonical rows: {osm['canonical_rows_with_checks']:,}; outcomes: {json.dumps(osm['statuses'])}.",
                  "Read-only API policy: " + osm.get("api_policy_url", API_POLICY), "", osm.get("api_policy_rationale", "")]
    lines += ["", "Category-specific counts and denominators are in `summary.json`; every canonical ID is represented in `rows.jsonl`. Raw responses and redirect/DNS metadata are retained in `cache/`. Candidate branch facts are separate in `candidates.jsonl`."]
    (output / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary


async def run(args):
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    baseline = output / "input-pois.json"
    if not baseline.exists():
        baseline.write_bytes(Path(args.input).read_bytes())
    pois = json.loads(baseline.read_text())
    targets = set()
    for poi in pois:
        if poi.get("website"):
            try:
                targets.add(normalize_url(poi["website"]))
            except ValueError:
                targets.add(poi["website"])
    # Exact official directory pages are useful; release-level Overture URLs are not.
    for poi in pois:
        if poi.get("source") in {"citypass", "sxodim", "marwin", "dodo", "khanshatyr"} and poi.get("source_url"):
            try:
                targets.add(normalize_url(poi["source_url"]))
            except ValueError:
                pass
    log = output / "fetches.jsonl"
    fetches = load_fetch_results(log, output / "cache", targets)
    source_checks_path = output / "audit-osm-checks.json"
    source_checks = json.loads(source_checks_path.read_text()) if source_checks_path.exists() else {}
    if getattr(args, "report_only", False):
        for fetch in fetches.values():
            if fetch.get("status") == "successful_fetch" and fetch.get("raw_cache"):
                raw = Path(fetch["raw_cache"]).read_bytes()
                if fetch.get("raw_sha256") and hashlib.sha256(raw).hexdigest() != fetch["raw_sha256"]:
                    fetch["extracted"] = {"businesses": [], "content_flags": ["raw_cache_integrity_failure"]}
                else:
                    fetch["extracted"] = extract_source_payload(raw, fetch.get("final_url", fetch["url"]), fetch.get("content_type") or "")
        summary = write_report(pois, fetches, output, user_as_of=args.as_of, source_checks=source_checks)
        summary.update(target_urls=len(targets), pending_urls=len(targets - fetches.keys()), input_sha256=hashlib.sha256(baseline.read_bytes()).hexdigest())
        if args.retry_before:
            summary["retry_cutoff"] = args.retry_before
            summary["initial_queue_affected_outcomes_remaining"] = sum(f.get("fetched_at", "") < args.retry_before and f["status"] in {"network_error", "incomplete_robots_unavailable"} for f in fetches.values())
        (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"event": "report_complete", "at": utcnow(), "records": len(pois), "fetch_results": len(fetches)}), flush=True)
        return
    retry = {url for url, f in fetches.items() if args.retry_incomplete and f["status"] in {"network_error", "incomplete_robots_unavailable"}
             and (not args.retry_before or f.get("fetched_at", "") < args.retry_before)}
    pending = sorted((targets - fetches.keys()) | retry)
    if args.limit is not None:
        pending = pending[:args.limit]
    print(json.dumps({"event": "start", "at": utcnow(), "records": len(pois), "target_urls": len(targets), "cached_results": len(fetches), "pending": len(pending), "concurrency": args.concurrency}), flush=True)
    write_report(pois, fetches, output, user_as_of=args.as_of, source_checks=source_checks)
    async with PublicFetcher(output / "cache", concurrency=args.concurrency, timeout=args.timeout, delay=args.delay) as fetcher:
        async def worker(url):
            result = await fetcher.fetch(url, refresh=url in retry)
            fetches[url] = result
            with log.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(result, ensure_ascii=False) + "\n")
                stream.flush()
            if len(fetches) % 25 == 0:
                print(json.dumps({"event": "progress", "at": utcnow(), "completed": len(fetches), "target_urls": len(targets), "statuses": dict(Counter(f["status"] for f in fetches.values()))}), flush=True)
            if len(fetches) % 250 == 0:
                write_report(pois, fetches, output, user_as_of=args.as_of, source_checks=source_checks)
        await asyncio.gather(*(worker(url) for url in pending))
    summary = write_report(pois, fetches, output, user_as_of=args.as_of, source_checks=source_checks)
    summary["target_urls"] = len(targets)
    summary["pending_urls"] = len(targets - fetches.keys())
    summary["input_sha256"] = hashlib.sha256(baseline.read_bytes()).hexdigest()
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"event": "complete", "at": utcnow(), "records": len(pois), "completed": len(fetches), "pending": summary["pending_urls"]}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default="data/processed/pois.json")
    parser.add_argument("--output", required=True)
    parser.add_argument("--as-of", default="2026-10-19")
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--timeout", type=float, default=10)
    parser.add_argument("--delay", type=float, default=.8)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--retry-incomplete", action="store_true", help="Append fresh checks for cached network/robots-unavailable results; preserve prior observations.")
    parser.add_argument("--retry-before", help="Retry only results older than this UTC ISO timestamp, so an interrupted retry pass resumes without repeating finished attempts.")
    parser.add_argument("--osm-only", action="store_true", help="Fetch current exact OSM source IDs in bounded public Overpass batches.")
    parser.add_argument("--report-only", action="store_true", help="Rebuild candidate extraction, field gaps, and source counts from the retained responses without network access.")
    parser.add_argument("--osm-batch-size", type=int, default=100)
    args = parser.parse_args()
    asyncio.run(run_osm(args) if args.osm_only else run(args))


if __name__ == "__main__":
    main()

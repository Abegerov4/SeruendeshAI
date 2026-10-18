"""Small, polite factual supplements from public official directories.

Public access is not an open-data licence: every record retains that distinction.
Narrative copy and photographs are not mirrored. Unlocated facts are retained for
an unambiguous join, never assigned guessed coordinates.
"""
from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import time
from urllib.parse import urljoin, urlsplit, urlunsplit, parse_qs
from urllib.robotparser import RobotFileParser

from bs4 import BeautifulSoup
import httpx

from data.collect.normalize import _name_key, _distance
from data.collect.identity import addresses_compatible, _address_signature, name_keys

USER_AGENT = "SeruendeshAI/0.1 (Astana hackathon POI research)"


def _walk(value):
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from _walk(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk(item)


def _number(value):
    try:
        number = float(value)
        return number if math.isfinite(number) and not isinstance(value, bool) else None
    except (ValueError, TypeError):
        return None


def _base(source, ident, name, url, category="other"):
    return {"id": f"{source}:{ident}", "source": source, "name": name,
            "category": category, "source_url": url, "source_license": "not_specified",
            "opening_hours": None, "rating": None, "rating_count": None,
            "address": None, "phone": None, "website": None, "wheelchair": None,
            "kid_friendly": None, "description_source": None,
            "raw_tags": {}, "tags": [], "description": None,
            "collected_at": datetime.now(timezone.utc).isoformat()}


def parse_marwin(html: str) -> list[dict]:
    result = []
    soup = BeautifulSoup(html, "html.parser")
    for script in soup.find_all("script", type="text/x-magento-init"):
        try:
            config = json.loads(script.string or script.get_text())
        except (ValueError, TypeError):
            continue
        for node in _walk(config):
            stores = node.get("stores")
            if not isinstance(stores, dict):
                continue
            city = stores.get("astana", {})
            shops = city.get("shops", []) if isinstance(city, dict) else []
            if isinstance(shops, dict):
                shops = list(shops.values())
            for shop in shops:
                name = str(shop.get("name") or "").strip()
                if not re.search(r"marwin|м[ае]рвин|meloman|меломан", name, re.I) or re.search(r"europharma|еврофарма|пункт выдачи", name, re.I):
                    continue
                location = shop.get("location") or {}
                lat, lon = _number(location.get("lat")), _number(location.get("lng"))
                if lat is None or lon is None:
                    continue
                ident = shop.get("code") or hashlib.sha256((name+str(shop.get("address"))).encode()).hexdigest()[:16]
                poi = _base("marwin", ident, name, "https://www.marwin.kz/shops/")
                poi.update(lat=lat, lon=lon, address=shop.get("address"), tags=["магазин книг", "магазин игрушек"])
                poi["raw_tags"] = {"shop": "books", "schedule_text": shop.get("schedule"), "source_code": ident}
                phones = shop.get("phoneNumbers") or []
                if isinstance(phones, str):
                    poi["phone"] = phones
                elif phones:
                    poi["phone"] = "; ".join(str(p.get("number", p.get("phone", ""))) if isinstance(p, dict) else str(p) for p in phones)
                result.append(poi)
    return result


def _dodo_hours(row: dict) -> str | None:
    if row.get("IsAroundClockRestaurantWorkTime") is True:
        return "24/7"
    names = {day: short for day, short in zip(
        ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"),
        ("Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"))}
    days = {}
    for item in row.get("RestaurantWeekWorkingTime") or []:
        day = names.get(item.get("DayAlias"))
        start, end = item.get("WorkingTimeStart"), item.get("WorkingTimeEnd")
        if not day or type(start) is not int or type(end) is not int or not (0 <= start < 86400 and 0 <= end <= 86400) or start % 60 or end % 60:
            return None
        if start == end:
            return None  # equal endpoints are ambiguous without the explicit 24h flag
        if end == 0:
            end = 86400
        days[day] = f"{start//3600:02}:{start%3600//60:02}-{end//3600:02}:{end%3600//60:02}"
    if not days:
        return None
    if len(days) == 7 and len(set(days.values())) == 1:
        return "Mo-Su " + next(iter(days.values()))
    return "; ".join(day + " " + days[day] for day in names.values() if day in days)


def parse_dodo(payload) -> list[dict]:
    if isinstance(payload, dict):
        payload = payload.get("Units", payload.get("units", payload.get("Data")))
    if not isinstance(payload, list):
        raise ValueError("Dodo response is not a verified unit list")
    result = []
    for row in payload:
        if row.get("State") != 1 or row.get("Type") != 1 or row.get("IsTemporarilyClosed") is True:
            continue
        coords = row.get("Coordinates") or row.get("Location") or row
        lat = _number(coords.get("Latitude", coords.get("latitude")))
        lon = _number(coords.get("Longitude", coords.get("longitude")))
        if lat is None or lon is None or not (50.9 <= lat <= 51.4 and 71 <= lon <= 71.9):
            continue
        ident = row.get("Id", row.get("UUId", row.get("Uuid", row.get("Name"))))
        name = row.get("Alias") or "Додо Пицца " + row.get("Name", "")
        poi = _base("dodo", ident, name, "https://publicapi.dodois.io/KZ/api/v1/unitinfo/all", "restaurant")
        poi.update(lat=lat, lon=lon, address=row.get("Address"), tags=["пицца", "пиццерия"], website="https://dodopizza.kz/", opening_hours=_dodo_hours(row))
        poi["raw_tags"] = {"cuisine": "pizza", "locality": row.get("LocalityName") or (row.get("AddressDetails") or {}).get("LocalityName"), "schedule": row.get("Schedule", row.get("RestaurantSchedule")), "restaurant_week_working_time": row.get("RestaurantWeekWorkingTime"), "temporarily_closed": row.get("IsTemporarilyClosed")}
        result.append(poi)
    return result


def _next_payloads(html: str):
    """Read public Next.js hydration JSON without executing page JavaScript."""
    for script in BeautifulSoup(html, "html.parser").find_all("script"):
        match = re.search(r"self\.__next_f\.push\((\[.*\])\)", script.string or script.get_text(), re.S)
        if not match:
            continue
        try:
            packet = json.loads(match.group(1))
            text = packet[1] if len(packet) > 1 else None
            if isinstance(text, str) and ":" in text and "initialItems" in text:
                yield json.loads(text.split(":", 1)[1])
        except (ValueError, TypeError, IndexError):
            continue


def _daily_hours(period, schedule) -> str | None:
    if not isinstance(schedule, str):
        return None
    period = str(period or "").strip().casefold()
    text = schedule.strip().replace("–", "-").replace("—", "-")
    if period not in {"daily", "ежедневно", "күн сайын", "күнделікті", "every day", "каждый день"}:
        return None
    match = re.fullmatch(r"(\d{1,2})[:.](\d{2})\s*-\s*(\d{1,2})[:.](\d{2})", text)
    if not match:
        return None
    start_hour, start_minute, end_hour, end_minute = map(int, match.groups())
    if not (0 <= start_hour <= 23 and 0 <= end_hour <= 24 and start_minute < 60 and end_minute < 60 and (end_hour != 24 or end_minute == 0)):
        return None
    return f"Mo-Su {start_hour:02}:{start_minute:02}-{end_hour:02}:{end_minute:02}"


def _posted_hours(period, schedule) -> str | None:
    """Normalize only explicit daily or weekday-range opening windows."""
    normalized = _daily_hours(period, schedule)
    if normalized:
        return normalized
    period = str(period or "").strip().replace("–", "-").replace("—", "-").casefold()
    days = {"monday": "Mo", "tuesday": "Tu", "wednesday": "We", "thursday": "Th", "friday": "Fr", "saturday": "Sa", "sunday": "Su",
            "понедельник": "Mo", "вторник": "Tu", "среда": "We", "четверг": "Th", "пятница": "Fr", "суббота": "Sa", "воскресенье": "Su"}
    choices = "|".join(days)
    match = re.match(rf"^({choices})\s*-\s*({choices})(?:\s*,.*)?$", period)
    if not match:
        return None
    if not str(schedule or "").strip():
        windows = re.findall(r"\d{1,2}[:.]\d{2}\s*-\s*\d{1,2}[:.]\d{2}", period)
        if len(windows) != 1:
            return None
        schedule = windows[0]
    daily = _daily_hours("daily", schedule)
    return days[match.group(1)] + "-" + days[match.group(2)] + " " + daily.split(" ", 1)[1] if daily else None


def parse_citypass(html: str, url: str) -> list[dict]:
    found = {}
    lang = urlsplit(url).path.strip("/").split("/")[0]
    category_tags = {"monument": "monument", "park": "park", "theatre": "theatre", "museum": "museum", "entertainment": "attraction", "sight": "attraction"}
    for payload in _next_payloads(html):
        for node in _walk(payload):
            for row in node.get("initialItems", []) if isinstance(node.get("initialItems"), list) else []:
                name = str(row.get("title") or "").strip()
                if not name or not row.get("id") or not row.get("slug"):
                    continue
                slugs = {tag.get("slug") for tag in row.get("tags", []) if isinstance(tag, dict)}
                category = next((category_tags[tag] for tag in category_tags if tag in slugs), "attraction")
                link = urljoin(url.rstrip("/") + "/", row["slug"])
                poi = _base("citypass", row["id"], name, link, category)
                poi.update(address=row.get("address"), opening_hours=_posted_hours(row.get("work_period"), row.get("work_time")))
                poi["raw_tags"] = {"schedule_text": row.get("work_time"), "schedule_period": row.get("work_period"), "source_tags": [tag.get("name") for tag in row.get("tags", []) if isinstance(tag, dict)]}
                lat, lon = _number(row.get("latitude")), _number(row.get("longitude"))
                if lat is not None and lon is not None and -90 <= lat <= 90 and -180 <= lon <= 180:
                    poi.update(lat=lat, lon=lon)
                if lang in {"en", "kk"}:
                    poi["name_" + lang] = name
                found[poi["id"]] = poi
    return list(found.values())


def parse_sxodim(html: str, url: str, category: str) -> list[dict]:
    found = {}
    for card in BeautifulSoup(html, "html.parser").select(".impression-card[data-id]"):
        if card.find_parent(class_="impression-best"):
            continue
        anchor = card.select_one('a.impression-card-title[href]')
        if not anchor or not re.fullmatch(r"/astana/place/[^/]+/?", urlsplit(urljoin(url, anchor["href"])).path):
            continue
        name = (card.get("data-title") or anchor.get_text(" ", strip=True)).strip()
        if not name:
            continue
        poi = _base("sxodim", card["data-id"], name, urljoin(url, anchor["href"]), category)
        address = card.select_one(".impression-card-info")
        poi["address"] = address.get_text(" ", strip=True) if address else None
        poi["raw_tags"] = {"directory_category": card.get("data-category"), "listing_url": url}
        found[poi["id"]] = poi
    return list(found.values())


def iter_directory_pages(fetcher, start_url: str):
    """Visit every advertised page of this directory, with URL cycle detection."""
    start = urlsplit(start_url)
    queue, visited = deque([start_url]), set()
    while queue:
        url = queue.popleft()
        if url in visited:
            continue
        visited.add(url)
        html = fetcher.get(url)
        yield url, html
        for anchor in BeautifulSoup(html, "html.parser").select("a[href]"):
            next_url = urljoin(url, anchor["href"]).split("#")[0]
            parts = urlsplit(next_url)
            if parts.netloc == start.netloc and parts.path.rstrip("/") == start.path.rstrip("/") and "page" in parse_qs(parts.query) and next_url not in visited:
                queue.append(next_url)


def parse_mega_restaurants(html: str, url: str) -> list[dict]:
    """Retain brand, mall/floor and posted hours, not copyrighted narrative."""
    found = {}
    for card in BeautifulSoup(html, "html.parser").select(".rest-card"):
        address_node, logo = card.select_one(".address"), card.select_one("img.logo")
        if not address_node or not logo:
            continue
        lines = list(address_node.stripped_strings)
        if not lines or not re.search(r"MEGA\s+S(?:ilk|lik)\s+Way", lines[0], re.I):
            continue
        label = logo.get("alt", "").strip()
        raw_name = label
        paragraph = card.select_one(".rest-card__description")
        text = paragraph.get_text(" ", strip=True) if paragraph else ""
        named = re.match(r"^(?:Ресторан\s+)?([A-Z][A-Za-z0-9 &'’.-]{1,35}?)\s+(?:был|[—–]|в переводе)", text)
        if named:
            name = named.group(1)
        else:
            asset = urlsplit(logo.get("src", "")).path.rsplit("/", 1)[-1].split(".")[0]
            label = asset if label.startswith("logo_") and "coffee" in asset else label
            name = re.sub(r"(?:^logo[_ ]|[_ ](?:rest[_ ]logo|white|sushi rest logo).*$|\.scale.*$|\.max.*$)", "", label, flags=re.I)
            name = name.replace("_", " ").strip()
            if "okadzaki" in label.casefold():
                name = "Okadzaki"
            if re.search(r"дизайн|без названия|^\d", name, re.I):
                continue
            if name.islower():
                name = name.title()
        if not name:
            continue
        ident = hashlib.sha256(("MEGA Silk Way:" + raw_name).encode()).hexdigest()[:16]
        category = "cafe" if re.search(r"кафе|кофеен|кофей|пекарн", text, re.I) or "starbucks" in name.casefold() else "restaurant"
        poi = _base("mega_silkway", ident, name, url, category)
        schedule = " ".join(lines[1:]).strip()
        daily = re.match(r"Ежедневно\s+(.+)", schedule, re.I)
        poi.update(address=lines[0], opening_hours=_daily_hours("ежедневно", daily.group(1)) if daily else None)
        poi["raw_tags"] = {"mall": "MEGA Silk Way", "logo_label": raw_name, "logo_asset": logo.get("src"), "schedule_text": schedule, "name_origin": "official logo asset label or named introductory phrase"}
        menu = card.select_one('a[href*="restaurant_menus"]')
        if menu:
            poi["raw_tags"]["menu_url"] = urljoin(url, menu["href"])
        found[poi["id"]] = poi
    return list(found.values())


def attach_directory_facts(base_candidates: list[dict], facts: list[dict]) -> tuple[list[dict], list[dict]]:
    """Resolve names only with independently matching branch context.

    Mall tenant facts require an unambiguous physical mall anchor and a venue
    within500m of that anchor. Other facts require complete compatible street
    and house addresses. Neither a city label nor a missing address is proof.
    """
    names = defaultdict(dict)
    usable = []
    for poi in base_candidates:
        if poi.get("lat") is None or poi.get("lon") is None:
            continue
        usable.append(poi)
        for key in name_keys(poi):
            names[key][poi["id"]] = poi
    mall_names = {
        "mega_silkway": {"Mega Silk Way", "Mega Silk-way", "Мега Силк Вей"},
        "greenmall": {"Green Mall", "GreenMall", "Грин Молл"},
        "khanshatyr": {"Хан Шатыр", "Ханшатыр", "Khan Shatyr", "KhanShatyr"},
    }
    source_scope = {"mega_silkway": "mega_silkway", "mega": "mega_silkway", "mega_restaurants": "mega_silkway", "greenmall": "greenmall", "khanshatyr": "khanshatyr"}
    anchors = {}
    for scope, labels in mall_names.items():
        keys = {_name_key(label) for label in labels}
        matches = [poi for poi in usable if poi.get("category") == "mall" and name_keys(poi) & keys]
        # Different source centroids for one mall may be tens of metres apart.
        # Separate same-name mall clusters remain ambiguous; choose neither.
        if matches and all(_distance(left, right) <= 500 for left in matches for right in matches):
            anchors[scope] = matches

    def category_agrees(fact, candidate):
        left, right = fact.get("category", "other"), candidate.get("category", "other")
        return left == right or "other" in {left, right} or {left, right} <= {"cafe", "restaurant"}

    def address_proves(fact, candidate):
        left, right = fact.get("address"), candidate.get("address")
        if not isinstance(left, str) or not isinstance(right, str):
            return False
        a, b = _address_signature(left), _address_signature(right)
        return bool(a and b and a[1] and b[1] and addresses_compatible(left, right))

    attached, unresolved = [], []
    for fact in facts:
        candidates = {poi["id"]: poi for key in name_keys(fact) for poi in names.get(key, {}).values()}
        scope = source_scope.get(fact.get("source"))
        method = "mall_scope" if scope else "street_address"
        choices = []
        for match in candidates.values():
            if not category_agrees(fact, match):
                continue
            if scope:
                if not anchors.get(scope) or min(_distance(match, anchor) for anchor in anchors[scope]) > 500:
                    continue
            elif not address_proves(fact, match):
                continue
            choices.append(match)
        if len(choices) == 1:
            match = choices[0]
            attached.append({**fact, "lat": match["lat"], "lon": match["lon"],
                             "coordinate_source_id": match["id"], "coordinate_source_url": match.get("source_url"),
                             "coordinate_match_verified": True, "coordinate_match_method": method,
                             **({"coordinate_match_anchor_ids": sorted(anchor["id"] for anchor in anchors[scope])} if scope else {})})
        else:
            unresolved.append(fact)
    return attached, unresolved


class Fetcher:
    def __init__(self, raw_dir: Path, refresh: bool):
        self.raw_dir, self.refresh = raw_dir, refresh
        self.client = httpx.Client(timeout=40, follow_redirects=True, trust_env=False, headers={"User-Agent": USER_AGENT})
        self.robots = {}
        self.log = []
        self.last = 0.0
        self.failed_hosts = set()

    def close(self):
        self.client.close()

    def get(self, url: str, *, api: bool = False) -> str:
        path = self.raw_dir / (hashlib.sha256(url.encode()).hexdigest() + ".txt")
        if path.exists() and not self.refresh:
            self.log.append({"url": url, "status": "cached", "cache": path.name})
            return path.read_text()
        parsed = urlsplit(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if parsed.netloc in self.failed_hosts:
            raise RuntimeError(f"Provider {parsed.netloc} failed in this run; additional live requests skipped")
        if not api:
            if origin not in self.robots:
                robots_url = origin + "/robots.txt"
                robots_path = self.raw_dir / (hashlib.sha256(robots_url.encode()).hexdigest() + ".txt")
                if robots_path.exists() and not self.refresh:
                    response = httpx.Response(200, text=robots_path.read_text())
                else:
                    time.sleep(max(0, 1.0 - (time.monotonic()-self.last)))
                    self.last = time.monotonic()
                    response = self.client.get(robots_url)
                    if response.status_code == 200:
                        robots_path.write_text(response.text)
                    self.log.append({"url": robots_url, "status": response.status_code, "kind": "robots"})
                if response.status_code == 200:
                    parser = RobotFileParser()
                    parser.parse(response.text.splitlines())
                    self.robots[origin] = parser
                elif response.status_code in {404, 410}:
                    self.robots[origin] = None
                else:
                    raise RuntimeError(f"Cannot establish robots policy: HTTP {response.status_code}")
            policy = self.robots[origin]
            if policy and not policy.can_fetch(USER_AGENT, url):
                raise RuntimeError("Disallowed by robots.txt")
        time.sleep(max(0, 1.0 - (time.monotonic()-self.last)))
        self.last = time.monotonic()
        response = self.client.get(url)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError:
            if response.status_code in {403, 429, 500, 502, 503, 504}:
                self.failed_hosts.add(parsed.netloc)
            self.log.append({"url": url, "status": response.status_code, "retry_after": response.headers.get("Retry-After")})
            raise
        path.write_text(response.text)
        self.log.append({"url": url, "status": "downloaded", "cache": path.name,
                         "collected_at": datetime.now(timezone.utc).isoformat()})
        return response.text


DIRECTORIES = [
    ("citypass", "https://astana.citypass.kz/en/attractions", r"/attractions/[^/?#]+", "attraction"),
    ("khanshatyr", "https://khanshatyr.com/ru/food-court/kafe-restorany-i-kofeyni", r"/map/\d+/show/\d+", "cafe"),
    ("greenmall", "https://greenmall.kz/ru/brands", r"/brands/[^/?#]+", "other"),
    ("sxodim", "https://sxodim.com/astana/places/kofejni", r"/astana/place/[^/?#]+", "cafe"),
]


def _directory_facts(html, source, url, pattern, category):
    soup, found = BeautifulSoup(html, "html.parser"), {}
    for anchor in soup.find_all("a", href=True):
        href = urljoin(url, anchor["href"]).split("#")[0]
        if not re.search(pattern, urlsplit(href).path):
            continue
        name = anchor.get_text(" ", strip=True)
        heading = anchor.select_one(".brend__small-text-title") if source == "greenmall" else None
        heading = heading or anchor.find(["h2", "h3", "h4", "h5"])
        if heading:
            name = heading.get_text(" ", strip=True)
        if not name or len(name) > 140 or name.startswith("#") or name.casefold() in {"show on map", "подробнее", "на карте", "аренда"}:
            continue
        ident = hashlib.sha256(href.encode()).hexdigest()[:16]
        found[ident] = _base(source, ident, name, href, category)
        if source == "greenmall":
            hours = anchor.select_one(".brend__small-text-date")
            source_category = anchor.select_one(".brend__small-text-category")
            found[ident]["raw_tags"] = {"schedule_text": hours.get_text(" ", strip=True) if hours else None,
                                        "directory_category": source_category.get_text(" ", strip=True) if source_category else None,
                                        "mall": "Green Mall"}
    return list(found.values())


SXODIM_CATEGORIES = {
    "kofejni": "cafe", "restorany": "restaurant", "kafe-1": "cafe", "kafe": "other",
    "bary": "bar", "fastfud": "restaurant", "konditerskie": "cafe", "nochnye-kluby": "nightlife",
    "karaoke": "nightlife", "anticafe": "coworking", "biblioteki": "library",
    "dostoprimechatelnosti": "attraction", "cinemas": "cinema", "concert-halls": "theatre",
    "muzei": "museum", "teatry": "theatre", "parki-skvery-i-allei": "park",
    "torgovye-centry": "mall", "sportzaly": "sport", "akvaparki": "sport",
    "aktivnyi-otdyh": "attraction", "intellectual": "other", "prirodnye-mesta": "park",
    "banketnye-zaly": "restaurant",
}


def _save(path: Path, value) -> None:
    temporary = path.with_name("." + path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    os.replace(temporary, path)


def collect(raw_dir: Path, bbox=None, refresh: bool = False) -> dict:
    """Collect uncapped advertised directories and preserve failed provider snapshots."""
    raw_dir = Path(raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    previous = []
    for filename in ("candidates.json", "unlocated.json"):
        try:
            previous.extend(json.loads((raw_dir / filename).read_text()))
        except (OSError, ValueError):
            pass
    fetcher, errors = Fetcher(raw_dir, refresh), []
    records, metrics = {}, defaultdict(lambda: {"pages": 0, "records": 0})

    def ingest(source, values):
        for item in values:
            old = records.get(item["id"], {})
            merged = {**old, **{key: value for key, value in item.items() if value is not None}}
            if old.get("category") not in {None, "other"} and item.get("category") == "other":
                merged["category"] = old["category"]
            records[item["id"]] = merged
        metrics[source]["records"] = sum(item.get("source") == source for item in records.values())

    def failure(source, url, error):
        errors.append({"source": source, "url": url, "error": f"{type(error).__name__}: {error}"})

    providers = [("marwin", "https://www.marwin.kz/shops/", parse_marwin, False),
                 ("dodo", "https://publicapi.dodois.io/KZ/api/v1/unitinfo/all", lambda text: parse_dodo(json.loads(text)), True),
                 ("mega_silkway", "https://restaurants.mega.kz/ru/?sm=2", lambda text: parse_mega_restaurants(text, "https://restaurants.mega.kz/ru/?sm=2"), False)]
    try:
        for source, url, parser, api in providers:
            try:
                html = fetcher.get(url, api=api)
                values = parser(html)
                if source == "marwin" and not values and not ("text/x-magento-init" in html and '"astana"' in html and '"stores"' in html):
                    raise RuntimeError("Unrecognized or incomplete MARWIN store response")
                if source == "mega_silkway" and not values and "rest-card" not in html:
                    raise RuntimeError("Unrecognized MEGA restaurant directory response")
                metrics[source]["pages"] += 1
                ingest(source, values)
            except Exception as error:
                failure(source, url, error)
        for source, url, pattern, category in DIRECTORIES:
            if source in {"citypass", "sxodim"}:
                continue
            try:
                for page_url, html in iter_directory_pages(fetcher, url):
                    metrics[source]["pages"] += 1
                    values = _directory_facts(html, source, page_url, pattern, category)
                    if not values:
                        raise RuntimeError("Directory HTML contains no verified named entries; previous snapshot retained")
                    ingest(source, values)
            except Exception as error:
                failure(source, url, error)
        # The complete CityPass initialItems array is present in public hydration
        # even when only the first12 cards are rendered. Follow any real pagination
        # as well, so neither UI pagination style introduces an artificial cap.
        for url in ("https://astana.citypass.kz/en/attractions", "https://astana.citypass.kz/ru/attractions"):
            try:
                for page_url, html in iter_directory_pages(fetcher, url):
                    metrics["citypass"]["pages"] += 1
                    values = parse_citypass(html, page_url)
                    if not values:
                        raise RuntimeError("CityPass returned no parseable attraction hydration; snapshot not treated as complete")
                    ingest("citypass", values)
            except Exception as error:
                failure("citypass", url, error)
        sxodim_start = "https://sxodim.com/astana/places/kofejni"
        try:
            first = fetcher.get(sxodim_start)
            jobs = {sxodim_start: "cafe"}
            for anchor in BeautifulSoup(first, "html.parser").select("a[href]"):
                link = urljoin(sxodim_start, anchor["href"])
                parsed = urlsplit(link)
                slug = parsed.path.rstrip("/").rsplit("/", 1)[-1]
                if parsed.netloc == "sxodim.com" and parsed.path.startswith("/astana/places/") and slug in SXODIM_CATEGORIES:
                    canonical = urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))
                    jobs[canonical] = SXODIM_CATEGORIES[slug]
            metrics["sxodim"]["categories"] = len(jobs)
            for url, category in jobs.items():
                try:
                    for page_url, html in iter_directory_pages(fetcher, url):
                        metrics["sxodim"]["pages"] += 1
                        values = parse_sxodim(html, page_url, category)
                        if not values and not BeautifulSoup(html, "html.parser").select_one(".impression-items"):
                            raise RuntimeError("Sxodim returned no recognizable venue listing")
                        ingest("sxodim", values)
                except Exception as error:
                    failure("sxodim", url, error)
        except Exception as error:
            failure("sxodim", sxodim_start, error)
        # Respect this provider's robots policy; a disallowed homepage is recorded
        # as unavailable, never worked around through a different path or API.
        library_url = "https://astana-library.kz/"
        try:
            fetcher.get(library_url)
            failure("astana_library", library_url, RuntimeError("No verified structured branch directory available from homepage"))
        except Exception as error:
            failure("astana_library", library_url, error)
    finally:
        fetcher.close()
    failed_sources = {item["source"] for item in errors}
    retained = defaultdict(int)
    for old in previous:
        source = old.get("source")
        if source in failed_sources and old.get("id") not in records:
            records[old["id"]] = {**old, "stale_cache": True, "source_status": "retained_after_provider_failure"}
            retained[source] += 1
    pois, facts = [], []
    for item in records.values():
        if item.get("lat") is not None and item.get("lon") is not None:
            if bbox and not (bbox[0] <= item["lat"] <= bbox[2] and bbox[1] <= item["lon"] <= bbox[3]):
                continue
            pois.append(item)
        else:
            facts.append(item)
    pois.sort(key=lambda row: row["id"])
    facts.sort(key=lambda row: row["id"])
    report = {"status": "partial" if errors else "ok", "candidate_count": len(pois),
              "unlocated_fact_count": len(facts), "errors": errors, "requests": fetcher.log,
              "providers": dict(metrics), "retained_stale_by_provider": dict(retained),
              "with_opening_hours": sum(bool(item.get("opening_hours")) for item in pois + facts),
              "with_address": sum(bool(item.get("address")) for item in pois + facts),
              "record_limit": None,
              "licensing": "Public access is not an open-data licence. Only factual fields retained; no general redistribution licence established for these sites.",
              "coordinate_policy": "Source-provided coordinates only; unlocated facts require a unique exact-name base match later."}
    for name, value in (("candidates.json", pois), ("unlocated.json", facts), ("report.json", report)):
        _save(raw_dir / name, value)
    return {"pois": pois, "unlocated": facts, "report": report}


if __name__ == "__main__":
    result = collect(Path("data/raw/web"))
    print(json.dumps(result["report"], ensure_ascii=False, indent=2))

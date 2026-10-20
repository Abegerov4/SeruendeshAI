"""Public event catalogue, independent of recommendation venue mappings."""
from __future__ import annotations

import calendar
import json
import logging
import math
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Literal
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app import paths
from app.store import outside_astana

router = APIRouter()
LOCAL_TZ = ZoneInfo("Asia/Almaty")
log = logging.getLogger("app.event_feed")
CATEGORY_LABELS = {
    "concerts": "Концерты", "theatres": "Театр", "stand-up": "Стендап",
    "children": "Детям", "entertainment": "Развлечения", "museums": "Музеи и выставки",
    "exhibitions": "Выставки", "sports": "Спорт", "cinema": "Кино", "festivals": "Фестивали",
    "education": "Образование", "one": "События", "other": "Другое",
}


class EventSource(BaseModel):
    name: Literal["ticketon", "sxodim"]
    url: str


class EventOut(BaseModel):
    id: str
    title: str
    description: str | None
    venue: str | None
    address: str | None
    start: str | None
    end: str | None
    sessions: list[str]
    schedule_kind: Literal["continuous", "sessions"]
    price_from: float | None
    currency: str | None
    category: str
    category_label: str
    image_url: str | None
    announced_at: str | None
    first_seen_at: str | None
    sources: list[EventSource]
    is_archived: bool


class EventCategory(BaseModel):
    value: str
    label: str


class EventPage(BaseModel):
    items: list[EventOut]
    total: int
    offset: int
    limit: int
    today: str
    categories: list[EventCategory]
    months: list[str]
    updated_at: str | None


@dataclass
class FeedEvent:
    item: dict
    periods: list[tuple[datetime, datetime]]
    aliases: set[str] = field(default_factory=set)

    @property
    def ends_at(self) -> datetime:
        return max(end for _, end in self.periods)


def _now() -> datetime:
    return datetime.now(LOCAL_TZ)


def _moment(value, *, end_of_day: bool = False) -> datetime | None:
    """Naive source timestamps are local; date-only endings include the whole day."""
    if not isinstance(value, str) or not value.strip():
        return None
    value = value.strip()
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            return datetime.combine(date.fromisoformat(value), time.max if end_of_day else time.min, LOCAL_TZ)
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return (parsed if parsed.tzinfo else parsed.replace(tzinfo=LOCAL_TZ)).astimezone(LOCAL_TZ)
    except ValueError:
        return None


def _iso(value) -> str | None:
    parsed = _moment(value)
    if parsed is None:
        return None
    return parsed.date().isoformat() if len(value.strip()) == 10 else parsed.isoformat()


def _text(value) -> str | None:
    return (value.strip() or None) if isinstance(value, str) else None


def _key(value) -> str:
    return " ".join(unicodedata.normalize("NFKC", value or "").casefold().replace("ё", "е").split())


def _url(value) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = urlsplit(value)
        return value if parsed.scheme in {"https", "http"} and parsed.hostname else None
    except ValueError:
        return None


def _price(value) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
        return number if math.isfinite(number) and number >= 0 else None
    except (TypeError, ValueError, OverflowError):
        return None


def _session_values(raw: dict) -> list:
    value = raw.get("sessions")
    return value if isinstance(value, list) else []


def _schedule_kind(raw: dict) -> Literal["continuous", "sessions"]:
    explicit = _text(raw.get("schedule_kind"))
    if explicit in {"continuous", "sessions"}:
        return explicit
    sessions = {moment for value in _session_values(raw) if (moment := _moment(value)) is not None}
    start = _moment(raw.get("start"))
    if len(sessions) >= 2 or (len(sessions) == 1 and next(iter(sessions)) != start):
        return "sessions"
    return "continuous"


def _periods(raw: dict, schedule_kind: Literal["continuous", "sessions"]) -> list[tuple[datetime, datetime]]:
    start = _moment(raw.get("start"))
    end = _moment(raw.get("end"), end_of_day=True)
    sessions = sorted({moment for value in _session_values(raw) if (moment := _moment(value)) is not None})
    if schedule_kind == "continuous":
        start = start or (sessions[0] if sessions else None)
        if start is None:
            return []
        return [(start, end if end is not None and end >= start else datetime.combine(start.date(), time.max, LOCAL_TZ))]
    if not sessions:
        if start is None:
            return []
        sessions = [start]

    # A series' broad start/end envelope is not continuous opening. The final
    # explicit end can establish a short duration for individual performances.
    duration = None
    if end is not None and isinstance(raw.get("end"), str) and len(raw["end"].strip()) > 10:
        for candidate in (sessions[-1], start):
            if candidate is not None and timedelta(0) <= end - candidate < timedelta(days=1):
                duration = end - candidate
                break
    return [(session, session + duration if duration is not None else
             datetime.combine(session.date(), time.max, LOCAL_TZ)) for session in sessions]


def _normalize(raw: dict, now: datetime) -> FeedEvent | None:
    if outside_astana(raw) or outside_astana({"title": _text(raw.get("source_city"))}):
        return None
    event_id, title = _text(raw.get("id")), _text(raw.get("title"))
    source, url = _text(raw.get("source")), _url(raw.get("url"))
    schedule_kind = _schedule_kind(raw)
    periods = _periods(raw, schedule_kind)
    if not event_id or not title or source not in {"ticketon", "sxodim"} or not url or not periods:
        return None
    category = _text(raw.get("category")) or "other"
    item = {
        "id": event_id, "title": title, "description": _text(raw.get("description")),
        "venue": _text(raw.get("venue")), "address": _text(raw.get("address")),
        "start": _iso(raw.get("start")), "end": _iso(raw.get("end")),
        "sessions": sorted({value for session in _session_values(raw) if (value := _iso(session)) is not None}),
        "schedule_kind": schedule_kind,
        "price_from": _price(raw.get("price_from")), "currency": _text(raw.get("currency")),
        "category": category, "category_label": CATEGORY_LABELS.get(category, category),
        "image_url": _url(raw.get("image_url")),
        "announced_at": _iso(raw.get("published_at")) or _iso(raw.get("announced_at")),
        "first_seen_at": _iso(raw.get("first_seen_at")), "sources": [{"name": source, "url": url}],
        "is_archived": max(end for _, end in periods) < now,
    }
    return FeedEvent(item, periods, {event_id})


def _merge(target: FeedEvent, other: FeedEvent) -> None:
    """Retain source links and the earliest known announcement/discovery of a duplicate."""
    item, extra = target.item, other.item
    item["sources"].extend(source for source in extra["sources"] if source not in item["sources"])
    target.aliases.update(other.aliases)
    for name in ("description", "image_url", "address", "currency"):
        if not item[name]:
            item[name] = extra[name]
    for name in ("announced_at", "first_seen_at"):
        values = [value for value in (item[name], extra[name]) if value is not None]
        item[name] = min(values, key=_moment) if values else None
    prices = [value for value in (item["price_from"], extra["price_from"]) if value is not None]
    if item["currency"] == extra["currency"]:
        item["price_from"] = min(prices) if prices else None
    if item["category"] == "other" and extra["category"] != "other":
        item["category"], item["category_label"] = extra["category"], extra["category_label"]


def _deduplicate(events: list[FeedEvent]) -> list[FeedEvent]:
    groups: dict[tuple, list[FeedEvent]] = {}
    # Stable preference retains existing Ticketon IDs and source ordering.
    for event in sorted(events, key=lambda e: (e.item["sources"][0]["name"] != "ticketon", e.item["id"])):
        item = event.item
        identity = (_key(item["title"]), _key(item["venue"]), item["schedule_kind"], tuple(start for start, _ in event.periods))
        groups.setdefault(identity, []).append(event)
    result = []
    for candidates in groups.values():
        # More than two matching records are ambiguous; retain them for review
        # instead of choosing a same-source listing arbitrarily.
        if len(candidates) == 2:
            first, second = candidates
            addresses = _key(first.item["address"]), _key(second.item["address"])
            if first.item["venue"] and first.item["sources"][0]["name"] != second.item["sources"][0]["name"] and (
                    not all(addresses) or addresses[0] == addresses[1]):
                _merge(first, second)
                result.append(first)
                continue
        result.extend(candidates)
    return result


def _load(now: datetime) -> tuple[list[FeedEvent], str | None]:
    # The collector atomically replaces this dedicated archive independently of
    # immutable POI bundles. Reopen it per request so refreshes are visible.
    file = paths.EVENTS_FILE
    if not file.exists():
        return [], None
    events, updated = [], []
    with file.open(encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                log.warning("Ignoring malformed event JSON at %s:%d", file, line_no)
                continue
            if not isinstance(raw, dict):
                continue
            if (timestamp := _iso(raw.get("fetched_at"))) is not None:
                updated.append(timestamp)
            if (event := _normalize(raw, now)) is not None:
                events.append(event)
    return _deduplicate(events), max(updated, key=_moment) if updated else None


def _date_filter(value: str | None, name: str) -> date | None:
    if value is None:
        return None
    try:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError
        return date.fromisoformat(value)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"{name} must be a valid ISO date (YYYY-MM-DD)") from None


def _overlaps(event: FeedEvent, lower: date | None, upper: date | None) -> bool:
    if lower is not None and upper is not None and lower > upper:
        return False
    return any((upper is None or start.date() <= upper) and (lower is None or end.date() >= lower)
               for start, end in event.periods)


def _months(event: FeedEvent) -> set[str]:
    result = set()
    for start, end in event.periods:
        year, month = start.year, start.month
        while (year, month) <= (end.year, end.month):
            result.add(f"{year:04d}-{month:02d}")
            year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return result


@router.get("/api/events", tags=["events"], response_model=EventPage, summary="Astana event announcements and archive")
def list_events(
    view: Literal["upcoming", "archive"] = "upcoming",
    q: str | None = Query(None, max_length=500),
    category: str | None = Query(None, max_length=100),
    source: Literal["ticketon", "sxodim"] | None = None,
    price: Literal["all", "free", "paid"] = "all",
    date_from: str | None = None,
    date_to: str | None = None,
    month: str | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
):
    lower, upper = _date_filter(date_from, "date_from"), _date_filter(date_to, "date_to")
    if lower is not None and upper is not None and lower > upper:
        raise HTTPException(status_code=422, detail="date_from must not be later than date_to")
    if month is not None:
        first = _date_filter(month + "-01", "month")
        if view == "archive":
            last = first.replace(day=calendar.monthrange(first.year, first.month)[1])
            lower = max(lower, first) if lower else first
            upper = min(upper, last) if upper else last

    now = _now().astimezone(LOCAL_TZ)
    events, updated_at = _load(now)
    categories = {event.item["category"]: event.item["category_label"] for event in events}
    months = sorted({month for event in events if event.item["is_archived"] for month in _months(event)}, reverse=True)
    matches = []
    query = _key(q)
    for event in events:
        item = event.item
        if item["is_archived"] != (view == "archive"):
            continue
        if category and item["category"] != category:
            continue
        if source and not any(link["name"] == source for link in item["sources"]):
            continue
        if price == "free" and item["price_from"] != 0:
            continue
        if price == "paid" and (item["price_from"] is None or item["price_from"] <= 0):
            continue
        if query and query not in _key(" ".join(item.get(name) or "" for name in ("title", "description", "venue", "address"))):
            continue
        if not _overlaps(event, lower, upper):
            continue
        matches.append(event)
    matches.sort(key=lambda event: event.item["id"])
    matches.sort(key=lambda event: event.ends_at if view == "archive" else
                 (_moment(event.item["announced_at"] or event.item["first_seen_at"]) or datetime.min.replace(tzinfo=LOCAL_TZ)),
                 reverse=True)
    return {"items": [event.item for event in matches[offset:offset + limit]], "total": len(matches),
            "offset": offset, "limit": limit, "today": now.date().isoformat(), "updated_at": updated_at,
            "categories": [{"value": value, "label": label} for value, label in sorted(categories.items())], "months": months}


@router.get("/api/events/{event_id}", tags=["events"], response_model=EventOut, summary="Event details including all source links")
def event_detail(event_id: str):
    events, _ = _load(_now().astimezone(LOCAL_TZ))
    for event in events:
        if event_id in event.aliases:
            return event.item
    raise HTTPException(status_code=404, detail="Event not found")

"""Visitors' marks on a place: a weak evidence tier next to the collected hours.

Stored: day | place | kind -> count (db.PlaceReport). No person, text, position or time of day.
Rules for how much a mark may say:
- only «was closed» and «wrong hours» touch the hours, and only downwards: they lower the confidence of
  «open» and, when several are fresh, turn it into «unknown»; they never turn «closed» into «open»;
- a mark is ignored after 30 days and its weight halves every 14 days;
- a place counts at most 3 marks a day, and one client marks one place once in 12 hours (main.api_feedback).
"""
from __future__ import annotations

import datetime as dt
import logging
import threading

from app import db

log = logging.getLogger("app.feedback")
HOURS_KINDS = ("closed", "wrong_hours")
MAX_AGE_DAYS, HALF_LIFE_DAYS, DAILY_CAP = 30, 14, 3
DOUBT_LOWER, DOUBT_UNKNOWN = 1.0, 2.5  # one fresh mark lowers confidence; about three fresh ones make «open» unknown

_marks: dict[str, dict[tuple[str, str], int]] = {}  # poi -> (day, kind) -> hits, the last 30 days
_loaded = False
_lock = threading.Lock()


def _load() -> None:
    global _loaded
    with _lock:
        if _loaded:
            return
        _loaded = True
        try:
            if db.SessionLocal is None:
                db.init_db()
            since = (dt.date.today() - dt.timedelta(days=MAX_AGE_DAYS)).isoformat()
            with db.SessionLocal() as s:
                for r in s.query(db.PlaceReport).filter(db.PlaceReport.day >= since):
                    _marks.setdefault(r.poi_id, {})[(r.day, r.kind)] = r.hits
        except Exception as exc:  # marks are optional evidence: answers work without them
            log.warning("place reports not loaded: %s", type(exc).__name__)


def record(poi_id: str, kind: str, today: dt.date | None = None) -> None:
    _load()
    day = (today or dt.date.today()).isoformat()
    with _lock:
        per = _marks.setdefault(poi_id, {})
        per[(day, kind)] = per.get((day, kind), 0) + 1
    try:
        with db.SessionLocal.begin() as session:
            dialect = session.bind.dialect.name
            if dialect == "sqlite":
                from sqlalchemy.dialects.sqlite import insert
            elif dialect == "postgresql":
                from sqlalchemy.dialects.postgresql import insert
            else:
                return
            stmt = insert(db.PlaceReport).values(key=f"{day}|{poi_id}|{kind}", day=day, poi_id=poi_id, kind=kind, hits=1)
            session.execute(stmt.on_conflict_do_update(index_elements=[db.PlaceReport.key],
                                                       set_={"hits": db.PlaceReport.hits + 1}))
    except Exception as exc:
        log.warning("place report not stored: %s", type(exc).__name__)


def doubt(poi_id: str | None, on: dt.date) -> float:
    """Weighted fresh «closed / wrong hours» marks for a place on a given day (0 = none)."""
    if not poi_id:
        return 0.0
    if not _loaded:
        _load()
    score = 0.0
    for (day, kind), hits in (_marks.get(poi_id) or {}).items():
        if kind not in HOURS_KINDS:
            continue
        age = (on - dt.date.fromisoformat(day)).days
        if 0 <= age <= MAX_AGE_DAYS:
            score += min(hits, DAILY_CAP) * 0.5 ** (age / HALF_LIFE_DAYS)
    return score


def counts(poi_id: str) -> dict[str, int]:
    _load()
    out: dict[str, int] = {}
    for (_, kind), hits in (_marks.get(poi_id) or {}).items():
        out[kind] = out.get(kind, 0) + hits
    return out


def reset() -> None:
    """Tests: forget the in-memory mirror."""
    global _loaded
    with _lock:
        _marks.clear()
        _loaded = False

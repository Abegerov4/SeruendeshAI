"""Opening-hours status with an explicit confidence level.

Rules (never claim "open" without data):
- parsed opening_hours -> open/closing_soon/closed; confidence high only for dated source evidence,
  otherwise low; on a public holiday a schedule without its own PH rule says nothing about today: «open»
  becomes «unknown» with the usual hours as a hint (closed stays closed, with lower confidence);
- no hours: a playground, a monument or an unfenced park is an «open public space» (status always); else "unknown", low.
"""
from __future__ import annotations

import datetime as dt
import re
from functools import lru_cache

import opening_hours as oh

from app import feedback
from app.i18n import t
from app.config import get_settings

_DOWN = {"high": "medium", "medium": "low", "low": "low"}


@lru_cache(maxsize=4096)
def _parse(raw: str):
    try:
        return oh.OpeningHours(raw, country="KZ")
    except Exception:
        return None


@lru_cache(maxsize=4096)
def _state_at(raw: str, arrive: dt.datetime) -> tuple[str, dt.datetime | None]:
    """Share expensive transition lookup at the exact local arrival time.

    Only immutable parser results are cached. Visit duration, evidence freshness,
    holiday confidence and translated labels remain per-call decisions below.
    Exceptions propagate so a transient parser failure can be retried.
    """
    o = _parse(raw)
    state = o.state(arrive)[0]
    return getattr(state, "name", str(state)).upper(), o.next_change(arrive)


_DAYS = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]


@lru_cache(maxsize=4096)
def _week_calendar(raw: str) -> bytes | None:
    """Cached simple weekly calendar for conservative overnight-tail recovery."""
    import re
    cal = bytearray(7 * 1440)
    try:
        for rule in raw.split(";"):
            m = re.fullmatch(r"\s*(?:(\w{2}(?:-\w{2})?(?:,\w{2}(?:-\w{2})?)*)\s+)?(off|closed|\d{1,2}:\d{2}-\d{1,2}:\d{2}(?:,\s*\d{1,2}:\d{2}-\d{1,2}:\d{2})*)\s*", rule)
            if not m:
                return None
            days = set()
            for item in (m[1] or "Mo-Su").split(","):
                a, b = item.split("-")[0], item.split("-")[-1]
                i, j = _DAYS.index(a), _DAYS.index(b)
                days.update((i + k) % 7 for k in range((j - i) % 7 + 1))
            for d in days:
                cal[d * 1440:(d + 1) * 1440] = bytes(1440)
            if m[2] in ("off", "closed"):
                continue
            for span in m[2].split(","):
                s_, e_ = [int(x.split(":")[0]) * 60 + int(x.split(":")[1]) for x in span.strip().split("-")]
                if e_ <= s_:
                    e_ += 1440
                for d in days:
                    for minute in range(s_, e_):
                        cal[(d * 1440 + minute) % len(cal)] = 1
    except (ValueError, IndexError):
        return None
    return bytes(cal)


def _calendar_open(raw: str, when: dt.datetime) -> bool | None:
    cal = _week_calendar(raw)
    if cal is None:
        return None
    return bool(cal[when.weekday() * 1440 + when.hour * 60 + when.minute])


def _fmt_day(d: dt.datetime, ref: dt.datetime, lang: str) -> str:
    if d.date() == ref.date():
        return t("today", lang)
    if d.date() == ref.date() + dt.timedelta(days=1):
        return t("tomorrow", lang)
    return d.strftime("%d.%m")


OPEN_SPACE = {"playground", "monument", "artwork", "park"}
# parks that have gates, tickets or hours of their own are not «open space» even without listed hours
_GATED = re.compile(r"ботани|botanic|зоо|zoo|дендро|аттракцион|amusement|аквапарк|water ?park|ипподром|стадион|stadium|"
                    r"этнопарк|ethno|сафари|контакт|keruen|хан шатыр|khan shatyr", re.I)


_SQUARE = re.compile(r"сквер|бульвар|аллея|саябақ|гүлзар|square|boulevard|alley", re.I)  # a «garden» that is a city square


def open_space(poi: dict) -> bool:
    """A playground, a monument or an unfenced city park: you can come at any time, there are no opening hours."""
    feats = poi.get("features") or {}
    name = poi.get("name") or ""
    kind_ok = poi.get("category") in OPEN_SPACE or (poi.get("category") == "garden" and _SQUARE.search(name))
    return (kind_ok and not _GATED.search(name)
            and feats.get("fee") is not True and poi.get("access") not in ("private", "customers", "no"))


def opening_status(poi: dict, arrive: dt.datetime, visit_min: int, lang: str, holiday: str | None) -> dict:
    """arrive: naive local time (Asia/Almaty). Returns the API `Opening` dict + `ok` for filtering."""
    raw = poi.get("opening_hours")
    if not raw and open_space(poi):  # shown as «open public space», never as «open» (the contract says unknown)
        return {"status": "always", "confidence": "medium", "label": t("oh_always", lang), "raw": None,
                "next_change": None, "ok": True}
    if not raw:
        return {"status": "unknown", "confidence": "low", "label": t("oh_unknown", lang), "raw": None,
                "next_change": None, "ok": True}
    o = _parse(raw)
    if o is None:
        return {"status": "unknown", "confidence": "low", "label": t("oh_unparsed", lang, raw=raw[:60]), "raw": raw,
                "next_change": None, "ok": True}
    conf = "low"
    source = (poi.get("hours_source") or "").strip()
    cd = poi.get("check_date")
    if cd:
        try:
            age = (arrive.date() - dt.date.fromisoformat(cd[:10])).days
            if source and poi.get("hours_source_url") and 0 <= age <= getattr(get_settings(), "hours_max_age_days", 180):
                conf = "high"
        except ValueError:
            pass
    suffix = t("oh_src", lang) if source.lower() in {"osm", "openstreetmap"} else (
        t("oh_source", lang, source=source) if source else "")
    if holiday:
        conf = _DOWN[conf]
        suffix += t("oh_holiday", lang)
    doubt = feedback.doubt(poi.get("id"), arrive.date())  # visitors' «was closed / wrong hours» marks, weak evidence
    if doubt >= feedback.DOUBT_LOWER:
        conf = _DOWN[conf]
        suffix += t("oh_reported", lang)
    try:
        name, nxt = _state_at(raw, arrive)
    except Exception:
        return {"status": "unknown", "confidence": "low", "label": t("oh_unparsed", lang, raw=raw[:60]), "raw": raw,
                "next_change": None, "ok": True}
    if name == "CLOSED" and arrive.hour < 6 and _calendar_open(raw, arrive):
        name, conf = "OPEN", _DOWN[conf]
        # The parser's next transition was a future OPENING. Recover the actual
        # closing boundary from the same calendar that established the tail.
        minute = arrive.replace(second=0, microsecond=0)
        nxt = next((minute + dt.timedelta(minutes=i) for i in range(1, 7 * 1440 + 1)
                    if not _calendar_open(raw, minute + dt.timedelta(minutes=i))), None)
    nxt_s = nxt.strftime("%H:%M") if isinstance(nxt, dt.datetime) else None
    if name == "OPEN" and doubt >= feedback.DOUBT_UNKNOWN:  # marks may only lower trust, never open a closed place
        return {"status": "unknown", "confidence": "low", "label": t("oh_reported_unknown", lang), "raw": raw,
                "next_change": nxt_s, "ok": True}
    if raw.strip() == "24/7":
        return {"status": "open", "confidence": conf, "label": t("oh_open", lang) + " · 24/7" + suffix, "raw": raw,
                "next_change": None, "ok": True}
    if name == "OPEN" and holiday and "PH" not in raw:
        usual = t("oh_open_until", lang, t=nxt_s) if nxt_s else t("oh_open", lang)
        usual = usual[:1].lower() + usual[1:]
        return {"status": "unknown", "confidence": "low", "label": t("oh_holiday_unknown", lang, usual=usual), "raw": raw,
                "next_change": nxt_s, "ok": True}
    if name == "OPEN":
        end = arrive + dt.timedelta(minutes=visit_min)
        if isinstance(nxt, dt.datetime) and nxt < end:
            on_site = int((nxt - arrive).total_seconds() // 60)
            return {"status": "closing_soon", "confidence": conf, "label": t("oh_closing_soon", lang, t=nxt_s, m=on_site) + suffix,
                    "raw": raw, "next_change": nxt_s, "ok": on_site >= visit_min, "minutes_left": on_site}
        lbl = t("oh_open_until", lang, t=nxt_s) if nxt_s and isinstance(nxt, dt.datetime) and (nxt - arrive).days < 1 else t("oh_open", lang)
        return {"status": "open", "confidence": conf, "label": lbl + suffix, "raw": raw, "next_change": nxt_s, "ok": True}
    if name == "CLOSED":
        if isinstance(nxt, dt.datetime) and (nxt - arrive).days < 7:
            lbl = t("oh_closed_until", lang, d=_fmt_day(nxt, arrive, lang), t=nxt_s)
        else:
            lbl = t("oh_closed", lang)
        return {"status": "closed", "confidence": conf, "label": lbl + suffix, "raw": raw, "next_change": nxt_s, "ok": False}
    return {"status": "unknown", "confidence": "low", "label": t("oh_unknown", lang), "raw": raw, "next_change": nxt_s, "ok": True}

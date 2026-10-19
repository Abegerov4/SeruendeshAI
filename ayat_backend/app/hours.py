"""Opening-hours status with an explicit confidence level.

Rules (never claim "open" without data):
- parsed opening_hours -> open/closing_soon/closed; confidence high only for dated source evidence,
  otherwise low; public holidays lower it one step (the parser does not know transferred days off);
- no hours otherwise -> "unknown", low.
"""
from __future__ import annotations

import datetime as dt
from functools import lru_cache

import opening_hours as oh

from ayat_backend.app.i18n import t
from ayat_backend.app.config import get_settings

_DOWN = {"high": "medium", "medium": "low", "low": "low"}


@lru_cache(maxsize=4096)
def _parse(raw: str):
    try:
        return oh.OpeningHours(raw, country="KZ")
    except Exception:
        return None


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


def opening_status(poi: dict, arrive: dt.datetime, visit_min: int, lang: str, holiday: str | None) -> dict:
    """arrive: naive local time (Asia/Almaty). Returns the API `Opening` dict + `ok` for filtering."""
    raw = poi.get("opening_hours")
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
    try:
        state = o.state(arrive)[0]
        nxt = o.next_change(arrive)
    except Exception:
        return {"status": "unknown", "confidence": "low", "label": t("oh_unparsed", lang, raw=raw[:60]), "raw": raw,
                "next_change": None, "ok": True}
    name = getattr(state, "name", str(state)).upper()
    if name == "CLOSED" and arrive.hour < 6 and _calendar_open(raw, arrive):
        name, conf = "OPEN", _DOWN[conf]
        # The parser's next transition was a future OPENING. Recover the actual
        # closing boundary from the same calendar that established the tail.
        minute = arrive.replace(second=0, microsecond=0)
        nxt = next((minute + dt.timedelta(minutes=i) for i in range(1, 7 * 1440 + 1)
                    if not _calendar_open(raw, minute + dt.timedelta(minutes=i))), None)
    nxt_s = nxt.strftime("%H:%M") if isinstance(nxt, dt.datetime) else None
    if raw.strip() == "24/7":
        return {"status": "open", "confidence": conf, "label": t("oh_open", lang) + " · 24/7" + suffix, "raw": raw,
                "next_change": None, "ok": True}
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

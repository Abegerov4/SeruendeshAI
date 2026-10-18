"""Opening-hours status with an explicit confidence level.

Rules (never claim "open" without data):
- parsed OSM opening_hours -> open/closing_soon/closed; confidence high if check_date <= 12 months,
  else medium; public holidays lower it one step (the parser does not know transferred days off);
- no hours + open public space (park, square, monument, playground) -> "always", medium;
- no hours otherwise -> "unknown", low.
"""
from __future__ import annotations

import datetime as dt
from functools import lru_cache

import opening_hours as oh

from app.i18n import t

ALWAYS_OPEN_CATS = {"park", "garden", "playground", "monument", "artwork"}
OUTDOOR_LANDMARK = {"landmark", "viewpoint"}
_DOWN = {"high": "medium", "medium": "low", "low": "low"}


@lru_cache(maxsize=4096)
def _parse(raw: str):
    try:
        return oh.OpeningHours(raw, country="KZ")
    except Exception:
        return None


def _fmt_day(d: dt.datetime, ref: dt.datetime, lang: str) -> str:
    if d.date() == ref.date():
        return t("today", lang)
    if d.date() == ref.date() + dt.timedelta(days=1):
        return t("tomorrow", lang)
    return d.strftime("%d.%m")


def opening_status(poi: dict, arrive: dt.datetime, visit_min: int, lang: str, holiday: str | None) -> dict:
    """arrive: naive local time (Asia/Almaty). Returns the API `Opening` dict + `ok` for filtering."""
    raw = poi.get("opening_hours")
    cat = poi["category"]
    if not raw:
        if cat in ALWAYS_OPEN_CATS or (cat in OUTDOOR_LANDMARK and not poi.get("indoor")):
            return {"status": "always", "confidence": "medium", "label": t("oh_always", lang), "raw": None,
                    "next_change": None, "ok": True}
        return {"status": "unknown", "confidence": "low", "label": t("oh_unknown", lang), "raw": None,
                "next_change": None, "ok": True}
    o = _parse(raw)
    if o is None:
        return {"status": "unknown", "confidence": "low", "label": t("oh_unparsed", lang, raw=raw[:60]), "raw": raw,
                "next_change": None, "ok": True}
    conf = "medium"
    cd = poi.get("check_date")
    if cd:
        try:
            if (arrive.date() - dt.date.fromisoformat(cd[:10])).days <= 365:
                conf = "high"
        except ValueError:
            pass
    suffix = t("oh_src", lang)
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
    nxt_s = nxt.strftime("%H:%M") if isinstance(nxt, dt.datetime) else None
    if raw.strip() == "24/7":
        return {"status": "open", "confidence": conf, "label": t("oh_open", lang) + " · 24/7" + suffix, "raw": raw,
                "next_change": None, "ok": True}
    if name == "OPEN":
        end = arrive + dt.timedelta(minutes=visit_min)
        if isinstance(nxt, dt.datetime) and nxt < end:
            on_site = int((nxt - arrive).total_seconds() // 60)
            return {"status": "closing_soon", "confidence": conf, "label": t("oh_closing_soon", lang, t=nxt_s, m=on_site) + suffix,
                    "raw": raw, "next_change": nxt_s, "ok": on_site >= 15, "minutes_left": on_site}
        lbl = t("oh_open_until", lang, t=nxt_s) if nxt_s and isinstance(nxt, dt.datetime) and (nxt - arrive).days < 1 else t("oh_open", lang)
        return {"status": "open", "confidence": conf, "label": lbl + suffix, "raw": raw, "next_change": nxt_s, "ok": True}
    if name == "CLOSED":
        if isinstance(nxt, dt.datetime) and (nxt - arrive).days < 7:
            lbl = t("oh_closed_until", lang, d=_fmt_day(nxt, arrive, lang), t=nxt_s)
        else:
            lbl = t("oh_closed", lang)
        return {"status": "closed", "confidence": conf, "label": lbl + suffix, "raw": raw, "next_change": nxt_s, "ok": False}
    return {"status": "unknown", "confidence": "low", "label": t("oh_unknown", lang), "raw": raw, "next_change": nxt_s, "ok": True}

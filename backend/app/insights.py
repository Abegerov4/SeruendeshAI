"""City Insights for the akimat / Smart City centre: what people look for, where and when, and where the city
does not answer. Only counters are stored (≈1 km cell, 3-hour slot, intent, answered or not) — no query text,
no coordinates finer than a cell, no person. A cell or an intent is published only from K requests up."""
from __future__ import annotations

import datetime as dt
import logging

from sqlalchemy import delete, select

from app import db
from app.categories import CATEGORIES, label

log = logging.getLogger("seru.insights")
K = 5            # k-anonymity threshold for anything published
CELL = 0.01      # degrees: ≈1.1 km north–south, ≈0.7 km east–west in Astana
KEEP_DAYS = 90
NEED_LABELS = {"wifi": {"ru": "Wi-Fi", "kk": "Wi-Fi", "en": "Wi-Fi"},
               "power_outlets": {"ru": "розетки", "kk": "розетка", "en": "power outlets"},
               "quiet": {"ru": "тишина", "kk": "тыныштық", "en": "quiet"},
               "wheelchair": {"ru": "доступная среда", "kk": "қолжетімді орта", "en": "step-free access"},
               "kids": {"ru": "с детьми", "kk": "балалармен", "en": "with kids"},
               "free": {"ru": "бесплатно", "kk": "тегін", "en": "free"},
               "view": {"ru": "вид на город", "kk": "қала көрінісі", "en": "city view"},
               "walk": {"ru": "прогулка", "kk": "серуен", "en": "walk"},
               "event": {"ru": "события", "kk": "іс-шаралар", "en": "events"},
               "food": {"ru": "поесть", "kk": "тамақтану", "en": "eat"},
               "any": {"ru": "без уточнения", "kk": "нақтыламай", "en": "anything"}}


def intent_label(key: str, lang: str = "ru") -> str:
    if key in CATEGORIES:
        return label(key, lang)
    return NEED_LABELS.get(key, {}).get(lang) or key


def intents_of(used: dict) -> list[str]:
    q = used.get("parsed_from_query") or {}
    out = [c for c in q.get("categories") or [] if c in CATEGORIES][:2]
    out += [n for n in q.get("needs") or [] if n in NEED_LABELS and n != "kids"][:1]
    if "kids" in (q.get("needs") or []) or used.get("party") == "family_kids":
        out.append("kids")
    if q.get("food_requirements") and not out:
        out.append("food")
    return list(dict.fromkeys(out))[:3] or ["any"]


def record(resp: dict) -> None:
    """Count one answered request; never raises into the request path."""
    try:
        used = resp.get("used_context") or {}
        loc = used.get("location") or {}
        if resp.get("off_topic") or loc.get("lat") is None or not used.get("now") or loc.get("source") == "home":
            return
        now = dt.datetime.fromisoformat(used["now"])
        cell = (round(round(loc["lat"] / CELL) * CELL, 4), round(round(loc["lon"] / CELL) * CELL, 4))
        shown = (used.get("funnel") or {}).get("shown", len(resp.get("recommendations") or []))
        unmet = int(not shown or bool(used.get("relaxations")))
        day, slot = now.date().isoformat(), now.hour // 3
        if db.SessionLocal is None:
            db.init_db()
        with db.SessionLocal.begin() as session:
            dialect = session.bind.dialect.name
            if dialect == "sqlite":
                from sqlalchemy.dialects.sqlite import insert
            elif dialect == "postgresql":
                from sqlalchemy.dialects.postgresql import insert
            else:
                return
            for intent in ["*", *intents_of(used)]:  # "*" counts the request itself once
                key = f"{day}|{cell[0]}|{cell[1]}|{slot}|{intent}|{unmet}"
                stmt = insert(db.DemandCount).values(key=key, day=day, cell_lat=cell[0], cell_lon=cell[1], slot=slot,
                                                     intent=intent, unmet=unmet, hits=1)
                session.execute(stmt.on_conflict_do_update(index_elements=[db.DemandCount.key],
                                                           set_={"hits": db.DemandCount.hits + 1}))
    except Exception as exc:  # analytics must never break a recommendation
        log.warning("insights record skipped: %s", type(exc).__name__)


def summary(days: int = 30, lang: str = "ru", today: dt.date | None = None) -> dict:
    if db.SessionLocal is None:
        db.init_db()
    today = today or dt.date.today()
    since = (today - dt.timedelta(days=days - 1)).isoformat()
    with db.SessionLocal.begin() as session:
        session.execute(delete(db.DemandCount).where(db.DemandCount.day < (today - dt.timedelta(days=KEEP_DAYS)).isoformat()))
        rows = session.execute(select(db.DemandCount).where(db.DemandCount.day >= since)).scalars().all()
        rows = [(r.cell_lat, r.cell_lon, r.slot, r.intent, r.unmet, r.hits, r.day) for r in rows]
    cells: dict[tuple, list[int]] = {}
    cell_intents: dict[tuple, dict[str, int]] = {}
    intents: dict[str, list[int]] = {}
    slots = [0] * 8
    for lat, lon, slot, intent, unmet, hits, _ in rows:
        if intent == "*":
            c = cells.setdefault((lat, lon), [0, 0])
            c[0] += hits
            c[1] += hits * unmet
            slots[slot] += hits
        else:
            ci = cell_intents.setdefault((lat, lon), {})
            ci[intent] = ci.get(intent, 0) + hits
            it = intents.setdefault(intent, [0, 0])
            it[0] += hits
            it[1] += hits * unmet
    published = {k: v for k, v in cells.items() if v[0] >= K}
    total = sum(v[0] for v in cells.values())
    return {
        "k": K, "cell_km": 1, "days": days, "since": since, "until": today.isoformat(),
        "requests": total,
        "suppressed_requests": total - sum(v[0] for v in published.values()),
        "cells": [{"lat": lat, "lon": lon, "requests": n, "unmet_share": round(u / n, 2),
                   "top": [intent_label(i, lang) for i, h in sorted(cell_intents.get((lat, lon), {}).items(),
                                                                    key=lambda x: -x[1]) if h >= K and i != "any"][:3]}
                  for (lat, lon), (n, u) in sorted(published.items(), key=lambda x: -x[1][0])],
        "intents": [{"key": i, "label": intent_label(i, lang), "requests": n, "unmet_share": round(u / n, 2)}
                    for i, (n, u) in sorted(intents.items(), key=lambda x: -x[1][0]) if n >= K and i != "any"],
        "unmet_share": round(sum(v[1] for v in cells.values()) / total, 2) if total >= K else None,
        "slots": [{"from": f"{i * 3:02d}:00", "to": f"{i * 3 + 3:02d}:00", "requests": n} for i, n in enumerate(slots)]
                 if total >= K else [],
        "privacy": "Только счётчики: ячейка ≈1 км, интервал 3 часа, тип запроса. Текст запросов, точные координаты "
                   "и пользователи не сохраняются. Показываются только значения от K запросов.",
    }

"""Mock-реализация интерфейса rag.* (team/README.md §3.2) поверх фикстуры.

Нужна, чтобы бэкенд работал до merge ветки feature/data-rag. Поиск — простой keyword + близость.
"""
import json
import math
import re
from datetime import datetime, time
from functools import lru_cache

from .config import get_settings

LANDMARKS = {
    "mega silk way": (51.0891, 71.4071, "ТРЦ Mega Silk Way"),
    "мега силк вей": (51.0891, 71.4071, "ТРЦ Mega Silk Way"),
    "мега": (51.0891, 71.4071, "ТРЦ Mega Silk Way"),
    "экспо": (51.0893, 71.4158, "EXPO / Nur Alem"),
    "expo": (51.0893, 71.4158, "EXPO / Nur Alem"),
    "нур алем": (51.0893, 71.4158, "EXPO / Nur Alem"),
    "байтерек": (51.1283, 71.4305, "Байтерек"),
    "bayterek": (51.1283, 71.4305, "Байтерек"),
    "хан шатыр": (51.1324, 71.4036, "ТРЦ Хан Шатыр"),
    "khan shatyr": (51.1324, 71.4036, "ТРЦ Хан Шатыр"),
    "аэропорт": (51.0222, 71.4669, "Аэропорт Нурсултан Назарбаев"),
    "airport": (51.0222, 71.4669, "Аэропорт Нурсултан Назарбаев"),
    "нурлы жол": (51.1124, 71.5310, "Вокзал Нурлы Жол"),
    "ак орда": (51.1257, 71.4462, "Ак Орда"),
}


@lru_cache
def load_pois() -> list[dict]:
    return json.loads(get_settings().fixture_path.read_text(encoding="utf-8"))


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> int:
    r = 6_371_000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return int(2 * r * math.asin(math.sqrt(a)))


def resolve_landmark(text: str) -> dict | None:
    low = text.lower()
    for alias in sorted(LANDMARKS, key=len, reverse=True):
        if alias in low:
            lat, lon, label = LANDMARKS[alias]
            return {"lat": lat, "lon": lon, "label": label}
    for p in load_pois():  # точное имя POI в тексте
        if p["name"].lower() in low:
            return {"lat": p["lat"], "lon": p["lon"], "label": p["name"]}
    return None


# --- opening_hours: только частые форматы OSM, всё остальное -> unknown ---
_DAYS = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]


def _days(spec: str) -> set[int]:
    out: set[int] = set()
    for part in spec.split(","):
        if "-" in part:
            a, b = part.split("-")
            i, j = _DAYS.index(a), _DAYS.index(b)
            out.update(range(i, j + 1) if i <= j else [*range(i, 7), *range(0, j + 1)])
        else:
            out.add(_DAYS.index(part))
    return out


def _t(s: str) -> time:
    h, m = map(int, s.split(":"))
    return time(23, 59) if h == 24 else time(h, m)


def open_status(opening_hours: str | None, dt: datetime) -> tuple[str, str]:
    if not opening_hours:
        return "unknown", "none"
    oh = opening_hours.strip()
    if oh == "24/7":
        return "open", "high"
    try:
        now_t, wd = dt.time(), dt.weekday()
        matched_any = False
        for rule in oh.split(";"):
            m = re.fullmatch(r"\s*([A-Za-z,\-]+)\s+(\d{1,2}:\d{2})-(\d{1,2}:\d{2})\s*", rule)
            if not m:
                return "unknown", "none"
            days, start, end = _days(m.group(1)), _t(m.group(2)), _t(m.group(3))
            if start <= end:
                if wd in days:
                    matched_any = True
                    if start <= now_t <= end:
                        return "open", "high"
            else:  # через полночь: Fr 20:00-02:00
                if wd in days and now_t >= start:
                    return "open", "high"
                if (wd - 1) % 7 in days and now_t <= end:
                    return "open", "high"
                matched_any = matched_any or wd in days
        return "closed", "high" if matched_any else "low"
    except (ValueError, IndexError):
        return "unknown", "none"


def _tokens(s: str) -> set[str]:
    return {w[:5] for w in re.findall(r"\w+", s.lower()) if len(w) > 2}


def search(query: str, lat: float | None, lon: float | None, radius_m: int = 2000,
           categories: list[str] | None = None, top_k: int = 15) -> list[dict]:
    q = _tokens(query)
    hits = []
    for p in load_pois():
        dist = haversine_m(lat, lon, p["lat"], p["lon"]) if lat is not None and lon is not None else None
        if dist is not None and dist > radius_m:
            continue
        if categories and p["category"] not in categories:
            continue
        text = " ".join([p["name"], p.get("name_en") or "", p["category"], " ".join(p.get("tags", [])),
                         p.get("description") or ""])
        overlap = len(q & _tokens(text))
        closeness = 1 - dist / radius_m if dist is not None else 0.5
        score = overlap + 0.5 * closeness + 0.1 * (p.get("rating") or 0) / 5
        hits.append({**p, "distance_m": dist, "score": round(score, 4)})
    hits.sort(key=lambda h: h["score"], reverse=True)
    return hits[:top_k]

"""Places and opening hours from sxodim.com/astana (`python -m pipeline.sxodim <crawl.jsonl>`).

sxodim's terms allow non-commercial use with an active link to the site (intro and §7.1 of
sxodim.com/polzovatelskoe-soglashenie); robots.txt allows crawling. Every fact taken from it keeps its page URL.
The crawl (name, address, coordinates, the hours line and the card's dateModified) is kept as a source snapshot
in data/sources/sxodim/. Two outputs:
- data/sources/place_research/batch_8_output.json: hours for our places that have none (matched ≤150 m with the
  same distinctive name), fed to pipeline.place_facts like any other research wave. Cards are often years old:
  a card older than a year gives confidence «low», and the note says the card's date;
- new places appended to data/processed/pois.jsonl (id «sx:<slug>»), only when another source confirms the place
  still exists (Overture or the 2GIS export lists it within 150 m under the same name) or the card was updated
  since 2024 — an old card alone may describe a closed venue. Re-run `pipeline.cli embed` afterwards.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import math
import re
import sys
from pathlib import Path

from rapidfuzz import fuzz

from app.categories import CATEGORIES
from app.hours import _parse
from app.paths import DATA_DIR, MANIFEST_FILE, POIS_FILE, PROCESSED_DIR
from pipeline.common import write_jsonl
from pipeline.twogis import DEFAULT_SOURCE, key, load

log = logging.getLogger("pipeline.sxodim")
TODAY = dt.date(2026, 10, 20)
SNAPSHOT = DATA_DIR / "sources" / "sxodim" / "places_2026-10-20.jsonl"
BATCH = DATA_DIR / "sources" / "place_research" / "batch_8_output.json"
CATEGORY = {"muzei": "museum", "biblioteki": "library", "cinemas": "cinema", "kinorumy": "cinema",
            "concert-halls": "event_venue", "dostoprimechatelnosti": "landmark", "karaoke": "karaoke", "bary": "bar",
            "kafe": "cafe", "kafe-1": "cafe", "kofejni": "cafe", "konditerskie": "sweets", "restorany": "restaurant",
            "fastfud": "fast_food", "torgovye-centry": "mall", "parki-skvery-i-allei": "park", "anticafe": "cafe",
            "nochnye-kluby": "nightclub", "aktivnyi-otdyh": "active", "akvaparki": "water_park", "spa-tsentry": "spa",
            "kvesty-1": "active"}
DAYS = {"пн": "Mo", "вт": "Tu", "ср": "We", "чт": "Th", "пт": "Fr", "сб": "Sa", "вс": "Su"}
TIME = r"(\d{1,2})[:.](\d{2})\s*[-–—]\s*(\d{1,2})[:.](\d{2})"
GENERIC_WORDS = {"ресторанный", "ресторан", "комплекс", "кафе", "бар", "кофейня", "кинотеатр", "музей", "галерея", "центр",
                 "астана", "astana", "lounge", "restaurant", "cafe", "coffee", "гриль", "grill", "паб", "pub", "сеть", "тц", "трц"}
ASTANA = (50.8576, 71.2179, 51.3512, 71.7852)


def _t(h, m):
    return f"{int(h):02d}:{m}"


def to_osm(text: str) -> str | None:
    """«Пн-Пт 10:00–18:00, Сб-Вс выходной» -> «Mo-Fr 10:00-18:00; Sa-Su off». None when the line is not plain."""
    t = text.lower().replace("ё", "е")
    t = re.sub(r"санитарн\w* д\w*[^,;]*", "", t)  # the sanitary day is a note, not a weekly rule
    t = re.sub(r"\bс\s+(\d{1,2}[:.]\d{2})\s+до\s+(\d{1,2}[:.]\d{2})", r"\1-\2", t)  # «с 11:00 до 23:00»
    if re.search(r"круглосуточн|24/7|24 часа", t) and not re.search(TIME, t):
        return "24/7"
    if re.fullmatch(r"\s*(ежедневно|без выходных)?\s*[,:]?\s*" + TIME + r"\s*(,?\s*(ежедневно|без выходных))?\s*[.,]?\s*", t):
        h1, m1, h2, m2 = re.search(TIME, t).groups()
        return f"Mo-Su {_t(h1, m1)}-{_t(h2, m2)}"
    rules = []
    for part in re.split(r"[;,]|\n", t):
        part = part.strip(" .")
        if not part:
            continue
        dm = re.match(r"(пн|вт|ср|чт|пт|сб|вс)\s*(?:[-–—]\s*(пн|вт|ср|чт|пт|сб|вс))?(?:\s*,\s*(пн|вт|ср|чт|пт|сб|вс))?\s*:?\s*(.*)$", part)
        if not dm:
            if re.fullmatch(r"(ежедневно|без выходных)", part):
                continue
            return None
        d1, d2, d3, rest = dm.groups()
        days = DAYS[d1] + (f"-{DAYS[d2]}" if d2 else "") + (f",{DAYS[d3]}" if d3 else "")
        if re.search(r"выходн|закрыт", rest):
            rules.append(f"{days} off")
            continue
        tm = re.fullmatch(r"(?:с\s*)?" + TIME + r"\s*", rest.replace(" до ", "-"))
        if not tm:
            return None
        h1, m1, h2, m2 = tm.groups()
        rules.append(f"{days} {_t(h1, m1)}-{_t(h2, m2)}")
    out = "; ".join(rules)
    return out if rules and _parse(out) is not None else None


def name_score(a: str, b: str) -> float:
    """Names must agree on their distinctive words («Гараж» is not «FIVE ENJ» though both are «ресторанный комплекс»)."""
    ka, kb = key(a), key(b)
    da = " ".join(w for w in ka.split() if w not in GENERIC_WORDS)
    db = " ".join(w for w in kb.split() if w not in GENERIC_WORDS)
    if da and db:
        return max(fuzz.ratio(da, db), fuzz.token_set_ratio(da, db))
    return max(fuzz.ratio(ka, kb), fuzz.token_set_ratio(ka, kb))


def _dist(a: dict, b: dict) -> float:
    return math.hypot((a["lat"] - b["lat"]) * 111000, (a["lon"] - b["lon"]) * 69700)


def _grid(rows: list[dict]) -> dict:
    g: dict = {}
    for r in rows:
        if r.get("lat") is not None and r.get("lon") is not None and r.get("name"):
            g.setdefault((round(r["lat"], 2), round(r["lon"], 2)), []).append(r)
    return g


def _near(r: dict, grid: dict, radius: float = 150, score: float = 85) -> tuple | None:
    best = None
    la, lo = round(r["lat"], 2), round(r["lon"], 2)
    for dl in (-.01, 0, .01):
        for dn in (-.01, 0, .01):
            for p in grid.get((round(la + dl, 2), round(lo + dn, 2)), []):
                d = _dist(r, p)
                if d > radius:
                    continue
                s = max(name_score(n, r["name"]) for n in [p["name"], *(p.get("names") or {}).values()] if n)
                if s >= score and (best is None or (s, -d) > (best[0], -best[1])):
                    best = (s, d, p)
    return best


def _age(r: dict) -> int:
    mod = (r.get("date_modified") or "")[:10]
    return (TODAY - dt.date.fromisoformat(mod)).days if mod else 10 ** 6


def main(crawl: str) -> dict:
    rows = [json.loads(line) for line in open(crawl, encoding="utf-8") if line.strip()]
    rows = [r for r in rows if r.get("lat") is not None and ASTANA[0] <= r["lat"] <= ASTANA[2] and ASTANA[1] <= r["lon"] <= ASTANA[3]]
    SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    write_jsonl(SNAPSHOT, rows)
    pois = [json.loads(line) for line in POIS_FILE.open(encoding="utf-8") if line.strip()]
    facts = json.loads((PROCESSED_DIR / "place_facts.json").read_text())
    gis = json.loads((PROCESSED_DIR / "twogis_layer.json").read_text())
    ours = _grid(pois)
    others = _grid(list(load(DEFAULT_SOURCE)))  # existence check only: nothing is copied from the 2GIS export
    ov_file = DATA_DIR / "raw" / "overture_astana.json"
    if ov_file.exists():
        for r in json.loads(ov_file.read_text()):
            others.setdefault((round(r["lat"], 2), round(r["lon"], 2)), []).append(r)
    batch, new, stats = [], [], {"crawled": len(rows), "hours_parsed": 0, "matched": 0, "hours_filled": 0, "new": 0, "new_unconfirmed": 0}
    taken = set()
    for r in rows:
        oh = to_osm(r["hours_text"]) if r.get("hours_text") else None
        stats["hours_parsed"] += bool(oh)
        age = _age(r)
        mod = (r.get("date_modified") or "")[:10] or "без даты"
        if (m := _near(r, ours)):
            stats["matched"] += 1
            p = m[2]
            if oh and p["id"] not in taken and not (p.get("opening_hours") or facts.get(p["id"], {}).get("opening_hours")
                                                   or gis.get(p["id"], {}).get("opening_hours")):
                taken.add(p["id"])
                batch.append({"poi_id": p["id"], "name": p["name"], "status": "open", "opening_hours": oh,
                              "hours_source": r["url"], "hours_note": f"по данным sxodim.com (карточка от {mod})",
                              "confidence": "medium" if age <= 365 else "low",
                              "notes": f"sxodim «{r['name']}» {int(m[1])} m, name score {m[0]:.0f}; page opened 2026-10-20"})
            continue
        cat = CATEGORY.get(r.get("category"))
        if not cat:
            continue
        # sxodim coordinates are often a building off: the same name within 400 m, or a place of the same kind
        # in the same building (≤30 m, another name), is a place we already have
        group = CATEGORIES[cat].group
        if _near(r, ours, radius=400) or any(_dist(r, q) <= 30 and CATEGORIES[q["category"]].group == group
                                            for q in ours.get((round(r["lat"], 2), round(r["lon"], 2)), [])):
            stats["already_ours"] = stats.get("already_ours", 0) + 1
            continue
        if not (age <= (TODAY - dt.date(2024, 1, 1)).days or _near(r, others)):
            stats["new_unconfirmed"] += 1
            continue
        slug = r["url"].rstrip("/").rsplit("/", 1)[-1]
        p = {"id": f"sx:{slug}"[:60], "name": r["name"].strip(), "category": cat, "lat": round(r["lat"], 6), "lon": round(r["lon"], 6),
             "address": re.sub(r"^(Қазақстан|Казахстан),\s*(Нұр-Сұлтан|Нур-Султан)\s*\(Астана\),\s*", "", r.get("address") or "") or None,
             "sources": ["sxodim"], "source_url": r["url"], "popularity": 0.03, "features": {}, "names": {}}
        if oh:
            p.update(opening_hours=oh, hours_source="sxodim.com", hours_source_url=r["url"], check_date=mod if mod != "без даты" else None)
        from pipeline.build import template_description
        p["description"], p["description_source"] = template_description(p), "template"
        new.append(p)
        ours.setdefault((round(p["lat"], 2), round(p["lon"], 2)), []).append(p)  # two sxodim cards of one venue: once
    stats.update(hours_filled=len(batch), new=len(new))
    BATCH.write_text(json.dumps(batch, ensure_ascii=False, indent=1) + "\n")
    if new:
        write_jsonl(POIS_FILE, pois + new)
        man = json.loads(MANIFEST_FILE.read_text())
        allp = pois + new
        man["poi_count"] = len(allp)
        man["by_category"] = dict(sorted({c: sum(1 for p in allp if p["category"] == c) for c in {p["category"] for p in allp}}.items(),
                                         key=lambda kv: -kv[1]))
        man.setdefault("by_source", {})["sxodim"] = len(new)
        man["pois_sha"] = hashlib.sha1("\n".join(p["id"] + p["name"] for p in allp).encode()).hexdigest()[:16]
        MANIFEST_FILE.write_text(json.dumps(man, ensure_ascii=False, indent=1))
    log.info("sxodim: %s", stats)
    return stats


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s", datefmt="%H:%M:%S")
    main(sys.argv[1])

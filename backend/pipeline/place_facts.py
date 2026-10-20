"""Researched facts for the places the assistant recommends most (`python -m pipeline.place_facts <batch_*.json>...`).

Input: research batches (one object per place: status, short description in our own words, opening hours,
features — each with the URL it came from). Every fact is checked here before it reaches the product:
a source URL is required, map/review services whose terms forbid reuse are rejected, hours must parse with the
same opening_hours parser the API uses, descriptions must not be about another city.
Output: data/processed/place_facts.json {poi_id: facts}; the API applies it at load (app/store.py).
"""
from __future__ import annotations

import json
import logging
import re
import sys
from urllib.parse import urlparse

from app.hours import _parse
from app.paths import PROCESSED_DIR
from app.store import OUTSIDE_ASTANA

log = logging.getLogger("pipeline.place_facts")
OUT_FILE = PROCESSED_DIR / "place_facts.json"
CHECKED = "2026-10-20"
BANNED = re.compile(r"2gis\.|yandex\.|google\.|goo\.gl|tripadvisor\.|restoclub\.|instagram\.|facebook\.|vk\.com|zoon\.|kudago\.", re.I)
EXCLUDE = {"cp:121"}  # «Музей Искусств»: the researcher could not tie the description to this address
STAGES = {"theatre", "event_venue", "arts_centre"}
FEATURES = {"wifi", "power_outlets", "kids_area", "outdoor_seating", "wheelchair", "free_entry"}


def _urls(values) -> list[str]:
    out = []
    for u in values if isinstance(values, list) else [values]:
        if isinstance(u, str) and re.match(r"https?://[^\s/]+\.[^\s]+", u) and not BANNED.search(urlparse(u).netloc):
            out.append(u.strip())
    return out


def clean(rec: dict, poi: dict) -> dict | None:
    out: dict = {}
    if rec.get("status") == "closed_permanently" and (src := _urls(rec.get("status_source"))):
        return {"status": "closed_permanently", "status_source": src[0], "checked": CHECKED}
    srcs = _urls(rec.get("description_sources") or [])
    text = (rec.get("description_ru") or "").strip()
    other_city = OUTSIDE_ASTANA.search(text) and not OUTSIDE_ASTANA.search(poi["name"])
    # a low-confidence text describes a chain or a guess about the branch: not shown as this place
    if srcs and 20 <= len(text) <= 320 and not other_city and rec.get("confidence") != "low" and poi["id"] not in EXCLUDE:
        out["description_ru"] = text
        if 20 <= len(en := (rec.get("description_en") or "").strip()) <= 360:
            out["description_en"] = en
        out["description_url"] = srcs[0]
    hours = (rec.get("opening_hours") or "").strip()
    src = [u for u in _urls(rec.get("hours_source")) if ".wikipedia.org" not in u]  # unsourced, often stale
    note = rec.get("hours_note") or ""
    # box-office hours are not visit times: a stage venue's hours, or a note whose times are the hours themselves
    box_office = re.search(r"касс|box office|ticket office", note, re.I) and (
        poi["category"] in STAGES or set(re.findall(r"\d{1,2}:\d{2}", note)) >= set(re.findall(r"\d{1,2}:\d{2}", hours)))
    snippet = re.search(r"snippet|excerpt|сниппет|выдержк", rec.get("notes") or "", re.I)  # page not actually opened / in doubt
    if hours and src and not box_office and not snippet and _parse(hours) is not None:
        out.update(opening_hours=hours, hours_url=src[0])
        if note := (rec.get("hours_note") or "").strip():
            out["hours_note"] = note[:120]
    feats = {k: v for k, v in (rec.get("features") or {}).items()
             if k in FEATURES and (v in (True, False) or (k == "wheelchair" and v in ("yes", "limited", "no")))}
    if feats and _urls(rec.get("features_sources") or []):
        out["features"] = feats
        out["features_url"] = _urls(rec["features_sources"])[0]
    if not out:
        return None
    out["checked"] = rec.get("checked") or CHECKED  # site_hours records carry their own crawl date
    out["confidence"] = rec.get("confidence") if rec.get("confidence") in ("high", "medium", "low") else "medium"
    return out


def merge_link_checks(facts: dict, path: str) -> int:
    """Websites checked by hand (domain gone, parked, or now an unrelated or harmful site): the card drops the link."""
    n = 0
    for rec in json.loads(open(path, encoding="utf-8").read()):
        f = facts.setdefault(rec["poi_id"], {"checked": CHECKED})
        f.update(drop_website=True, website_problem=rec["problem"])
        n += 1
    return n


def main(paths: list[str]) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    pois = {json.loads(line)["id"]: json.loads(line) for line in (PROCESSED_DIR / "pois.jsonl").open(encoding="utf-8") if line.strip()}
    facts = json.loads(OUT_FILE.read_text()) if OUT_FILE.exists() else {}
    seen = kept = 0
    for path in [p for p in paths if "link_check" in p]:
        log.info("link checks: %d websites dropped", merge_link_checks(facts, path))
    for path in [p for p in paths if "link_check" not in p]:
        for rec in json.loads(open(path, encoding="utf-8").read()):
            seen += 1
            poi = pois.get(rec.get("poi_id"))
            if poi and (c := clean(rec, poi)):
                facts[poi["id"]] = {**facts.get(poi["id"], {}), **c}
                kept += 1
    OUT_FILE.write_text(json.dumps(facts, ensure_ascii=False, indent=1))
    log.info("place facts: %d of %d researched places kept (%d in file)", kept, seen, len(facts))


if __name__ == "__main__":
    main(sys.argv[1:])

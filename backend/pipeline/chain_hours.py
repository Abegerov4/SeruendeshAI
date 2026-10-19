"""Opening hours from chains' branch lists: Coffee Boom's own site and AllThePlaces (CC0) spiders.

A chain list gives every branch with coordinates and hours, so one request covers dozens of our places.
`fetch` stores the factual fields in the committed file data/sources/chain_hours.json together with the
check date (for AllThePlaces - the date of their crawl, not of our download); `apply` accepts hours for one of our records only when exactly one branch can be meant:

* the name/brand is the chain's and the nearest branch is within MATCH_M;
* no other branch with different hours is within AMBIGUOUS_M of that one (two counters in one mall
  stay pending - we cannot tell which one OSM mapped);
* the branch is confirmed independently: coordinates within EXACT_M, the same phone (unique within the
  chain), or the same house number. A different house number rules the branch out.

Everything else goes to the pending queue with a reason. Existing hours are never overwritten: when they
differ, the record keeps them and gets `hours_conflict` with both versions and sources, so the API keeps
the undated value at low confidence instead of quietly trusting either. Equal start and end times
("00:00-00:00") are not read as 24/7 without an explicit source statement, and hours whose scope is not
the venue itself (delivery, order desk, unknown) stay pending.

Not covered and why (checked 2026-10-19): starbucks.com.kz times out from KZ networks; kfc-kazakhstan.kz,
the website on most KFC records, now redirects to an unrelated leasing company. Of ~180 AllThePlaces
spiders for chains present in Kazakhstan only dodo_pizza and papa_johns_kz have Astana branches.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import math
import re
from collections import Counter

from app.paths import DATA_DIR

log = logging.getLogger("pipeline.chain_hours")

CHAIN_FILE = DATA_DIR / "sources" / "chain_hours.json"
REVIEW_FILE = DATA_DIR / "sources" / "chain_hours_review.json"
USER_AGENT = "SeruendeshAI/0.1 (Astana hackathon POI research)"
PARSER_VERSION = 2
MATCH_M, AMBIGUOUS_M, EXACT_M = 150, 100, 50
SOURCE_NOTE = ("Chain branch lists with dated checks: coffeeboom.kz (licence not specified - opening hours only) "
               "and AllThePlaces spiders dodo_pizza, papa_johns_kz (CC0)")
ATP_RUNS = "https://data.alltheplaces.xyz/runs/latest.json"

CHAINS = {
    "coffeeboom": {
        "label": "coffeeboom.kz",
        "page": "https://coffeeboom.kz/coffeeshops/?city=16",
        "endpoint": "https://coffeeboom.kz/e/437/getCoffeeshops/",
        "form": {"filters[city][]": "16", "filters[format][]": "all"},  # 16 = Astana
        "robots": "https://coffeeboom.kz/robots.txt allows /coffeeshops/ and /e/ (checked 2026-10-19)",
        "hours_scope": "venue",  # the site lists coffee shop hours; there is no separate delivery schedule
        "name": re.compile(r"coffee\s*boom|кофе\s*бум", re.I),
    },
    "dodo": {
        "label": "alltheplaces.xyz",
        "spider": "dodo_pizza",
        "hours_scope": "venue",  # the spider reads RestaurantWeekWorkingTime, not delivery hours
        "license": "CC0-1.0",
        "name": re.compile(r"dodo|додо", re.I),
    },
    "papajohns": {
        "label": "alltheplaces.xyz",
        "spider": "papa_johns_kz",
        "hours_scope": "unknown",  # free text from the order site; "00:00-02:45" looks like delivery hours
        "license": "CC0-1.0",
        "name": re.compile(r"papa\s*john|пап[аы]\s*джон", re.I),
    },
}

_DAYS = {"Mon": "Mo", "Tue": "Tu", "Wed": "We", "Thu": "Th", "Fri": "Fr", "Sat": "Sa", "Sun": "Su"}
_WORK = re.compile(r"(Mon|Tue|Wed|Thu|Fri|Sat|Sun)(?:-(Mon|Tue|Wed|Thu|Fri|Sat|Sun))?\s+(\d\d):(\d\d)-(\d\d):(\d\d)")


def coffeeboom_hours(text: str | None) -> str | None:
    """'Mon-Sun 08:00-00:00' -> 'Mo-Su 08:00-24:00'. Unknown formats and equal endpoints -> None."""
    parts = [p.strip() for p in (text or "").split(";") if p.strip()]
    rules = []
    for part in parts:
        m = _WORK.fullmatch(part)
        if not m:
            return None
        d1, d2, h1, m1, h2, m2 = m.groups()
        start, end = int(h1) * 60 + int(m1), int(h2) * 60 + int(m2)
        if start >= 1440 or end > 1440 or start == end:
            return None  # "00:00-00:00" may mean 24 hours or a blank form field
        if end == 0:
            end = 1440
        days = _DAYS[d1] + ("-" + _DAYS[d2] if d2 else "")
        rules.append(f"{days} {start // 60:02}:{start % 60:02}-{end // 60:02}:{end % 60:02}")
    return "; ".join(rules) or None


def phone_key(value: str | None) -> str | None:
    digits = re.sub(r"\D", "", value or "")
    return digits[-10:] if len(digits) >= 10 else None


def house_number(address: str | None) -> str | None:
    """First house number of an address ('Тұран даңғылы, 43В' -> '43в'); None when there is none."""
    m = re.search(r"(?<![\d/])(\d{1,4}(?:/\d{1,3})?[а-яәa-z]?)(?![\d])", (address or "").casefold())
    return m[1] if m else None


def parse_coffeeboom(payload: dict) -> list[dict]:
    shops = ((payload.get("data") or {}).get("coffeeshops")) if isinstance(payload, dict) else None
    if not isinstance(shops, dict) or not shops:
        raise ValueError("Coffee Boom response is not a coffee shop list")
    out = []
    for s in shops.values():
        try:
            lat, lon = float(s["lat"]), float(s["lng"])
        except (KeyError, TypeError, ValueError):
            continue
        if str(s.get("status")) != "1" or not (50.9 <= lat <= 51.4 and 71.0 <= lon <= 71.9):
            continue
        out.append({"chain": "coffeeboom", "branch_id": str(s["id"]), "name": (s.get("name") or "").strip(),
                    "address": (s.get("address") or "").strip() or None, "lat": lat, "lon": lon,
                    "phone": phone_key(s.get("phone")), "work_time": s.get("work_time"),
                    "opening_hours": coffeeboom_hours(s.get("work_time")),
                    "format": (s.get("format") or {}).get("code"), "source_updated_at": s.get("update_datetime")})
    return sorted(out, key=lambda b: int(b["branch_id"]) if b["branch_id"].isdigit() else b["branch_id"])


def _valid_hours(value) -> str | None:
    import opening_hours as oh

    if not isinstance(value, str) or not value.strip():
        return None
    try:
        oh.OpeningHours(value)
    except Exception:
        return None
    return value.strip()


def parse_atp(geojson: dict, chain: str) -> list[dict]:
    """Astana branches from an AllThePlaces spider output (GeoJSON, OSM-style properties)."""
    out = []
    for f in geojson.get("features") or []:
        lon, lat = ((f.get("geometry") or {}).get("coordinates") or [None, None])[:2]
        props = f.get("properties") or {}
        if not isinstance(lat, (int, float)) or not (50.9 <= lat <= 51.4 and 71.0 <= lon <= 71.9):
            continue
        address = props.get("addr:full:ru") or props.get("addr:full") or props.get("addr:street_address")
        out.append({"chain": chain, "branch_id": str(props.get("ref") or f.get("id")), "name": props.get("branch") or props.get("name"),
                    "address": address, "lat": lat, "lon": lon, "phone": phone_key(props.get("phone")),
                    "work_time": props.get("opening_hours"), "opening_hours": _valid_hours(props.get("opening_hours")),
                    "source_uri": props.get("@source_uri")})
    return sorted(out, key=lambda b: b["branch_id"])


def fetch(today: dt.date | None = None) -> dict:
    """Download the branch lists and rewrite data/sources/chain_hours.json."""
    import httpx

    branches, checked, pages = {}, {}, {}
    today = (today or dt.date.today()).isoformat()
    with httpx.Client(timeout=120, headers={"User-Agent": USER_AGENT}) as client:
        chain = CHAINS["coffeeboom"]
        r = client.post(chain["endpoint"], data=chain["form"], headers={"Referer": chain["page"]})
        r.raise_for_status()
        branches["coffeeboom"], checked["coffeeboom"] = parse_coffeeboom(r.json()), today
        run = client.get(ATP_RUNS).raise_for_status().json()
        output = run["output_url"].rsplit("/", 1)[0] + "/output/"
        for key, chain in CHAINS.items():
            if spider := chain.get("spider"):
                r = client.get(output + spider + ".geojson")
                r.raise_for_status()
                branches[key], checked[key] = parse_atp(r.json(), key), run["start_time"][:10]
                pages[key] = output + spider + ".geojson"
    snap = snapshot(branches, checked, pages)
    write(snap)
    return snap


def snapshot(branches: dict[str, list[dict]], checked: dict[str, str], pages: dict[str, str] | None = None) -> dict:
    """`pages` gives the downloaded URL for chains without a fixed page (AllThePlaces run outputs)."""
    return {"parser_version": PARSER_VERSION,
            "chains": {key: {k: v for k, v in CHAINS[key].items() if k not in {"name", "form"}}
                       | ({"page": pages[key]} if pages and key in pages else {})
                       | {"checked_at": checked[key], "branches": rows} for key, rows in branches.items()}}


def write(snap: dict, path=CHAIN_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snap, ensure_ascii=False, indent=1) + "\n")


def load() -> dict:
    return json.loads(CHAIN_FILE.read_text()) if CHAIN_FILE.exists() else {"chains": {}}


def _m(a: dict, b: dict) -> float:
    p1, p2 = math.radians(a["lat"]), math.radians(b["lat"])
    dl = math.radians(b["lon"] - a["lon"])
    h = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(h))


def same_hours(a: str | None, b: str | None) -> bool:
    """Equal schedules written differently ('09:00-24:00' vs 'Mo-Su 09:00-24:00') are the same fact."""
    from app.hours import _week_calendar

    if a == b:
        return True
    left = _week_calendar(a) if a else None
    return left is not None and left == (_week_calendar(b) if b else None)


def _identity(p: dict, best: dict, dist: float, unique_phones: set[str]) -> tuple[str | None, str]:
    """(method, reason): method is None when the branch is not independently confirmed."""
    ours, theirs = house_number(p.get("address")), house_number(best.get("address"))
    if ours and theirs and ours != theirs:
        return None, "house_number_conflict"
    if phone_key(p.get("phone")) and phone_key(p.get("phone")) == best.get("phone") and best["phone"] in unique_phones:
        return "phone", ""
    if ours and ours == theirs:
        return "house_number", ""
    if dist <= EXACT_M:
        return "coordinates", ""
    return None, "unconfirmed_branch"


def apply(pois: list[dict], snap: dict) -> dict:
    """Attach accepted chain hours in place; returns accepted, conflicting and pending cases."""
    report = {"parser_version": snap.get("parser_version"),
              "branches": 0, "accepted": [], "conflicts": [], "pending": [], "unmatched_branches": 0}
    for key, chain in snap.get("chains", {}).items():
        pattern = CHAINS[key]["name"]
        branches = chain["branches"]
        report["branches"] += len(branches)
        phones = Counter(b["phone"] for b in branches if b.get("phone"))
        unique_phones = {ph for ph, n in phones.items() if n == 1}
        used = set()
        for p in pois:
            if not pattern.search(f"{p.get('name') or ''} {p.get('brand') or ''}"):
                continue
            ranked = sorted(branches, key=lambda b: _m(p, b))
            case = {"poi": p["id"], "chain": key}
            if not ranked or _m(p, ranked[0]) > MATCH_M:
                report["pending"].append(case | {"reason": "no_branch_nearby"})
                continue
            best, dist = ranked[0], _m(p, ranked[0])
            case |= {"branch": best["branch_id"], "distance_m": round(dist), "branch_address": best["address"],
                     "work_time": best["work_time"]}
            rivals = [b["branch_id"] for b in ranked[1:]
                      if _m(p, b) - dist < AMBIGUOUS_M and not same_hours(b["opening_hours"], best["opening_hours"])]
            if rivals:
                report["pending"].append(case | {"reason": "several_branches", "rivals": rivals})
                continue
            used.add(best["branch_id"])
            if not best["opening_hours"]:
                report["pending"].append(case | {"reason": "hours_unclear"})
                continue
            if chain.get("hours_scope") != "venue":
                report["pending"].append(case | {"reason": "hours_scope_" + str(chain.get("hours_scope"))})
                continue
            method, reason = _identity(p, best, dist, unique_phones)
            if not method:
                report["pending"].append(case | {"reason": reason, "our_address": p.get("address")})
                continue
            fact = {"value": best["opening_hours"], "source": chain["label"], "source_url": chain["page"],
                    "branch_id": best["branch_id"], "checked_at": chain["checked_at"],
                    "source_updated_at": best.get("source_updated_at"), "match_method": method}
            old = p.get("opening_hours")
            if old and not same_hours(old, best["opening_hours"]):
                p["hours_conflict"] = {"current": old, "current_source": p.get("hours_source") or "osm", "candidate": fact}
                report["conflicts"].append(case | {"current": old, "candidate": best["opening_hours"], "match_method": method})
                continue
            report["accepted"].append(case | {"opening_hours": best["opening_hours"], "match_method": method,
                                              "filled": not old})
            p["opening_hours"] = best["opening_hours"]
            p["hours_source"] = chain["label"]
            p["hours_source_url"] = chain["page"]
            p["check_date"] = chain["checked_at"]
            p["hours_evidence"] = fact
            if chain["label"] not in p.setdefault("sources", []):
                p["sources"].append(chain["label"])
        report["unmatched_branches"] += sum(b["branch_id"] not in used for b in branches)
    log.info("chain hours: %d accepted (%d new), %d conflicts, %d pending", len(report["accepted"]),
             sum(a["filled"] for a in report["accepted"]), len(report["conflicts"]), len(report["pending"]))
    return report


def summary(report: dict) -> dict:
    return {"branches": report["branches"],
            "accepted": len(report["accepted"]), "filled": sum(a["filled"] for a in report["accepted"]),
            "conflicts": len(report["conflicts"]), "pending": len(report["pending"]),
            "unmatched_branches": report["unmatched_branches"]}

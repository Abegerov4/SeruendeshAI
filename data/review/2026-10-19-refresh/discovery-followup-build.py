#!/usr/bin/env python3
"""Extract only manually reviewed exact firms from the public discovery cache.

No network, model calls, canonical mutation or automatic identity acceptance.
The review ledger pins each accepted firm to a source response hash. Re-running
requires those local source archives; accepted excerpts remain in the sidecar.
"""
from __future__ import annotations

import ast
from collections import Counter
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
DAY_LABELS = ("Mo", "Tu", "We", "Th", "Fr", "Sa", "Su")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def source_firm_ids(record):
    """Find physical directory branches even when the identity page is a menu."""
    urls = [record["identity"]["source_url"]]
    for key in ("facts", "menu_items", "prices"):
        for item in record.get(key, []):
            urls.extend(item.get("source", {}).get(field, "")
                        for field in ("url", "identity_url", "source_url"))
    result = set()
    for url in urls:
        if not isinstance(url, str):
            continue
        parsed = urlsplit(url)
        if parsed.hostname not in {"2gis.kz", "www.2gis.kz"}:
            continue
        match = re.search(r"/firm/(\d+)(?:/|$)", parsed.path)
        if match:
            result.add(match[1])
    return result


def firm_objects(raw):
    soup = BeautifulSoup(raw, "html.parser")
    script = next(t.get_text() for t in soup.find_all("script")
                  if "initialState = JSON.parse" in t.get_text())
    match = re.search(r"initialState\s*=\s*JSON.parse\(('(?:\\.|[^'\\])*')\)", script)
    state = json.loads(ast.literal_eval(match[1]))
    found = {}

    def walk(value):
        if isinstance(value, dict):
            if all(k in value for k in ("id", "point", "address_name")) and value.get("type") == "branch":
                if value["id"] in found and found[value["id"]] != value:
                    raise ValueError("Conflicting public objects for the same firm ID")
                found[value["id"]] = value
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(state)
    return found


def schedule_value(schedule):
    # Missing weekdays do not mean closed. Special/partial schedules stay raw.
    if not set(DAYS) <= set(schedule) or set(schedule) - set(DAYS) - {"comment", "is_24x7"}:
        return None
    calendar = bytearray(7 * 1440)
    for index, day in enumerate(DAYS):
        item = schedule[day]
        if set(item) != {"working_hours"} or not item["working_hours"]:
            return None
        for interval in item["working_hours"]:
            if set(interval) != {"from", "to"}:
                return None
            if not all(re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d|24:00", interval[k])
                       for k in ("from", "to")):
                return None
            start, end = [int(interval[k][:2]) * 60 + int(interval[k][3:]) for k in ("from", "to")]
            if start == 1440 or start == end:
                return None
            if end < start:
                end += 1440
            for minute in range(start, end):
                calendar[(index * 1440 + minute) % len(calendar)] = 1
    # Emit complete same-day intervals. The consumer treats later weekday rules
    # as replacements, so a bare overnight tail could otherwise be erased.
    intervals = []
    for index in range(7):
        day = calendar[index * 1440:(index + 1) * 1440]
        pieces, start = [], None
        for minute in range(1441):
            opened = minute < 1440 and day[minute]
            if opened and start is None:
                start = minute
            elif not opened and start is not None:
                pieces.append(f"{start // 60:02}:{start % 60:02}-{minute // 60:02}:{minute % 60:02}")
                start = None
        intervals.append(",".join(pieces))
    if len(set(intervals)) == 1:
        return "Mo-Su " + intervals[0]
    return "; ".join(day + " " + value for day, value in zip(DAY_LABELS, intervals))


def extract(row, firm, event, review):
    assert not firm.get("dates", {}).get("deleted_at"), "Closed/deleted source is not an active fact"
    name = firm.get("name_ex", {}).get("primary", firm["name"])
    identity = {
        "canonical_name": row["name"], "canonical_address": row.get("address"),
        "canonical_lat": row["lat"], "canonical_lon": row["lon"],
        "source_name": name, "source_address": firm["address_name"],
        "source_lat": firm["point"]["lat"], "source_lon": firm["point"]["lon"],
        "source_url": "https://2gis.kz/astana/firm/" + firm["id"],
        "branch_confirmed": True, "match_basis": "name_coordinates",
    }
    checked = datetime.fromisoformat(event["checked_at"]).astimezone(ZoneInfo("Asia/Almaty")).date().isoformat()
    record = {"canonical_id": row["id"], "identity": identity, "facts": [], "menu_items": [], "prices": []}

    def evidence(excerpt, *, channel="onsite", **extra):
        return {
            "status": "accepted", "conflict_status": "none", "branch_scope": "exact",
            "branch_confirmation": {k: identity[k] for k in ("source_name", "source_address")},
            "source": {
                "url": event["source_url"], "identity_url": identity["source_url"],
                "excerpt": excerpt, "checked_at": checked, "fetched_at": event["checked_at"],
                "source_updated_at": firm.get("dates", {}).get("updated_at"),
                "channel": channel, "firm_id": firm["id"],
                "archive_path": event["archive_path"], "response_sha256": event["response_sha256"],
                "extraction": "Reviewed exact firm in public 2GIS HTML initial state; no neighboring cards",
                **extra,
            }, "valid_from": None, "valid_to": None,
        }

    def add(field, value, excerpt, **extra):
        record["facts"].append({"field": field, "value": value, **evidence(excerpt, **extra)})

    add("address", firm["address_name"], name + ": " + firm["address_name"])
    primary = [r["name"] for r in firm.get("rubrics", []) if r.get("kind") == "primary"]
    formats = [firm.get("name_ex", {}).get("extension"), *primary]
    formats = list(dict.fromkeys(f for f in formats if f))
    if formats:
        add("format", " / ".join(formats), name + ": " + "; ".join(formats))
    attrs = {a["tag"]: a["name"] for g in firm.get("attribute_groups", []) for a in g.get("attributes", [])}
    cuisines = [value for tag, value in attrs.items() if tag.startswith("food_service_food_")
                and tag != "food_service_food_hal"]
    if cuisines:
        add("cuisines", cuisines, "; ".join(cuisines))
    mappings = {
        "wifi": ("additionally_services_wifi", "additionally_services_freewifi"),
        "halal": ("food_service_food_hal",),
        "kids_area": ("food_service_infrastructure_kids_room", "food_service_infrastructure_kids_playroom"),
        "reservations": ("food_service_details_food_table_reservation",),
        "takeaway": ("food_service_details_food_takeaway",),
        "delivery": ("covid_homedelivery",),
        "terrace": ("food_service_infrastructure_patio", "food_service_infrastructure_outdoor_tables_eat_out"),
        "laptop_allowed": ("food_service_cafe_working",),
        "wheelchair_accessible": ("accessible_entrance_accessible_entrance",),
    }
    for field, tags in mappings.items():
        proof = [attrs[tag] for tag in tags if tag in attrs]
        if proof:
            add(field, True, "; ".join(proof))
    capacity = attrs.get("food_service_capacity")
    if capacity and re.fullmatch(r"До\s+\d+\s+мест", capacity):
        add("seating_capacity_max", int(re.search(r"\d+", capacity)[0]), capacity)
    payments = [value for tag, value in attrs.items() if tag.startswith("general_payment_type_")]
    if payments:
        add("payment_methods", payments, "; ".join(payments))
    services = [attrs[tag] for tag in ("food_service_business_lunch", "food_service_details_food_breakfast",
                "food_service_details_food_kids_menu", "food_service_details_food_english_menu",
                "food_service_details_food_chinese_menu", "food_service_details_food_fat_free_menu") if tag in attrs]
    if services:
        add("services", services, "; ".join(services))
    schedule = firm.get("schedule", {})
    hours = schedule_value(schedule)
    if hours:
        add("opening_hours", hours, "Exact firm weekly schedule: " + hours,
            raw_schedule=schedule, timezone_offset=firm.get("timezone_offset"))
    if schedule.get("comment"):
        add("description_fact", "Примечание к графику: " + schedule["comment"], schedule["comment"])

    # A directory check is a venue average, never an item/menu/complete-meal price.
    # Delivery-only, retail, banquet and unknown formats do not establish dine-in checks.
    groups = {"Рестораны": "restaurant", "Кафе": "cafe", "Кофейни": "cafe",
              "Кафе-кондитерские": "cafe", "Столовые": "canteen"}
    group = next((groups[r] for r in primary if r in groups), None)
    average = attrs.get("food_service_avg_price")
    if group and average and re.fullmatch(r"Чек\s+[\d\s\u00a0]+\s*₸", average):
        amount = int(re.sub(r"\D", "", average))
        record["prices"].append({"amount": amount, "currency": "KZT", "unit": "person",
            "channel": "dine_in", "kind": "average_check", "comparison_group": group,
            **evidence(average, channel="dine_in", price_basis="directory_reported_average_check")})
    return record


def main():
    raw = (ROOT / "data/processed/pois.json").read_bytes()
    canonical = {r["id"]: r for r in json.loads(raw)}
    reviews = json.loads((HERE / "discovery-followup-branch-reviews.json").read_text())
    assert reviews["canonical_sha256"] == sha(raw)
    events = [json.loads(line) for line in (HERE / "discovery-queue-events.jsonl").read_text().splitlines()]
    by_source = {(e["canonical_id"], e.get("response_sha256")): e for e in events if e.get("archive_path")}
    source = ROOT / "data/sources/place_details_discovery_2026-10-19.json"
    payload = json.loads(source.read_text())
    report_path = HERE / "discovery-followup-extraction.json"
    prior = json.loads(report_path.read_text()) if report_path.exists() else {"records": []}
    owned = {r["canonical_id"]: r for r in prior["records"]}
    for record in payload["records"]:
        expected = owned.get(record["canonical_id"], {}).get("accepted_record_sha256")
        if expected:
            assert sha(json.dumps(record, sort_keys=True, ensure_ascii=False).encode()) == expected, "Concurrent sidecar edit; do not overwrite"
    payload["records"] = [r for r in payload["records"] if r["canonical_id"] not in owned]
    known_ids = {r["canonical_id"] for r in payload["records"]}
    known_firms = set()
    for path in (ROOT / "data/sources/place_details_2026-10-19.json", source, HERE / "discovery-gasteria.json"):
        for record in (payload if path == source else json.loads(path.read_text()))["records"]:
            known_firms.update(source_firm_ids(record))
    added = []
    archives = {}
    for review in reviews["decisions"]:
        if review["decision"] != "accept_identity" or review["canonical_id"] in known_ids:
            continue
        assert review["firm_id"] not in known_firms, "One reviewed source branch per enrichment record"
        row = canonical[review["canonical_id"]]
        assert sha(json.dumps(row, sort_keys=True, ensure_ascii=False).encode()) == review["canonical_row_sha256"]
        event = by_source[(row["id"], review["response_sha256"])]
        archive = ROOT / event["archive_path"]
        if str(archive) not in archives:
            response = archive.read_bytes()
            assert sha(response) == review["response_sha256"]
            archives[str(archive)] = firm_objects(response)
        firm = archives[str(archive)][review["firm_id"]]
        record = extract(row, firm, event, review)
        payload["records"].append(record)
        known_ids.add(row["id"])
        known_firms.add(firm["id"])
        added.append({"canonical_id": row["id"], "name": row["name"], "firm_id": firm["id"],
                      "facts": len(record["facts"]), "prices": len(record["prices"]), "menu_items": 0,
                      "accepted_record_sha256": sha(json.dumps(record, sort_keys=True, ensure_ascii=False).encode())})
    write(source, payload)
    prior["records"] = added
    prior.update(canonical_sha256=sha(raw), accepted_additive_records=len(prior["records"]),
                 counts={key: sum(r[key] for r in prior["records"]) for key in ("facts", "prices", "menu_items")},
                 note="Manually matched public directory facts; no priced dishes inferred from average checks or assortment.")
    write(report_path, prior)
    print(json.dumps({"rebuilt_owned_records": len(added), "sidecar_records": len(payload["records"]),
                      "owned_counts": dict(Counter({k: sum(r[k] for r in added) for k in ("facts", "prices", "menu_items")}))}))


if __name__ == "__main__":
    main()

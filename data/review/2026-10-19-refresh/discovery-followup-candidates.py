#!/usr/bin/env python3
"""Prepare nearby cached firms for human review; never accept a candidate.

Usage: .venv/bin/python discovery-followup-candidates.py --output /tmp/candidates.json
Only already fetched public HTML is read. Name/address decisions remain manual.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
spec = importlib.util.spec_from_file_location("followup_build", HERE / "discovery-followup-build.py")
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


def distance(a, b):
    hav = (math.sin(math.radians(a["lat"] - b["lat"]) / 2) ** 2
           + math.cos(math.radians(a["lat"])) * math.cos(math.radians(b["lat"]))
           * math.sin(math.radians(a["lon"] - b["lon"]) / 2) ** 2)
    return 2 * 6371000 * math.asin(min(1, math.sqrt(hav)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    queue = json.loads((HERE / "discovery-queue.json").read_text())
    rows = {r["id"]: r for r in queue["records"]}
    reviewed = json.loads((HERE / "discovery-followup-branch-reviews.json").read_text())
    reviewed_keys = {(r["canonical_id"], r["firm_id"]) for r in reviewed["decisions"]}
    excluded = set()
    for path in (ROOT / "data/sources/place_details_2026-10-19.json",
                 ROOT / "data/sources/place_details_discovery_2026-10-19.json",
                 HERE / "discovery-gasteria.json"):
        excluded.update(r["canonical_id"] for r in json.loads(path.read_text())["records"])
    cache, candidates, errors = {}, [], []
    lines = (HERE / "discovery-queue-events.jsonl").read_text().splitlines()
    for line in lines:
        event = json.loads(line)
        ident = event["canonical_id"]
        if event["provider"] != "2gis" or ident not in rows or ident in excluded or not event.get("archive_path"):
            continue
        archive = ROOT / event["archive_path"]
        try:
            if str(archive) not in cache:
                raw = archive.read_bytes()
                assert hashlib.sha256(raw).hexdigest() == event["response_sha256"]
                cache[str(archive)] = builder.firm_objects(raw)
            for firm in cache[str(archive)].values():
                if (ident, firm["id"]) in reviewed_keys:
                    continue
                dist = distance(rows[ident], firm["point"])
                if dist <= 200:
                    candidates.append({"canonical": rows[ident], "firm": firm,
                                       "distance_m": round(dist, 1), "event": event})
        except Exception as exc:
            errors.append({"canonical_id": ident, "archive_path": event["archive_path"],
                           "error": type(exc).__name__ + ": " + str(exc)})
    args.output.write_text(json.dumps(candidates, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"unreviewed_nearby_candidates": len(candidates), "parse_errors": errors,
                      "note": "Nearby is triage only; unreviewed names/addresses never become accepted facts."}))


if __name__ == "__main__":
    main()

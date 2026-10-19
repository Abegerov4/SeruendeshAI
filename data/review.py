"""Reproducible offline review queues, source freshness and graph diagnostics.

Run ``python -m data.review --as-of YYYY-MM-DD --output-dir data/review/DATE``.
No facts are approved by this command. The checked-in duplicate decisions are
human/source evidence, while generated pairs remain unresolved by default.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
from itertools import combinations
import json
from pathlib import Path
import re
import unicodedata

from data.eligibility import source_ids
from data.provenance import freshness

ROOT = Path(__file__).resolve().parents[1]
FIELDS = ("opening_hours", "wheelchair", "kid_friendly", "internet_access", "power_supply", "entrance", "lit", "name_en", "name_kk")
SCENARIOS = {
    "work_with_laptop": ({"cafe", "coworking", "library"}, ("opening_hours", "internet_access", "power_supply")),
    "children": ({"museum", "playground", "kids_indoor", "zoo_aquarium", "park"}, ("opening_hours", "kid_friendly", "entrance")),
    "wheelchair": (None, ("opening_hours", "wheelchair", "entrance")),
    "evening_walk": ({"park", "garden", "monument", "viewpoint"}, ("opening_hours", "lit", "entrance")),
    "multilingual_culture": ({"museum", "theatre", "gallery", "monument"}, ("opening_hours", "name_en", "name_kk")),
}


def _key(name):
    return re.sub(r"[^\w]+", "", unicodedata.normalize("NFKC", name).casefold().replace("ё", "е"))


def _field(row, field, evidence, as_of):
    facts = [e for e in evidence if e.get("field") == field and e.get("source_id") and e.get("source_url")]
    conflict = [f for f in row.get("field_conflicts", []) if f.get("field") == field]
    values = {json.dumps(f.get("value"), sort_keys=True) for f in facts}
    if conflict or len(values) > 1:
        state = "conflicting"
    elif facts:
        state = "false" if facts[0].get("value") in (False, "no") else "confirmed"
    else:
        state = "unknown"
    checked = sorted(facts, key=lambda e: e.get("checked_at") or "", reverse=True)
    return {"state": state, "evidence": facts, "conflicts": conflict,
            "freshness": freshness(checked[0] if checked else {}, as_of=as_of)}


def graph_coverage(active, path):
    if not path or not Path(path).exists():
        return {"status": "missing", "real_path_checks": "pending"}
    import numpy as np
    from scipy.sparse import csr_matrix
    from scipy.sparse.csgraph import connected_components
    from scipy.spatial import cKDTree
    z = np.load(path)
    kx, ky = 111320 * np.cos(np.radians(51.14)), 110540
    tree = cKDTree(np.c_[z["lon"] * kx, z["lat"] * ky])
    dist, idx = tree.query(np.array([[p["lon"] * kx, p["lat"] * ky] for p in active]))
    matrix = csr_matrix((z["weights"], z["indices"], z["indptr"]), shape=(len(z["lat"]), len(z["lat"])))
    count, components = connected_components(matrix, directed=True, connection="weak")
    west, south, east, north = map(float, z["bbox"])
    rows = [{"id": p["id"], "inside_bbox": bool(south <= p["lat"] <= north and west <= p["lon"] <= east),
             "nearest_snap_m": round(float(dist[i]), 1), "weak_component": int(components[idx[i]])}
            for i, p in enumerate(active)]
    return {"status": "diagnostic_only", "bbox_lon_lat": [west, south, east, north],
            "nodes": len(z["lat"]), "directed_edges": len(z["indices"]), "weak_components": int(count),
            "active_inside_bbox": sum(p["inside_bbox"] for p in rows),
            "active_outside_bbox": sum(not p["inside_bbox"] for p in rows),
            "inside_snap_above_250m": sum(p["inside_bbox"] and p["nearest_snap_m"] > 250 for p in rows),
            "review_queue": [r for r in rows if not r["inside_bbox"] or r["nearest_snap_m"] > 250],
            "real_path_checks": "pending: entrances, crossing access, bridges and accessibility require source/field review"}


def build_review(rows, active, *, as_of, external=None, decisions=None, graph_path=None):
    external, decisions = external or {}, decisions or {}
    field_review = []
    for row in active:
        evidence = [*row.get("field_evidence", []), *row.get("amenity_facts", []),
                    *(e for ident in source_ids(row) for e in external.get(ident, []))]
        # Deduplicate the same cached assertion before evaluating disagreement.
        evidence = list({json.dumps(e, sort_keys=True): e for e in evidence}.values())
        field_review.append({"id": row["id"], "name": row["name"],
                             "fields": {field: _field(row, field, evidence, as_of) for field in FIELDS}})
    by_id = {r["id"]: r for r in field_review}
    scenarios = {}
    for name, (categories, required) in SCENARIOS.items():
        eligible = [p for p in active if categories is None or p["category"] in categories]
        complete = [p for p in eligible if all(by_id[p["id"]]["fields"][f]["state"] == "confirmed" for f in required)]
        fresh = [p for p in complete if all(by_id[p["id"]]["fields"][f]["freshness"]["status"] == "fresh" for f in required)]
        sample = sorted(eligible, key=lambda p: (-sum(by_id[p["id"]]["fields"][f]["state"] == "confirmed" for f in required), p["id"]))[:5]
        scenarios[name] = {"required_fields": required, "candidate_count": len(eligible),
            "source_supported_all_requirements": len(complete), "fresh_checked_all_requirements": len(fresh),
            "curator_sample": [{"id": p["id"], "name": p["name"], "review_status": "pending_source_or_human_check",
                                "requirements": {f: by_id[p["id"]]["fields"][f] for f in required}} for p in sample]}
    license_queue = [{"id": p["id"], "source_url": p.get("description_url") or p.get("source_url"),
                      "license": p.get("description_license"), "attribution": p.get("description_attribution"),
                      "publication_status": "held_pending_license_review", "required_action": "Verify terms and required attribution before publishing narrative"}
                     for p in rows if p.get("description_kind") == "source" and p.get("description_license") in (None, "", "not_specified", "unknown")]
    groups = defaultdict(list)
    for row in rows:
        groups[_key(row["name"])].append(row)
    from rag.geo import haversine_m
    duplicates = []
    for group in groups.values():
        for a, b in combinations(sorted(group, key=lambda p: p["id"]), 2):
            distance = haversine_m(a["lat"], a["lon"], b["lat"], b["lon"])
            if distance >= 50:
                continue
            key = "|".join(sorted((a["id"], b["id"])))
            decision = decisions.get(key, {})
            if decision and (decision.get("decision") not in {"merge", "keep", "unresolved"} or not decision.get("reason") or not decision.get("evidence_urls")):
                raise ValueError("Duplicate decision requires valid disposition, reason and evidence: " + key)
            duplicates.append({"pair_id": key, "source_ids": sorted(set(source_ids(a) + source_ids(b))),
                "distance_m": round(distance, 3), "records": [{k: p.get(k) for k in ("id", "name", "category", "address", "phone", "website", "source_url")} for p in (a, b)],
                **({"decision": "unresolved", "reason": "Nearby same-name candidates require contact/address/entity-scope evidence", "evidence_urls": []} | decision)})
    return {"schema_version": 1, "as_of": as_of,
        "definitions": {"confirmed": "Non-conflicting attributed source assertion; freshness and real-world verification are separate",
                        "unknown": "No attributable field evidence; category/name/template never establishes amenities",
                        "source_updated_at": "Source revision date, not a field check", "built_at": "Export date, never a field check"},
        "canonical_count": len(rows), "active_count": len(active), "source_id_count": len({i for p in rows for i in source_ids(p)}),
        "field_state_counts": {f: dict(Counter(r["fields"][f]["state"] for r in field_review)) for f in FIELDS},
        "scenarios": scenarios, "field_review": field_review,
        "freshness_queue": [{"id": r["id"], "field": f, **r["fields"][f]["freshness"]} for r in field_review for f in FIELDS
                            if r["fields"][f]["evidence"] and r["fields"][f]["freshness"]["status"] != "fresh"],
        "classification_queue": [{"id": p["id"], "name": p["name"], "category": p["category"],
            "status": "unverified", "source_ids": source_ids(p), "source_url": p.get("source_url")}
            for p in active if "source_classification_unverified" in p.get("quality_flags", [])],
        "license_queue": license_queue, "duplicates": sorted(duplicates, key=lambda p: p["pair_id"]),
        "duplicate_decision_counts": dict(Counter(p["decision"] for p in duplicates)), "graph_coverage": graph_coverage(active, graph_path)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--processed-dir", type=Path, default=ROOT / "data/processed")
    parser.add_argument("--raw-dir", type=Path)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    from data.snapshot import resolve_snapshot
    from data.provenance import cached_field_evidence
    from ayat_backend.app.team_data import load_team_snapshot
    handle = resolve_snapshot(args.processed_dir)
    canonical = handle.path / "pois.json"
    rows = json.loads(canonical.read_bytes())
    evidence_path = handle.path / "field_evidence.json"
    evidence = (cached_field_evidence(args.raw_dir, rows) if args.raw_dir else
                json.loads(evidence_path.read_bytes()) if evidence_path.exists() else {})
    reviews = handle.path / "quarantine.json" if handle.version != "legacy" else ROOT / "data/quarantine.json"
    active, _, meta = load_team_snapshot(canonical, quarantine_path=reviews if reviews.exists() else None)
    decisions_path = ROOT / "data/duplicate_decisions.json"
    decisions = json.loads(decisions_path.read_bytes()) if decisions_path.exists() else {}
    report = build_review(rows, active, as_of=args.as_of, external=evidence, decisions=decisions,
                          graph_path=handle.path / "walk_graph.npz")
    report["inputs"] = {"snapshot_version": handle.version, "canonical_sha256": hashlib.sha256(canonical.read_bytes()).hexdigest(),
                        "review_sha256": hashlib.sha256(reviews.read_bytes()).hexdigest() if reviews.exists() else None,
                        "decisions_sha256": hashlib.sha256(decisions_path.read_bytes()).hexdigest() if decisions_path.exists() else None}
    report["exclusions"] = meta["excluded_records"]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name, value in (("quality_review.json", report), ("field_evidence.json", evidence)):
        (args.output_dir / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"canonical": len(rows), "active": len(active), "duplicate_decisions": report["duplicate_decision_counts"],
                      "license_holds": len(report["license_queue"]), "graph": report["graph_coverage"]["status"]}))


if __name__ == "__main__":
    main()

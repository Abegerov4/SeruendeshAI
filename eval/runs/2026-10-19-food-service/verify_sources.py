"""Verify published food evidence, original IDs and the offline dense index."""
import hashlib
import json
from pathlib import Path

from data.snapshot import resolve_snapshot
from data.place_details import load_place_details
from ayat_backend.app.team_data import load_team_snapshot
from ayat_backend.app.canonical_index import load_index, policy_hashes


def main():
    snapshot = resolve_snapshot(Path("data/processed"))
    digest = hashlib.sha256((snapshot.path / "pois.json").read_bytes()).hexdigest()
    details = load_place_details(snapshot.path / "place_details.json", canonical_sha256=digest, as_of="2026-10-19")
    pois, origins, manifest = load_team_snapshot(snapshot.path / "pois.json", quarantine_path=snapshot.path / "quarantine.json")
    matrix = load_index(pois, "e5-small", snapshot.path, policy_hashes=policy_hashes(snapshot.path))
    menus = [item for record in details.values() for item in record["menu_items"]]
    reviews = json.loads(Path("data/review/2026-10-19-food-service/classification-review.json").read_bytes())
    by_id = {row["id"]: row for row in pois}
    checks = {
        "master_unchanged": digest == "803dcffdb4473abddfc97be9cab5a41bc663ee74afc67c560f1723b42f8c1e63",
        "source_ids_preserved": manifest["preserved_source_ids_count"] == 14607,
        "reviewed_categories_applied": all(by_id[r["canonical_id"]]["category"] == r["value"] for r in reviews["reviews"]),
        "italio_102": len(details["overture:b6f93c10-c613-4dea-bf99-4a468890fbcf"]["menu_items"]) == 102,
        "coffeehub_kitchen": any(f["field"] == "kitchen_hours" and f["value"] == "Mo-Su 08:00-21:30"
                                 for f in details["osm:node/12135856708"]["facts"]),
        "index_rows_match": matrix.shape == (len(pois), 384),
    }
    report = {
        "snapshot_version": snapshot.version, "canonical_sha256": digest, "canonical_records": 14006,
        "preserved_source_ids": manifest["preserved_source_ids_count"], "active_pois": len(pois), "origins": len(origins),
        "rich_branches": len(details), "facts": sum(len(r["facts"]) for r in details.values()),
        "menu_items": len(menus), "menu_branches": sum(bool(r["menu_items"]) for r in details.values()),
        "dine_in_items": sum((item.get("price") or {}).get("channel") == "dine_in" for item in menus),
        "partial_cost_items": sum(item.get("cost", {}).get("complete") is False for item in menus),
        "complete_cost_items": sum(item.get("cost", {}).get("complete") is True for item in menus),
        "kitchen_hour_branches": sum(any(f["field"] == "kitchen_hours" for f in r["facts"]) for r in details.values()),
        "classification_corrections": len(reviews["reviews"]), "index_shape": list(matrix.shape),
        "checks": checks, "passed": all(checks.values()),
    }
    Path("eval/runs/2026-10-19-food-service/source-index-verification.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False))
    assert report["passed"]


if __name__ == "__main__":
    main()

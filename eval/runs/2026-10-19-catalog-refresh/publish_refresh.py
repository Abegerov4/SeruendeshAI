"""Publish reviewed sidecars against the unchanged master and a local dense index.

Run from repository root with the existing venv; no external model/API calls.
All validation/index work completes before the atomic current-pointer change.
"""
from collections import Counter
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import tempfile
from zoneinfo import ZoneInfo

from data.snapshot import publish_snapshot, resolve_snapshot
from data.place_details import load_place_details, apply_place_details
from data.city_services import load_city_services
from data.eligibility import apply_fact_reviews
from ayat_backend.app.team_data import load_team_snapshot
from ayat_backend.app.canonical_index import build_index, load_index, policy_hashes
from ayat_backend.app.embedder import Embedder

ROOT = Path.cwd()
OUT = ROOT / "eval/runs/2026-10-19-catalog-refresh"


def encode(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+"\n").encode()


def main():
    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
    prior = resolve_snapshot(ROOT/"data/processed")
    raw = (prior.path/"pois.json").read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    today = datetime.now(ZoneInfo("Asia/Almaty")).date()
    master = json.loads(raw)
    files = {name:(prior.path/name).read_bytes() for name in prior.manifest["files"]
             if not name.startswith("vectors-") and name != "canonical_index_manifest.json"}
    source = ROOT/"data/sources/place_details_2026-10-19.json"
    payload = json.loads(source.read_bytes())
    source_hashes = {str(source.relative_to(ROOT)):hashlib.sha256(source.read_bytes()).hexdigest()}
    known = {r["canonical_id"] for r in payload["records"]}
    overlap = []
    extras = [ROOT/"data/sources/place_details_discovery_2026-10-19.json",
              ROOT/"data/review/2026-10-19-refresh/discovery-gasteria.json"]
    for extra in extras:
        if not extra.exists():
            continue
        more = json.loads(extra.read_bytes())
        if more["canonical_sha256"] != digest:
            raise ValueError("Discovery sidecar belongs to another master")
        source_hashes[str(extra.relative_to(ROOT))] = hashlib.sha256(extra.read_bytes()).hexdigest()
        for record in more["records"]:
            if record["canonical_id"] in known:
                overlap.append(record["canonical_id"])
                continue  # Do not rewrite source-branch confirmations to force a merge.
            payload["records"].append(record)
            known.add(record["canonical_id"])
    menus = ROOT/"data/sources/place_menus_full_2026-10-19.json"
    if menus.exists():
        menu_payload = json.loads(menus.read_bytes())
        if menu_payload["canonical_sha256"] != digest:
            raise ValueError("Full menus belong to another master")
        source_hashes[str(menus.relative_to(ROOT))] = hashlib.sha256(menus.read_bytes()).hexdigest()
        by_id = {r["canonical_id"]:r for r in payload["records"]}
        for record in menu_payload["records"]:
            current = by_id.get(record["canonical_id"])
            if not current or current["identity"] != record["identity"]:
                raise ValueError("Full-menu branch identity differs from accepted source identity")
            current["menu_items"] = record["menu_items"]
    files["place_details.json"] = encode(payload)
    service_source = ROOT/"data/sources/city_services_2026-10-19.json"
    files["city_services.json"] = service_source.read_bytes()
    source_hashes[str(service_source.relative_to(ROOT))] = hashlib.sha256(files["city_services.json"]).hexdigest()
    files["quarantine.json"] = (ROOT/"data/quarantine.json").read_bytes()
    coordinate_source = ROOT/"data/review/2026-10-19-refresh/coordinate-review.json"
    if coordinate_source.exists():
        coordinates = json.loads(coordinate_source.read_bytes())
        if coordinates["canonical_sha256"] != digest:
            raise ValueError("Coordinate review belongs to another master")
        review_payload = json.loads(files["fact_reviews.json"])
        replaced = {(r["canonical_id"],r["field"]) for r in coordinates["reviews"]}
        review_payload["reviews"] = [r for r in review_payload["reviews"]
            if (r["canonical_id"],r["field"]) not in replaced] + coordinates["reviews"]
        files["fact_reviews.json"] = encode(review_payload)
        source_hashes[str(coordinate_source.relative_to(ROOT))] = hashlib.sha256(coordinate_source.read_bytes()).hexdigest()
    with tempfile.TemporaryDirectory(prefix="seru-refresh-") as temp:
        stage = Path(temp)
        for name,value in files.items():
            (stage/name).write_bytes(value)
        details = load_place_details(stage/"place_details.json",canonical_sha256=digest,as_of=today)
        attached = apply_place_details(master,details)
        attached = apply_fact_reviews(attached,json.loads(files["fact_reviews.json"]),canonical_sha256=digest)
        attached_ids = {r["id"] for r in attached if r.get("place_details")}
        if attached_ids != set(details):
            raise ValueError("Accepted branch details failed canonical identity binding")
        services = load_city_services(stage/"city_services.json")
        pois,gaz,view = load_team_snapshot(stage/"pois.json",quarantine_path=stage/"quarantine.json")
        active = {r["id"] for r in pois}
        files["pois_leisure.json"] = encode([r for r in attached if r["id"] in active])
        index = build_index(pois,Embedder("e5-small"),stage,policy_hashes=policy_hashes(stage))
        load_index(pois,"e5-small",stage,policy_hashes=policy_hashes(stage))
        files["canonical_index_manifest.json"] = encode(index)
        files[index["artifact"]] = (stage/index["artifact"]).read_bytes()
        refresh = {
            "checked_at":today.isoformat(), "published_at":datetime.now(ZoneInfo("Asia/Almaty")).isoformat(),
            "scope":"Bounded public-source enrichment; whole catalog audited, not every branch independently verified",
            "canonical_sha256":digest,"canonical_records":len(master),"active_recommendation_records":len(pois),
            "gazetteer_records":len(gaz),"preserved_source_ids":view["preserved_source_ids_count"],
            "accepted_detail_branches":len(details),"detail_counts":{
                k:sum(len(r[k]) for r in details.values()) for k in ("facts","menu_items","prices")},
            "services":len(services.services),"source_hashes":source_hashes,
            "discovery_overlap_held":overlap,"archived_canonical_ids":view["archived_canonical_ids"],
            "dense_index_rows":index["rows"],"dense_index_model":index["model"],
            "source_audit":"eval/runs/2026-10-19-catalog-refresh/source-audit/summary.json",
        }
        stats=json.loads(files["stats.json"])
        stats["derived_refresh"] = refresh
        files["stats.json"] = encode(stats)
        reviews=json.loads(files.get("review_manifest.json",b"{}"))
        reviews["catalog_refresh"] = refresh
        files["review_manifest.json"] = encode(reviews)
        published = publish_snapshot(ROOT/"data/processed",files)
    resolved=resolve_snapshot(ROOT/"data/processed")
    assert resolved.version == published.version
    assert hashlib.sha256((resolved.path/"pois.json").read_bytes()).hexdigest() == digest
    report={**refresh,"version":published.version,"prior_version":prior.version,
            "bundle_files":len(published.manifest["files"]),"quality_gates":published.manifest["quality_gates"]}
    (OUT/"publication.json").write_bytes(encode(report))
    print(json.dumps(report,ensure_ascii=False))


if __name__ == "__main__":
    main()

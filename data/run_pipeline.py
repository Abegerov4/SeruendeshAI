"""Uncapped, cached Astana POI collection. Run from any working directory."""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import importlib
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data.collect.normalize import normalize_candidates
from data.collect.web_sources import attach_directory_facts, cached_descriptions
from data.collect.quality import apply_quality_overrides

SOURCES = ("osm", "overture", "wikimedia", "web", "geonames")
MODULES = {"osm": "osm_overpass", "overture": "overture", "wikimedia": "enrich_wiki", "web": "web_sources", "geonames": "geonames"}


def read_json(path, default=None):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def cached_source(folder):
    pois = read_json(folder / "candidates.json", [])
    report = read_json(folder / "report.json", {})
    if not pois:
        report = {**report, "status": "unavailable", "cache_note": "No nonempty candidate cache available"}
    return {"pois": pois, "unlocated": read_json(folder / "unlocated.json", []), "report": {**report, "pipeline_used_cache": True}}


def acquire(source, folder, bbox, refresh, offline):
    if offline:
        return cached_source(folder)
    previous = cached_source(folder)
    try:
        module = importlib.import_module("data.collect." + MODULES[source])
        result = module.collect(folder, bbox=bbox, refresh=refresh)
        if source == "osm" and not result["pois"]:
            # Public regional extract is a reproducible alternative to unavailable Overpass.
            path = module.download_extract(folder, refresh=False)
            result = module.collect_file(path, folder, bbox=bbox, refresh=refresh)
        if not result["pois"]:
            if previous["pois"]:
                previous["report"].update(status="partial", latest_attempt=result.get("report"), stale_cache=True)
                write_json(folder / "candidates.json", previous["pois"])
                write_json(folder / "report.json", previous["report"])
                return previous
        return result
    except Exception as error:
        result = previous
        result["report"].update(status="partial" if result["pois"] else "unavailable",
                                latest_error=f"{type(error).__name__}: {error}", stale_cache=bool(result["pois"]))
        if result["pois"]:
            write_json(folder / "candidates.json", result["pois"])
            write_json(folder / "report.json", result["report"])
        return result


def _bbox(boundary):
    if not boundary:
        return (50.8, 71.0, 51.4, 71.9)
    from shapely.geometry import shape
    geometry = boundary.get("geometry", boundary)
    west, south, east, north = shape(geometry).bounds
    return (south, west, north, east)


def _fingerprint(candidates):
    return hashlib.sha256(json.dumps(candidates, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def _refresh_fact_reviews(prior, pois, canonical_bytes):
    """Carry manual decisions only for the identical full canonical record.

    A changed record retains its old confirmation as pending, with the original
    decision and hash in history. Disputes remain active until manually resolved.
    The new binding hashes the exact bytes handed to the atomic publisher.
    """
    from data.eligibility import apply_fact_reviews
    previous_bytes = (prior.path / "pois.json").read_bytes()
    previous_sha = hashlib.sha256(previous_bytes).hexdigest()
    previous = json.loads(previous_bytes)
    payload = read_json(prior.path / "fact_reviews.json")
    # Never repair a corrupt or stale binding merely by replacing its hash.
    apply_fact_reviews(previous, payload, canonical_sha256=previous_sha)
    old_by_id = {row["id"]: row for row in previous}
    new_by_id = {row["id"]: row for row in pois}
    refreshed = deepcopy(payload)
    for review in refreshed["reviews"]:
        ident = review["canonical_id"]
        if review["status"] == "accepted" and old_by_id.get(ident) != new_by_id.get(ident):
            original = deepcopy(review)
            review.setdefault("review_history", []).append({"canonical_sha256": previous_sha, "review": original})
            review["status"] = "pending"
            review["reason"] = "Canonical record changed during refresh; manual confirmation required."
    refreshed["canonical_sha256"] = hashlib.sha256(canonical_bytes).hexdigest()
    return refreshed


def _refresh_place_details(prior, pois, canonical_bytes):
    """Carry rich evidence only for identical source rows; archive changed bindings."""
    from data.place_details import load_place_details
    previous_bytes = (prior.path / "pois.json").read_bytes()
    previous_sha = hashlib.sha256(previous_bytes).hexdigest()
    payload = read_json(prior.path / "place_details.json")
    load_place_details(prior.path / "place_details.json",canonical_sha256=previous_sha)
    previous = {row["id"]:row for row in json.loads(previous_bytes)}
    current = {row["id"]:row for row in pois}
    refreshed = deepcopy(payload)
    retained = []
    for record in refreshed["records"]:
        ident = record["canonical_id"]
        if previous.get(ident) == current.get(ident) and ident in current:
            retained.append(record)
        else:
            refreshed.setdefault("pending_records",[]).append({"canonical_sha256":previous_sha,"record":record,
                "reason":"Canonical record changed or disappeared; branch facts need re-verification."})
    refreshed["records"] = retained
    refreshed["canonical_sha256"] = hashlib.sha256(canonical_bytes).hexdigest()
    return refreshed


def _apply_description_patches(candidates, patches):
    """Update source text only; a listing cache cannot create or relocate a POI."""
    fields = {"description", "description_source", "description_kind", "description_source_detail",
              "description_url", "description_license", "description_attribution", "held_description",
              "description_review_status", "description_review_reason", "description_review_evidence"}
    by_id = {}
    for patch in patches:
        unexpected = set(patch) - fields - {"id"}
        if unexpected or not isinstance(patch.get("id"), str) or patch["id"] in by_id:
            raise ValueError(f"Invalid description patch: {patch.get('id')}; unsupported fields: {sorted(unexpected)}")
        by_id[patch["id"]] = patch
    present = {poi["id"] for poi in candidates}
    updated = [{**poi, **deepcopy({key: value for key, value in by_id.get(poi["id"], {}).items() if key != "id"})}
               for poi in candidates]
    return updated, {"applied_source_ids": sorted(present & by_id.keys()),
                     "unmatched_source_ids": sorted(by_id.keys() - present)}


def _stats(pois, quality, reports):
    total = len(pois)
    counts = {key: sum(p.get(key) is not None for p in pois) for key in
              ("description", "opening_hours", "rating", "wheelchair", "address", "phone", "website", "name_en", "name_kk")}
    participation = Counter(source for p in pois for source in {r["source"] for r in p["source_records"]})
    return {**quality, "field_counts": counts,
            "field_coverage_percent": {key: round(value / total * 100, 2) for key, value in counts.items()},
            "source_participation": dict(sorted(participation.items())),
            "leisure_count": sum(p["category"] != "other" for p in pois),
            "source_status": {key: value.get("status", "partial" if value.get("complete") is False else "ok") for key, value in reports.items()}}


def stats_markdown(stats):
    lines = ["# Данные POI Астаны", "", f"Собрано **{stats['output_count']:,}** уникальных именованных объектов без лимита количества.",
             f"Из них **{stats['leisure_count']:,}** относятся к категориям прогулок, еды, культуры, спорта и досуга; остальные сохранены с категорией `other`.",
             "", f"География: `{stats['boundary_mode']}`. Отброшено записей: {stats['rejected_count']}; объединено дублей: {stats['merged_count']}.",
             "", "## Заполненность", "", "| Поле | Объектов | Доля |", "|---|---:|---:|"]
    for key, count in stats["field_counts"].items():
        lines.append(f"| {key} | {count} | {stats['field_coverage_percent'][key]:.2f}% |")
    lines += ["", f"Авторские описания из источников: **{stats['source_description_count']}**. Фактические шаблоны из структурированных полей: **{stats['template_description_count']}**.",
              "Шаблоны отмечены `description_kind=structured_template`, отдельно от исходных описаний. LLM не использовалась. Шаблоны не подтверждают тишину, розетки, Wi-Fi, цены или пригодность для детей.",
              "Неизвестные часы, рейтинги и доступность остаются null. Наличие объекта в источнике не доказывает, что он работает сегодня.",
              "", "## Категории", "", "| Категория | Объектов |", "|---|---:|"]
    lines += [f"| {key} | {value} |" for key, value in stats["categories"].items()]
    lines += ["", "## Источники", "", "| Источник | Участие в итоговых POI | Статус сбора |", "|---|---:|---|"]
    for source in sorted(set(stats["source_status"]) | set(stats["source_participation"])):
        lines.append(f"| {source} | {stats['source_participation'].get(source, 0)} | {stats['source_status'].get(source, 'см. manifest')} |")
    lines += ["", "Полные ошибки, даты, релизы, ограничения и лицензии находятся в `processed/source_manifest.json`; первичные записи каждого объекта — в `source_records`.",
              "Это доступное покрытие перечисленных источников, а не перепись всех заведений города. Сайты без установленной лицензии отмечены отдельно; публичный доступ не равен открытой лицензии.", ""]
    return "\n".join(lines)


def run_pipeline(raw_dir=ROOT / "data/raw", processed_dir=ROOT / "data/processed", *,
                 sources=SOURCES, offline=False, refresh=False, allow_bbox=False,
                 wiki_enrichment=True):
    raw_dir, processed_dir = Path(raw_dir), Path(processed_dir)
    boundary = read_json(raw_dir / "osm/boundary.geojson")
    results, reports = {}, {}
    for source in sources:
        print(f"Collecting {source}{' (cache only)' if offline else ''}...", flush=True)
        results[source] = acquire(source, raw_dir / source, _bbox(boundary), refresh, offline)
        reports[source] = results[source]["report"]
        source_date = reports[source].get("collected_at") or reports[source].get("finished_at")
        for poi in results[source]["pois"]:
            if not poi.get("collected_at") and source_date:
                poi["collected_at"] = source_date
        if source == "osm":
            snapshot = read_json(raw_dir / "osm/pbf_download.json")
            if snapshot:
                reports[source]["extract_snapshot"] = snapshot
        if source == "osm":
            boundary = results[source].get("boundary") or read_json(raw_dir / "osm/boundary.geojson") or boundary
    if not boundary and not allow_bbox:
        raise RuntimeError("Administrative boundary unavailable; previous exports preserved. Use --allow-bbox only for explicitly approximate output.")
    candidates = [poi for result in results.values() for poi in result["pois"]]
    overrides = read_json(ROOT / "data/quality_overrides.json", {})
    candidates, quarantined, review = apply_quality_overrides(candidates, overrides)
    if not candidates:
        raise RuntimeError("No source candidates available; previous exports preserved")
    # Match directory facts after base deduplication, so equivalent source IDs are not false ambiguities.
    facts = results.get("web", {}).get("unlocated", [])
    seed, _ = normalize_candidates(candidates, boundary)
    attached, unresolved = attach_directory_facts(seed, facts)
    reports.setdefault("directory_join", {}).update(attached=len(attached), unresolved=len(unresolved),
                                                   rule="unique exact name, compatible category, and verified street/house or mall scope; no guessed coordinates")
    candidates.extend(attached)
    if wiki_enrichment and not offline and "wikimedia" in sources:
        try:
            from data.collect.enrich_wiki import enrich
            input_fingerprint = _fingerprint(candidates)
            result = enrich(candidates, raw_dir / "wikimedia", refresh=refresh)
            candidates = result["pois"]
            reports["wikimedia_enrichment"] = result["report"]
            write_json(raw_dir / "enriched_candidates.json", candidates)
            write_json(raw_dir / "enrichment_input.json", {"sha256": input_fingerprint})
        except Exception as error:
            reports["wikimedia_enrichment"] = {"status": "unavailable", "error": f"{type(error).__name__}: {error}"}
    elif offline:
        # Reuse enrichment only when every current record is represented: never silently drop newer candidates.
        fingerprint = read_json(raw_dir / "enrichment_input.json", {}).get("sha256")
        enriched = read_json(raw_dir / "enriched_candidates.json", []) if fingerprint == _fingerprint(candidates) else []
        lookup = {p["id"]: p for p in enriched}
        candidates = [lookup.get(p["id"], p) for p in candidates]
        if enriched:
            reports["wikimedia_enrichment"] = read_json(raw_dir / "wikimedia/enrichment_report.json", {"status": "cached"})
    # Source text and new review decisions are intentionally applied after exact
    # Wiki-cache matching, so they cannot invalidate or bypass its input guard.
    patches, description_report = cached_descriptions(raw_dir / "web")
    candidates, applied = _apply_description_patches(candidates, patches)
    if patches or description_report.get("cache_reads"):
        reports["cached_descriptions"] = {**description_report, **applied}
    candidates, post_quarantined, post_review = apply_quality_overrides(candidates, overrides, phase="after_enrichment")
    quarantined.extend(post_quarantined)
    review["quarantine_count"] += post_review["quarantine_count"]
    review["applied_overrides"].extend(post_review["applied_overrides"])
    pois, quality = normalize_candidates(candidates, boundary)
    quality.update(review)
    if not pois:
        raise RuntimeError("All candidates rejected; previous exports preserved")
    stats = _stats(pois, quality, reports)
    incomplete = any(r.get("status") in {"partial", "unavailable", "error", "failed", "stale_cache"} or r.get("complete") is False for r in reports.values())
    manifest = {"status": "partial" if incomplete else "ok", "generated_at": datetime.now(timezone.utc).isoformat(),
                "city": "Astana", "record_limit": None, "offline": offline,
                "boundary": {"mode": quality["boundary_mode"], "source_url": "https://www.openstreetmap.org/relation/3087155" if boundary else None,
                             "license": "ODbL-1.0" if boundary else None, "bbox": _bbox(boundary)},
                "sources": reports, "quality": quality,
                "licensing_note": "Mixed-source database: retain record-level attribution and upstream obligations; no blanket open licence asserted."}
    from data.snapshot import publish_snapshot, resolve_snapshot
    artifacts = {"pois.json": pois, "pois_leisure.json": [p for p in pois if p["category"] != "other"],
                 "source_manifest.json": manifest, "unlocated_facts.json": unresolved,
                 "quarantined_pois.json": quarantined, "stats.json": stats, "stats.md": stats_markdown(stats)}
    if boundary:
        artifacts["boundary.geojson"] = boundary
    # Freeze all runtime sidecars and review decisions with the same selected POIs.
    prior = resolve_snapshot(processed_dir)
    for name in ("events.jsonl", "gazetteer.json", "river.json", "walk_graph.npz", "astana_boundary.geojson", "field_evidence.json"):
        path = prior.path / name
        if path.exists():
            artifacts[name] = path.read_bytes()
    for name in ("quarantine.json", "quality_overrides.json"):
        previous = prior.path / name
        path = ROOT / "data" / name
        if name == "quarantine.json" and previous.exists():
            # Empty/missing local files cannot implicitly revoke an exclusion.
            retained = read_json(previous)
            for decision in read_json(path, []):
                if decision not in retained:
                    retained.append(decision)
            artifacts[name] = retained
        elif path.exists():
            artifacts[name] = path.read_bytes()
        elif previous.exists():
            artifacts[name] = previous.read_bytes()
    if (prior.path / "fact_reviews.json").exists():
        canonical_bytes = (json.dumps(pois, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()
        artifacts["pois.json"] = canonical_bytes
        artifacts["fact_reviews.json"] = _refresh_fact_reviews(prior, pois, canonical_bytes)
    if (prior.path / "place_details.json").exists():
        canonical_bytes = artifacts.get("pois.json")
        if not isinstance(canonical_bytes,bytes):
            canonical_bytes = (json.dumps(pois,ensure_ascii=False,indent=2,allow_nan=False)+"\n").encode()
            artifacts["pois.json"] = canonical_bytes
        artifacts["place_details.json"] = _refresh_place_details(prior,pois,canonical_bytes)
    if (prior.path / "city_services.json").exists():
        artifacts["city_services.json"] = (prior.path / "city_services.json").read_bytes()
    published = publish_snapshot(processed_dir, artifacts, required_sources=sources)
    manifest["snapshot_version"] = published.version
    # Human-readable compatibility report is not used by runtime snapshot readers.
    (processed_dir.parent / "stats.md").write_text(stats_markdown(stats), encoding="utf-8")
    print(f"Exported {len(pois)} POIs; {stats['leisure_count']} in leisure categories; status={manifest['status']}", flush=True)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=ROOT / "data/raw")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "data/processed")
    parser.add_argument("--sources", nargs="+", choices=SOURCES, default=list(SOURCES))
    parser.add_argument("--offline", action="store_true", help="Rebuild solely from local caches; no network requests")
    parser.add_argument("--refresh", action="store_true", help="Refresh source responses; may download a regional extract")
    parser.add_argument("--allow-bbox", action="store_true", help="Allow explicitly approximate output if no boundary is cached")
    parser.add_argument("--no-wiki-enrichment", action="store_true")
    args = parser.parse_args()
    run_pipeline(args.raw_dir, args.output_dir, sources=tuple(args.sources), offline=args.offline,
                 refresh=args.refresh, allow_bbox=args.allow_bbox, wiki_enrichment=not args.no_wiki_enrichment)


if __name__ == "__main__":
    main()

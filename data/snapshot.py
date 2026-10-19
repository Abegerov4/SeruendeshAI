"""Immutable local data bundles; resolve once per runtime, restart to adopt a version.

``current`` is the only publication pointer. Legacy fixed files are read only when
there is no pointer (or ``legacy=True``); they are never a fallback for a corrupt
active bundle. Publisher failures retain staging/rejection evidence for review.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
import uuid

REQUIRED = {"pois.json", "pois_leisure.json", "source_manifest.json", "stats.json"}
POLICY_SIDECARS = {"quarantine.json", "quality_overrides.json", "field_evidence.json", "fact_reviews.json", "place_details.json", "city_services.json"}
BAD_STATUS = {"partial", "unavailable", "error", "failed", "stale_cache"}


@dataclass(frozen=True)
class SnapshotHandle:
    path: Path
    version: str
    manifest: dict


class SnapshotRejected(RuntimeError):
    pass


def _json(path, default):
    return json.loads(path.read_bytes()) if path.exists() else default


def _sync_dir(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def resolve_snapshot(processed_dir, *, legacy=False) -> SnapshotHandle:
    root = Path(processed_dir).absolute()
    pointer = root / "current"
    if legacy or not pointer.is_symlink():
        if pointer.exists() and not legacy:
            raise ValueError("Snapshot current pointer must be a symlink")
        return SnapshotHandle(root, "legacy", {})
    path = pointer.resolve(strict=True)
    if path.parent != (root / ".snapshots").resolve():
        raise ValueError("Snapshot pointer escapes version directory")
    manifest = _json(path / "bundle_manifest.json", {})
    if manifest.get("version") != path.name or not REQUIRED <= manifest.get("files", {}).keys():
        raise ValueError("Invalid snapshot bundle manifest")
    for name, meta in manifest["files"].items():
        if Path(name).name != name:
            raise ValueError("Invalid snapshot artifact name")
        raw = (path / name).read_bytes()
        if hashlib.sha256(raw).hexdigest() != meta["sha256"] or len(raw) != meta["bytes"]:
            raise ValueError("Snapshot file hash mismatch: " + name)
    return SnapshotHandle(path, manifest["version"], manifest)


def _source_ids(rows):
    return {ident for row in rows for ident in [row["id"], *(s["id"] for s in row.get("source_records", []) if s.get("id"))]}


def publish_snapshot(processed_dir, artifacts, *, required_sources=(), approved_removed_ids=(),
                     approved_removed_sidecars=None, fault=None):
    """Stage, validate and atomically promote artifacts; return a bound handle.

    Missing source IDs require an explicit, reviewed ``approved_removed_ids``
    list. A >10% total/category loss is independently blocked. Required sources
    cannot regress to partial/unavailable after an existing usable publication.
    Bootstrap partial data remains labelled partial rather than called verified.
    ``fault(stage)`` is an optional fault-injection callback for recovery tests.
    """
    root = Path(processed_dir).absolute()
    root.mkdir(parents=True, exist_ok=True)
    versions = root / ".snapshots"
    versions.mkdir(exist_ok=True)
    if not REQUIRED <= artifacts.keys() or any(Path(n).name != n for n in artifacts):
        raise ValueError("Incomplete bundle or invalid artifact name")
    approvals = approved_removed_sidecars or {}
    from datetime import date
    from urllib.parse import urlsplit
    if not isinstance(approvals, dict) or not set(approvals) <= POLICY_SIDECARS:
        raise ValueError("Invalid approved policy sidecar removals")
    for name, review in approvals.items():
        if not isinstance(review, dict) or any(not isinstance(review.get(k), str) or not review[k].strip()
                                              for k in ("reason", "reviewed_by", "reviewed_on")):
            raise ValueError("Sidecar removal requires a reviewed reason, reviewer and date")
        date.fromisoformat(review["reviewed_on"])
        urls = review.get("evidence_urls")
        if not isinstance(urls, list) or not urls or any(not isinstance(u, str) or urlsplit(u).scheme not in {"http", "https"} or not urlsplit(u).hostname for u in urls):
            raise ValueError("Sidecar removal requires supporting evidence URLs")
        if name in artifacts:
            raise ValueError("Sidecar cannot be both published and approved for removal")
    def checkpoint(name):
        if fault:
            fault(name)
    # Serialize publishers, including baseline comparison and pointer replacement.
    with (root / ".publish.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        prior = resolve_snapshot(root)
        version = uuid.uuid4().hex
        stage = versions / (version + ".staging")
        stage.mkdir()
        files = {}
        for name, value in artifacts.items():
            checkpoint("write:" + name)
            raw = value if isinstance(value, bytes) else (value.encode() if isinstance(value, str) else
                  (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode())
            with (stage / name).open("wb") as target:
                target.write(raw)
                target.flush()
                os.fsync(target.fileno())
            files[name] = {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
        rows = _json(stage / "pois.json", [])
        if (stage / "place_details.json").exists():
            from data.place_details import load_place_details
            from datetime import datetime
            from zoneinfo import ZoneInfo
            load_place_details(stage / "place_details.json",canonical_sha256=files["pois.json"]["sha256"],
                as_of=datetime.now(ZoneInfo("Asia/Almaty")).date())
        if (stage / "city_services.json").exists():
            from data.city_services import load_city_services
            load_city_services(stage / "city_services.json")
        if (stage / "fact_reviews.json").exists():
            from data.eligibility import apply_fact_reviews
            apply_fact_reviews(rows, _json(stage / "fact_reviews.json", {}),
                               canonical_sha256=files["pois.json"]["sha256"])
        old = _json(prior.path / "pois.json", [])
        source_manifest = _json(stage / "source_manifest.json", {})
        reasons = ["missing_policy_sidecar:" + name for name in sorted(POLICY_SIDECARS)
                   if (prior.path / name).exists() and name not in artifacts and name not in approvals]
        if not rows or len({r["id"] for r in rows}) != len(rows):
            reasons.append("empty_or_duplicate_ids")
        lost = _source_ids(old) - _source_ids(rows) - set(approved_removed_ids)
        if lost:
            reasons.append("lost_source_ids:" + ",".join(sorted(lost)))
        if len(rows) < .9 * len(old):
            reasons.append("count_retention_below_90_percent")
        for category in {r.get("category") for r in old}:
            previous = sum(r.get("category") == category for r in old)
            if sum(r.get("category") == category for r in rows) < .9 * previous:
                reasons.append("category_loss:" + str(category))
        if old:
            for source in required_sources:
                report = source_manifest.get("sources", {}).get(source, {})
                if not report or report.get("status") in BAD_STATUS or report.get("complete") is False:
                    reasons.append("required_source_incomplete:" + source)
        checkpoint("validate")
        if reasons:
            (versions / (version + ".rejected.json")).write_text(json.dumps({"version": version, "reasons": reasons,
                "prior_version": prior.version, "staging_path": stage.name}, indent=2) + "\n")
            raise SnapshotRejected("Snapshot rejected: " + "; ".join(reasons))
        checkpoint("manifest")
        manifest = {"schema_version": 1, "version": version, "files": files,
                    "prior_version": prior.version, "quality_gates": "passed",
                    "approved_removed_ids": sorted(approved_removed_ids), "approved_removed_sidecars": approvals}
        with (stage / "bundle_manifest.json").open("w") as target:
            json.dump(manifest, target, indent=2)
            target.write("\n")
            target.flush()
            os.fsync(target.fileno())
        _sync_dir(stage)
        checkpoint("freeze")
        final = versions / version
        stage.rename(final)
        _sync_dir(versions)
        checkpoint("before_pointer")
        temporary = root / (".current-" + version)
        temporary.symlink_to(Path(".snapshots") / version, target_is_directory=True)
        os.replace(temporary, root / "current")
        _sync_dir(root)
        # Compatibility names on a new output dir follow the single pointer.
        # Existing fixed snapshots remain intact for explicit legacy consumers.
        for name in files:
            path = root / name
            if not path.exists() and not path.is_symlink():
                path.symlink_to(Path("current") / name)
        return SnapshotHandle(final, version, manifest)

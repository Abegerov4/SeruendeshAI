"""Offline readiness gate: presence, provenance-bound live eval, submission files.

Presence is never execution evidence. This command does no network work and does
not certify privacy, UI behavior, source quality or prose faithfulness.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from eval.run_eval import endpoint_url, file_sha256, git_state, source_fingerprint, finite_number, valid_origin, _case_errors

COMPONENTS = {
    "backend": "backend/app/main.py", "rag": "rag/retriever.py",
    "frontend": "frontend/package.json", "dataset": "data/processed/pois.json",
}
DOCUMENTS = (
    "docs/test_scenarios.md", "docs/product_concept.md", "docs/rag_approach.md",
    "docs/ethics_privacy.md", "docs/demo_script.md",
)
NOT_VERIFIED = [
    "Privacy: real application logs, storage, consent and coordinate rounding require inspection.",
    "Frontend UX, map interactions, race conditions and live demo behavior require execution.",
    "POI source accuracy, pedestrian access and current opening hours require source/human review.",
    "Faithfulness, explanation quality and RU/KK/EN fluency require calibrated human/judge review.",
    "A local report is operator-provided evidence; this gate cannot authenticate its author or detect an undisclosed mock server.",
]


def _resolve(root: Path, value) -> Path:
    value = Path(value)
    return value if value.is_absolute() else root / value


def _evidence_errors(path: Path, root: Path, pois: Path, cases: Path) -> list[str]:
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError, RecursionError):
        return ["Evidence is missing or invalid JSON"]
    if not isinstance(report, dict):
        return ["Evidence must be a report object"]
    metadata, summary = report.get("metadata"), report.get("summary")
    if not isinstance(metadata, dict) or not isinstance(summary, dict):
        return ["Evidence lacks metadata/summary"]
    errors = []
    if metadata.get("execution_kind") != "live_http":
        errors.append("Fixture or unverified transport is not live execution evidence")
    model = metadata.get("model_label", {})
    if not isinstance(model, dict):
        errors.append("Invalid model provenance")
    elif any(word in str(model.get("value", "")).lower() for word in ("mock", "fixture", "synthetic")):
        errors.append("Mock/fixture model labels cannot establish readiness")
    try:
        endpoint_url(metadata.get("base_url", ""))
    except (ValueError, TypeError, AttributeError):
        errors.append("Missing valid API endpoint provenance")
    for name, file in (("dataset_sha256", pois), ("scenario_sha256", cases)):
        try:
            if not file.is_file() or metadata.get(name) != file_sha256(file):
                errors.append(f"{name} does not match the current file")
        except OSError:
            errors.append(f"{name} current file could not be read")
    try:
        if metadata.get("source_sha256") != source_fingerprint(root):
            errors.append("Source fingerprint is missing or stale, including uncommitted changes")
    except OSError:
        errors.append("Current source fingerprint could not be read")
    state = git_state(root)
    if not state["git_head"] or metadata.get("git_head") != state["git_head"]:
        errors.append("Git HEAD provenance is missing or stale")
    if type(metadata.get("git_dirty")) is not bool or metadata["git_dirty"] != state["git_dirty"]:
        errors.append("Git dirty-state provenance is missing or changed")
    planned = summary.get("planned")
    if type(planned) is not int or planned < 1:
        errors.append("Evidence has no planned scenarios")
    elif not (summary.get("attempted") == summary.get("passed") == planned
              and summary.get("failed") == 0 and summary.get("unexecuted") == 0
              and report.get("passed") is True and not report.get("input_errors")):
        errors.append("Not every planned attempt executed and passed")
    scenarios, repeats = None, None
    try:
        scenarios = json.loads(cases.read_text(encoding="utf-8"))
        repeats = metadata.get("repeat")
        if (type(repeats) is not int or repeats < 1 or not isinstance(scenarios, list)
                or planned != len(scenarios) * repeats):
            errors.append("Planned attempt count does not cover current scenarios/repeats")
    except (OSError, UnicodeError, json.JSONDecodeError, RecursionError):
        errors.append("Current scenarios cannot be verified")
    results = report.get("results")
    if (not isinstance(results, list) or len(results) != planned
            or any(not isinstance(item, dict) or item.get("executed") is not True
                   or item.get("passed") is not True for item in results)):
        errors.append("Per-attempt execution evidence is incomplete")
    if isinstance(scenarios, list) and type(repeats) is int and repeats > 0 and isinstance(results, list):
        valid_scenarios = all(isinstance(case, dict) and isinstance(case.get("id"), str) for case in scenarios)
        valid_results = all(isinstance(item, dict) and isinstance(item.get("case_id"), str)
                            and type(item.get("repeat")) is int for item in results)
        if valid_scenarios and valid_results:
            expected = {(case["id"], repetition) for case in scenarios for repetition in range(1, repeats + 1)}
            actual = {(item["case_id"], item["repeat"]) for item in results}
            if expected != actual or len(actual) != len(results):
                errors.append("Scenario/repeat identity coverage does not match the current corpus")
            by_id = {case["id"]: case for case in scenarios}
            for item in results:
                case = by_id.get(item["case_id"])
                if case is None or _case_errors(case):
                    errors.append("Per-attempt evidence references an invalid or unknown scenario")
                    continue
                attempt_errors = _attempt_evidence_errors(item, case)
                errors.extend(attempt_errors)
        else:
            errors.append("Scenario/repeat identity evidence is malformed")
    return errors


def _attempt_evidence_errors(item: dict, case: dict) -> list[str]:
    errors = []
    expect = case["expect"]
    if type(item.get("http_status")) is not int or item["http_status"] not in expect["status_codes"]:
        errors.append("Per-attempt HTTP status does not match scenario expectation")
    if item.get("errors") != []:
        errors.append("Per-attempt errors must be an empty list")
    latency = item.get("latency_ms")
    if not finite_number(latency) or latency < 0:
        errors.append("Per-attempt HTTP latency must be finite and nonnegative")
    checks = item.get("checks")
    expected_schema = "passed_error_detail" if expect["outcome"] == "validation_error" else "passed"
    if (not isinstance(checks, dict) or checks.get("schema_and_semantic") != expected_schema
            or checks.get("http_status") != "passed"):
        errors.append("Per-attempt applicable HTTP/schema/semantic checks were not completed")
        return errors
    if expect["outcome"] == "validation_error":
        geometry = "not_applicable"
    else:
        count = item.get("recommendation_count")
        minimum, maximum = expect.get("count_between", [1 if expect["outcome"] == "recommendations" else 0, 3])
        if type(count) is not int or not minimum <= count <= maximum:
            errors.append("Per-attempt recommendation count is missing or inconsistent")
        geometry = "not_applicable" if count == 0 else "passed" if valid_origin(case["request"]) else "not_evaluated"
    for key in ("origin_distance", "first_leg_geometry"):
        if checks.get(key) != geometry:
            errors.append(f"Per-attempt {key} applicability/completion is inconsistent")
        elif geometry == "not_evaluated":
            notes = item.get("check_notes")
            if not isinstance(notes, dict) or not isinstance(notes.get(key), str) or not notes[key].strip():
                errors.append(f"Per-attempt {key} omission has no explanation")
    return errors


def _fixture_poi(item: object) -> bool:
    if not isinstance(item, dict):
        return True
    if str(item.get("id", "")).lower().startswith(("test:", "synthetic:", "fixture:", "mock:")):
        return True
    if any(word in str(item.get("source", "")).lower() for word in ("test_fixture", "synthetic", "mock", "fixture")):
        return True
    try:
        host = urlsplit(str(item.get("source_url", ""))).hostname or ""
        return host in {"example.com", "example.org", "example.net", "localhost"} or host.endswith((".example", ".invalid", ".test", ".localhost"))
    except ValueError:
        return True


def check_readiness(root: Path, *, evidence: Path | None = None,
                    pois: Path | None = None, cases: Path | None = None,
                    submission_manifest: Path | None = None) -> dict:
    root = Path(root).resolve()
    pois = _resolve(root, pois or COMPONENTS["dataset"])
    cases = _resolve(root, cases or "eval/golden_set.json")
    checks = []
    def check(name, status, scope, detail):
        checks.append({"name": name, "status": status, "scope": scope, "detail": detail})
    for name, relative in COMPONENTS.items():
        path = pois if name == "dataset" else root / relative
        present = path.is_file()
        check(name, "present" if present else "missing", "presence_only",
              f"{relative}: {'present; behavior not verified by file presence' if present else 'absent'}")
    if pois.is_file():
        try:
            from eval.validators import validate_pois
            data = json.loads(pois.read_text(encoding="utf-8"))
            errors = validate_pois(data)
            if not isinstance(data, list) or len(data) < 300:
                errors.append("Real dataset target is at least 300 POIs")
            if isinstance(data, list) and any(_fixture_poi(item) for item in data):
                errors.append("Explicit synthetic/test/fixture IDs or reserved sources are not real dataset evidence")
            check("dataset_contract", "failed" if errors else "passed", "offline_contract",
                  f"{len(errors)} dataset violations" if errors else f"{len(data)} POIs; schema checked, sources not independently audited")
        except (OSError, UnicodeError, json.JSONDecodeError, RecursionError):
            check("dataset_contract", "failed", "offline_contract", "Dataset is not readable JSON")
    else:
        check("dataset_contract", "pending", "offline_contract", "Real POI dataset absent")
    if evidence is None:
        check("live_evaluation", "pending", "measured_execution", "No --evidence report supplied; offline fixture tests establish QA-tool correctness only")
    else:
        errors = _evidence_errors(_resolve(root, evidence), root, pois, cases)
        check("live_evaluation", "failed" if errors else "passed", "measured_execution",
              "; ".join(errors) if errors else "All current scenarios executed/passed with matching dataset/scenario/source/Git provenance; operator must verify real runtime configuration")
    missing_docs = [path for path in DOCUMENTS if not (root / path).is_file()]
    check("submission_documents", "pending" if missing_docs else "present", "presence_only",
          "Missing: " + ", ".join(missing_docs) if missing_docs else "Required preparation documents present; factual review still required")
    manifest_path = _resolve(root, submission_manifest or "docs/submission.json")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            raise ValueError
        slides = manifest.get("slides_path")
        demo = urlsplit(manifest.get("demo_url", ""))
        slides_ready = isinstance(slides, str) and slides.lower().endswith(".pdf") and _resolve(root, slides).is_file()
        demo_ready = (demo.scheme == "https" and demo.hostname in {"youtube.com", "www.youtube.com", "youtu.be"}
                      and not demo.username and not demo.password and bool(demo.path.strip("/")))
        detail = []
        if not slides_ready:
            detail.append("slides PDF path absent/invalid")
        if not demo_ready:
            detail.append("YouTube demo reference absent/invalid")
        check("submission_artifacts", "pending" if detail else "present", "references_only",
              "; ".join(detail) if detail else "Slides file and YouTube URL referenced; playback/content/access not verified offline")
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, TypeError, RecursionError):
        check("submission_artifacts", "pending", "references_only",
              "No valid docs/submission.json; supply slides_path and demo_url after the working demo exists")
    return {"report_version": 1, "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "ready": all(item["status"] in {"present", "passed"} for item in checks),
            "scope": "File, dataset-contract, recorded live-eval and submission-reference readiness; not a product/privacy certification",
            "checks": checks, "not_verified": NOT_VERIFIED}


def render_markdown(report: dict) -> str:
    lines = ["# Readiness", "", f"Gate: **{'READY' if report['ready'] else 'NOT READY'}**", "", report["scope"], "",
             "Presence checks confirm files only. Live execution requires explicit provenance-bound evidence.", "",
             "| Check | State | Scope | Evidence / missing work |", "| --- | --- | --- | --- |"]
    lines += [f"| {item['name']} | {item['status']} | {item['scope']} | {item['detail'].replace('|', '/')} |" for item in report["checks"]]
    lines += ["", "## Not verified", ""] + ["- " + detail for detail in report["not_verified"]]
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, default=Path("eval/readiness.md"), help="Markdown destination; JSON companion uses same stem")
    parser.add_argument("--evidence", type=Path, help="Explicit run_eval report.json from real application execution")
    parser.add_argument("--pois", type=Path, help="Dataset relative to root or absolute")
    parser.add_argument("--cases", type=Path, help="Scenarios relative to root or absolute")
    parser.add_argument("--submission-manifest", type=Path, help="JSON with slides_path and demo_url")
    args = parser.parse_args(argv)
    try:
        report = check_readiness(args.root, evidence=args.evidence, pois=args.pois, cases=args.cases,
                                 submission_manifest=args.submission_manifest)
        output = _resolve(args.root.resolve(), args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(render_markdown(report), encoding="utf-8")
        output.with_suffix(".json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except OSError:
        print("Could not write readiness report.", file=sys.stderr)
        return 2
    print("READY" if report["ready"] else "NOT READY: required components/evidence/artifacts are missing or failed")
    return 0 if report["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

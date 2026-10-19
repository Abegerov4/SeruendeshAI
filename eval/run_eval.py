"""Explicit HTTP evaluation of synthetic scenarios; never invokes an LLM judge.

Injected httpx clients are labeled fixture_transport and cannot establish product
readiness. CLI execution uses HTTP, but the operator must still verify that the
service and dataset are real rather than mock implementations.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[1]
NOT_EVALUATED = {
    "faithfulness": "Human or explicitly executed judge review required; prose is not proven by regex.",
    "language_quality": "Human RU/KK/EN review required.",
    "retrieval_at_5": "Final API recommendations expose at most 3 items, not the retrieval candidate set.",
    "privacy": "Application logs, retention and frontend coordinate handling require integration inspection.",
    "pedestrian_access": "Straight-line geometry is not proof of a usable walking route.",
    "prompt_injection": "Forbidden-token checks cover only supplied examples; security review remains required.",
}


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_state(root: Path) -> dict:
    """Read-only provenance; no Git configuration or index changes."""
    try:
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True,
                              text=True, timeout=5, check=True).stdout.strip()
        status = subprocess.run(["git", "--no-optional-locks", "status", "--porcelain"], cwd=root,
                                capture_output=True, text=True, timeout=5, check=True).stdout
        return {"git_head": head, "git_dirty": bool(status)}
    except (OSError, subprocess.SubprocessError):
        return {"git_head": None, "git_dirty": None}


def source_fingerprint(root: Path) -> str:
    """Bind evidence to current source bytes, including uncommitted changes.

    Only runtime/QA source and explicit configs are read; datasets/reports,
    dependency caches, build output and secret .env files are excluded.
    """
    root = Path(root)
    digest = hashlib.sha256()
    excluded = {".git", "node_modules", ".venv", "venv", "__pycache__", ".pytest_cache", ".cache",
                ".mypy_cache", ".ruff_cache", "dist", "build", "coverage", "runs", "review_packets", "chroma"}
    extensions = {".py", ".js", ".ts", ".tsx", ".jsx", ".mjs", ".cjs", ".json", ".html", ".css",
                  ".scss", ".vue", ".svelte", ".toml", ".yaml", ".yml", ".md", ".txt"}
    paths = []
    for name in ("backend", "ayat_backend", "rag", "frontend", "scripts", "runtime_support", "data/collect"):
        directory = root / name
        digest.update(f"root:{name}:{directory.is_dir()}\0".encode())
        if directory.is_dir():
            for current, directories, files in os.walk(directory):
                directories[:] = sorted(item for item in directories if item not in excluded and not item.endswith(".egg-info"))
                paths.extend(Path(current) / name for name in files
                             if Path(name).suffix in extensions and not name.startswith(".env")
                             and (Path(current) / name).relative_to(root).as_posix() not in {
                                 "ayat_backend/docs/EVAL_RESULTS.md", "ayat_backend/eval/results.json"})
    eval_sources = ("eval/run_eval.py", "eval/check_readiness.py", "eval/judge.py", "eval/validators.py", "eval/metrics.py")
    configs = ("pytest.ini", "requirements-qa.txt", "requirements-integration.txt", "pyproject.toml", "requirements.txt", "package.json",
               "docker-compose.yml", "backend/Dockerfile", "ayat_backend/Dockerfile", "ayat_backend/uv.lock", "ayat_backend/.python-version", ".dockerignore",
               ".github/workflows/backend.yml", ".github/workflows/ayat-backend.yml", ".github/workflows/data-refresh.yml",
               "data/run_pipeline.py", "data/snapshot.py", "data/eligibility.py", "data/quarantine.json", "data/quality_overrides.json",
               "data/processed/field_evidence.json", "data/processed/fact_reviews.json",
               "data/processed/current/bundle_manifest.json", "data/processed/current/quarantine.json",
               "data/processed/current/field_evidence.json", "data/processed/current/fact_reviews.json")
    for name in (*eval_sources, *configs):
        path = root / name
        digest.update(f"file:{name}:{path.is_file()}\0".encode())
        if path.is_file():
            paths.append(path)
    paths.extend((root / "eval/schemas").glob("*.json"))
    for path in sorted(set(paths)):
        digest.update(path.relative_to(root).as_posix().encode() + b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def safe_text(value: object, limit: int = 400) -> str:
    """Bound diagnostic text, removing common credential forms; never pass exceptions."""
    value = str(value)
    value = re.sub(r"(?i)(authorization\s*[:=]\s*|bearer\s+|(?:api[_-]?key|token|password)\s*[:=]\s*)[^\s,;]+",
                   "[REDACTED]", value)
    value = re.sub(r"\bsk-[A-Za-z0-9_-]+", "[REDACTED]", value)
    return value.replace("\n", " ").replace("\r", " ")[:limit]


def endpoint_url(value: str) -> str:
    """Refuse credentials/query parameters so endpoint metadata cannot leak keys."""
    parsed = urlsplit(value)
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname
            or parsed.username or parsed.password or parsed.query or parsed.fragment):
        raise ValueError("base URL must be http(s), with no credentials, query or fragment")
    return value.rstrip("/")


def finite_number(value: object) -> bool:
    return type(value) is int or (type(value) is float and math.isfinite(value))


def valid_origin(request: object) -> bool:
    location = request.get("location") if isinstance(request, dict) else None
    return (isinstance(location, dict) and finite_number(location.get("lat"))
            and finite_number(location.get("lon")) and -90 <= location["lat"] <= 90
            and -180 <= location["lon"] <= 180)


def geometry_evidence(request: dict, outcome: str, result: dict) -> None:
    """Expose exactly which origin-dependent checks had an independent oracle."""
    if outcome == "validation_error":
        state, reason = "not_applicable", "Validation errors contain no recommendation geometry."
    elif result["checks"]["schema_and_semantic"] != "passed":
        state, reason = "not_evaluated", "Response validation did not complete successfully."
    elif result.get("recommendation_count") == 0:
        state, reason = "not_applicable", "No recommendations or first travel leg."
    elif valid_origin(request):
        state, reason = "passed", "Checked against the independent numeric request origin; straight-line bounds only."
    else:
        state, reason = "not_evaluated", "No independent origin coordinates in the request; landmark resolution is not an oracle."
    for name in ("origin_distance", "first_leg_geometry"):
        result["checks"][name] = state
        result["check_notes"][name] = reason


def _case_errors(case: object) -> list[str]:
    if not isinstance(case, dict):
        return ["scenario must be an object"]
    errors = []
    for field in ("id", "scenario"):
        if not isinstance(case.get(field), str) or not case[field].strip():
            errors.append(f"{field} must be a nonempty string")
    if not isinstance(case.get("request"), dict):
        errors.append("request must be an object")
    expect = case.get("expect")
    if not isinstance(expect, dict):
        return errors + ["expect must be an object"]
    statuses = expect.get("status_codes")
    valid_statuses = (isinstance(statuses, list) and bool(statuses)
                      and all(type(status) is int and 100 <= status <= 599 for status in statuses))
    if not valid_statuses:
        errors.append("expect.status_codes must contain HTTP integer status codes")
    outcome = expect.get("outcome")
    valid_outcome = isinstance(outcome, str) and outcome in {"recommendations", "clarification", "rejection", "validation_error", "safe_response"}
    if not valid_outcome:
        errors.append("expect.outcome is unsupported")
    elif valid_statuses and any(status != (422 if outcome == "validation_error" else 200) for status in statuses):
        errors.append("unsupported HTTP status/outcome configuration: contract supports 200 success or 422 validation_error")
    request = case.get("request")
    if (isinstance(request, dict) and request.get("location") is not None
            and outcome != "validation_error" and not valid_origin(request)):
        errors.append("request.location must contain numeric finite lat/lon within geographic ranges")
    if "count_between" in expect:
        counts = expect["count_between"]
        if (not isinstance(counts, list) or len(counts) != 2
                or any(type(n) is not int for n in counts) or not 0 <= counts[0] <= counts[1] <= 3):
            errors.append("expect.count_between must be [minimum, maximum] within 0..3")
    if "max_distance_m" in expect:
        maximum = expect["max_distance_m"]
        if not finite_number(maximum) or maximum < 0:
            errors.append("expect.max_distance_m must be a finite nonnegative number")
    for key in ("relevant_poi_ids", "categories_any", "forbidden_output", "candidate_poi_ids"):
        if key in expect and (not isinstance(expect[key], list) or any(not isinstance(v, str) or not v.strip() for v in expect[key])):
            errors.append(f"expect.{key} must be a list of nonempty strings")
    if not isinstance(case.get("tags"), list) or any(not isinstance(tag, str) for tag in case.get("tags", [])):
        errors.append("tags must be a string list")
    return errors


def _metadata(base_url, pois_path, cases_path, repeat, model_label, root, fixture):
    hash_errors = []
    def hash_input(label, path):
        try:
            return file_sha256(path) if path.is_file() else None
        except OSError:
            hash_errors.append(f"{label} provenance hash could not be read")
            return None
    try:
        source_sha256 = source_fingerprint(root)
    except OSError:
        source_sha256 = None
        hash_errors.append("source provenance fingerprint could not be read")
    builtin_cases = cases_path.resolve() == (PROJECT_ROOT / "eval/golden_set.json").resolve()
    return {
        "runtime_id": "secondary",
        "provenance_errors": hash_errors, "source_sha256": source_sha256,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "dataset_sha256": hash_input("dataset", pois_path),
        "scenario_sha256": hash_input("scenarios", cases_path),
        **git_state(root), "base_url": base_url, "repeat": repeat,
        "model_label": {"value": safe_text(model_label) if model_label else None,
                        "source": "user_supplied" if model_label else "not_supplied"},
        "execution_kind": "fixture_transport" if fixture else "live_http",
        "corpus_scope": "built_in_synthetic" if builtin_cases else "operator_supplied_unverified",
        "scenario_policy": "Built-in scenarios are synthetic. Custom inputs must be independently checked for private data before use; opt-in review packets retain sanitized source prose.",
        "validation_scope": "HTTP status + response schema + applicable deterministic semantic checks; per-case origin geometry omissions and human/judge checks remain explicit.",
    }


def _review_packet(request: dict, response: dict, pois: list[dict]) -> dict:
    """Sanitize export only, after evaluating the original payload unchanged."""
    secret = re.compile(r"authorization|api.?key|token|secret|password|cookie", re.I)
    def clean(value):
        if isinstance(value, dict):
            return {key: clean(item) for key, item in value.items() if isinstance(key, str) and not secret.search(key)}
        if isinstance(value, list):
            return [clean(item) for item in value]
        if isinstance(value, str):
            return safe_text(value, limit=10000)
        if isinstance(value, float) and not math.isfinite(value):
            return None
        return value
    request_fields = {"query", "location", "time_budget_min", "mode", "profile", "lang", "now"}
    response_fields = {"used_context", "recommendations", "route", "notes", "disclaimer"}
    return clean({"request": {key: value for key, value in request.items() if key in request_fields},
                  "response": {key: value for key, value in response.items() if key in response_fields},
                  "pois": pois,
                  "review_scope": "Matched recommended POI sources only; no retrieval candidates. Sanitized export may omit secrets/long text; inspect against source before scoring."})


def run_evaluation(*, base_url: str, pois_path: Path, cases_path: Path,
                   repeat: int = 1, model_label: str | None = None,
                   client: httpx.Client | None = None, root: Path = PROJECT_ROOT,
                   review_packets: bool = False) -> dict:
    """Run each case repeat times. Any missing/failed case makes the report fail."""
    from eval.metrics import latency_percentiles, retrieval_metrics
    from eval.validators import validate_pois, validate_response

    base_url = endpoint_url(base_url)
    if type(repeat) is not int or repeat < 1:
        raise ValueError("repeat must be a positive integer")
    pois_path, cases_path = Path(pois_path), Path(cases_path)
    metadata = _metadata(base_url, pois_path, cases_path, repeat, model_label, Path(root), client is not None)
    input_errors, cases, pois = list(metadata["provenance_errors"]), [], []
    for label, path in (("scenarios", cases_path), ("dataset", pois_path)):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(value, list) or not value:
                input_errors.append(f"{label} must be a nonempty JSON list")
            elif label == "scenarios":
                cases = value
            else:
                pois = value
        except (OSError, UnicodeError, json.JSONDecodeError, RecursionError):
            input_errors.append(f"{label} could not be read as JSON")
    if pois:
        input_errors.extend("dataset: " + safe_text(error) for error in validate_pois(pois))
    known_ids = {poi["id"] for poi in pois if isinstance(poi, dict) and isinstance(poi.get("id"), str)}
    results, latencies, observed_ids, final_scores, packets = [], [], [], [], []
    owned_client = client is None and not input_errors
    if owned_client:
        client = httpx.Client(timeout=20, follow_redirects=False, trust_env=False)
    seen_ids = set()
    try:
        for case_index, case in enumerate(cases):
            case_errors = _case_errors(case)
            case_id = case.get("id", f"case-{case_index + 1}") if isinstance(case, dict) else f"case-{case_index + 1}"
            if isinstance(case_id, str) and case_id in seen_ids:
                case_errors.append("duplicate scenario id")
            seen_ids.add(str(case_id))
            for repetition in range(1, repeat + 1):
                result = {"case_id": safe_text(case_id), "repeat": repetition, "executed": False,
                          "passed": False, "http_status": None, "latency_ms": None,
                          "errors": list(case_errors), "checks": {"schema_and_semantic": "not_evaluated", "http_status": "not_evaluated",
                          "origin_distance": "not_evaluated", "first_leg_geometry": "not_evaluated"}, "check_notes": {}}
                geometry_evidence(case.get("request", {}) if isinstance(case, dict) else {},
                                  case.get("expect", {}).get("outcome") if isinstance(case, dict) and isinstance(case.get("expect"), dict) else "", result)
                results.append(result)
                if input_errors or case_errors:
                    continue
                result["executed"] = True
                response, payload = None, None
                start = time.perf_counter()
                try:
                    response = client.post(base_url + "/api/recommend", json=case["request"])
                except httpx.HTTPError:
                    result["errors"].append("HTTP transport failed (details omitted for credential safety)")
                except RecursionError:
                    result["errors"].append("Request JSON exceeds supported nesting depth; raw input omitted")
                finally:
                    # Stop the HTTP clock before parsing, schema checks or POI scans.
                    result["latency_ms"] = round((time.perf_counter() - start) * 1000, 3)
                    latencies.append(result["latency_ms"])
                if response is not None:
                    result["http_status"] = response.status_code
                    expected = response.status_code in case["expect"]["status_codes"]
                    result["checks"]["http_status"] = "passed" if expected else "failed"
                    if not expected:
                        result["errors"].append(f"unexpected HTTP status {response.status_code}")
                    else:
                        try:
                            payload = response.json()
                            errors = validate_response(payload, case["request"], pois, case["expect"])
                            result["errors"].extend(safe_text(error) for error in errors)
                            if case["expect"]["outcome"] == "validation_error":
                                result["checks"]["schema_and_semantic"] = "failed_error_detail" if errors else "passed_error_detail"
                            else:
                                result["checks"]["schema_and_semantic"] = "failed" if errors else "passed"
                        except (ValueError, UnicodeError, RecursionError):
                            payload = None
                            result["errors"].append("Response JSON is invalid or exceeds supported nesting depth; raw output omitted")
                if isinstance(payload, dict) and isinstance(payload.get("recommendations"), list):
                    recs = payload["recommendations"]
                    ids = [rec.get("poi_id") for rec in recs if isinstance(rec, dict) and isinstance(rec.get("poi_id"), str) and rec["poi_id"].strip()]
                    observed_ids.extend(ids)
                    result["recommendation_count"] = len(recs)
                    result["invalid_recommendation_id_count"] = len(recs) - len(ids)
                    result["recommended_ids"] = [safe_text(poi_id) for poi_id in ids]
                else:
                    ids = []
                geometry_evidence(case["request"], case["expect"]["outcome"], result)
                if review_packets and result["http_status"] == 200 and isinstance(payload, dict):
                    try:
                        packet = _review_packet(case["request"], payload, [poi for poi in pois if poi.get("id") in ids])
                        if len(json.dumps(packet, ensure_ascii=False).encode("utf-8")) <= 65536:
                            name = f"{case_index + 1:04d}-repeat-{repetition}.json"
                            packets.append((name, packet))
                            result["review_packet"] = "review_packets/" + name
                        else:
                            result["review_packet"] = "not_written_source_exceeds_64KiB"
                    except RecursionError:
                        result["review_packet"] = "not_written_source_nesting_too_deep"
                labels = case["expect"].get("relevant_poi_ids", [])
                if labels and case["expect"]["outcome"] == "recommendations":
                    score = retrieval_metrics(ids, labels, k=3)
                    final_scores.append(score)
                    result["final_recommendation_metrics"] = {"hit_at_3": score["hit_at_k"], "recall_at_3": score["recall_at_k"]}
                result["passed"] = not result["errors"]
    finally:
        if owned_client:
            client.close()
    attempted = sum(result["executed"] for result in results)
    passed = sum(result["passed"] for result in results)
    responded = sum(result["http_status"] is not None for result in results)
    planned = len(cases) * repeat
    hallucinated = sum(poi_id not in known_ids for poi_id in observed_ids)
    def mean_metric(key):
        values = [score[key] for score in final_scores if score[key] is not None]
        return sum(values) / len(values) if values else None
    summary = {
        "planned": planned, "attempted": attempted, "passed": passed,
        "failed": attempted - passed, "unexecuted": planned - attempted,
        "response_coverage": responded / planned if planned else None,
        "recommendation_response_coverage": sum(result.get("recommendation_count", 0) > 0 for result in results) / planned if planned else None,
        "invalid_recommendation_id_items": sum(result.get("invalid_recommendation_id_count", 0) for result in results),
        "hallucinated_ids": {"numerator": hallucinated, "denominator": len(observed_ids),
                             "rate": hallucinated / len(observed_ids) if observed_ids else None},
        "latency": {**latency_percentiles(latencies), "sample_count": len(latencies), "scope": "HTTP duration only, including failed attempts; excludes JSON parsing and QA validation"},
        "final_recommendation_metrics": {"hit_at_3": mean_metric("hit_at_k"), "recall_at_3": mean_metric("recall_at_k"),
                                         "annotated_attempts": len(final_scores), "scope": "final recommendations only; annotated scenarios"},
    }
    return {"report_version": 1, "metadata": metadata, "summary": summary,
            "passed": bool(planned and passed == planned and not input_errors),
            "input_errors": input_errors, "results": results, "not_evaluated": NOT_EVALUATED, "_review_packets": packets}


def render_markdown(report: dict) -> str:
    s, m = report["summary"], report["metadata"]
    ids = s["hallucinated_ids"]
    lines = ["# Evaluation results", "", f"Execution: `{m['execution_kind']}`. Corpus: `{m['corpus_scope']}`; no judge executed.", "",
             f"Overall: **{'PASS' if report['passed'] else 'FAIL'}**. Planned {s['planned']}; attempted {s['attempted']}; passed {s['passed']}; failed {s['failed']}; unexecuted {s['unexecuted']}.", "",
             "| Metric | Value |", "| --- | --- |",
             f"| HTTP response coverage | {s['response_coverage']} |",
             f"| Nonempty recommendation response coverage | {s['recommendation_response_coverage']} |",
             f"| Hallucinated IDs / observed IDs | {ids['numerator']} / {ids['denominator']} (rate: {ids['rate']}) |",
             f"| Latency p50 / p95, all attempts | {s['latency'].get('p50_ms')} / {s['latency'].get('p95_ms')} ms |",
             f"| Final Hit@3 / Recall@3, labeled attempts only | {s['final_recommendation_metrics']['hit_at_3']} / {s['final_recommendation_metrics']['recall_at_3']} |", "",
             "Null means no evidence, never a zero-error result. Empty answers remain visible in coverage and scenario failures.", "",
             "## Deterministic failures", ""]
    lines += ["- " + error.replace("|", "\\|") for error in report["input_errors"]]
    lines += [f"- {r['case_id']} (repeat {r['repeat']}): " + ("; ".join(r["errors"]) or "unexecuted due to invalid input")
              for r in report["results"] if not r["passed"]]
    if not report["input_errors"] and all(r["passed"] for r in report["results"]):
        lines.append("No deterministic failures.")
    lines += ["", "## Geometry check omissions by attempt", ""]
    omissions = [f"- {result['case_id']} (repeat {result['repeat']}): {name} NOT_EVALUATED — {result['check_notes'].get(name, 'No completed geometry evidence.')}"
                 for result in report["results"] for name in ("origin_distance", "first_leg_geometry")
                 if result["checks"].get(name) == "not_evaluated"]
    lines += omissions or ["No applicable origin-dependent geometry checks were omitted."]
    lines += ["", "## Not evaluated by deterministic checks", ""]
    lines += [f"- {key}: {detail}" for key, detail in report["not_evaluated"].items()]
    lines += ["", "## Provenance", "", "```json", json.dumps(m, ensure_ascii=False, indent=2), "```", ""]
    return "\n".join(lines)


def _positive_int(value):
    try:
        number = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be a positive integer") from error
    if number < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return number


def main(argv=None, *, client=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True, help="Explicit API origin; no credentials/query")
    parser.add_argument("--pois", required=True, type=Path, help="Dataset to validate against")
    parser.add_argument("--cases", type=Path, default=PROJECT_ROOT / "eval/golden_set.json")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--repeat", type=_positive_int, default=1)
    parser.add_argument("--review-packets", action="store_true", help="Opt in to sanitized source packet files for human/judge review; use synthetic inputs only")
    parser.add_argument("--model-label", help="Optional operator supplied label, not independently verified")
    args = parser.parse_args(argv)
    try:
        report = run_evaluation(base_url=args.base_url, pois_path=args.pois, cases_path=args.cases,
                                repeat=args.repeat, model_label=args.model_label, client=client, review_packets=args.review_packets)
        args.output_dir.mkdir(parents=True, exist_ok=True)
        packets = report.pop("_review_packets", [])
        if packets:
            (args.output_dir / "review_packets").mkdir(exist_ok=True)
            for name, packet in packets:
                (args.output_dir / "review_packets" / name).write_text(json.dumps(packet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (args.output_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (args.output_dir / "results.md").write_text(render_markdown(report), encoding="utf-8")
    except (OSError, ValueError):
        # Fixed diagnostics avoid accidental path/credential echoes from exceptions.
        print("Evaluation could not complete: invalid configuration or report/input I/O failure.", file=sys.stderr)
        return 2
    print(f"Evaluation {'PASS' if report['passed'] else 'FAIL'}: {report['summary']['passed']}/{report['summary']['planned']} attempts passed")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

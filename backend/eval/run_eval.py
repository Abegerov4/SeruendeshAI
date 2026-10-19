"""Evaluation harness: runs backend/eval/scenarios.yaml against the API and checks hard constraints.

    uv run python eval/run_eval.py
    uv run python eval/run_eval.py --no-llm
    uv run python eval/run_eval.py --judge
    uv run python eval/run_eval.py --base-url http://localhost:8000

Writes docs/EVAL_RESULTS.md, a provenance companion at the same stem .json,
and the historical eval/results.json array. Pass --results-out for isolated runs.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml
import httpx

ROOT = Path(__file__).resolve().parent.parent  # backend/
sys.path.insert(0, str(ROOT.parent))  # repository root first: team `eval` and `data` packages
sys.path.append(str(ROOT))  # app (backend/) after it, so backend/eval does not shadow the team package

CHECKS = ["C1 schema", "C2 1–3 items", "C3 grounded ids", "C4 time budget", "C5 categories", "C6 source labels",
          "C7 language", "C8 no invented hours", "C9 coords rounded", "C10 safety rules", "C11 not closed",
          "C12 latency<8s", "S scenario"]
ADULT = {"bar", "nightclub", "hookah"}
OUTDOOR_NIGHT = {"park", "garden", "playground"}
KK = set("әғқңөұүһі")


def run_checks(sc: dict, resp: dict, ms: int, known_ids: set[str] | None) -> dict[str, bool | None]:
    from app.schemas import RecommendResponse
    try:
        RecommendResponse.model_validate(resp)
    except Exception:
        return {"C1 schema": False, "C4 time budget": False}
    e = sc.get("expect", {})
    items = resp.get("recommendations", [])
    poi = [i for i in items if i["source"] == "poi_data"]
    used = resp.get("used_context", {})
    budget = used.get("time_budget_min", 10 ** 6)
    r: dict[str, bool | None] = {}
    try:
        RecommendResponse.model_validate(resp)
        r["C1 schema"] = True
    except Exception:
        r["C1 schema"] = False
    if e.get("empty"):
        r["C2 1–3 items"] = len(poi) == 0
    else:
        r["C2 1–3 items"] = (1 <= len(poi) <= 3) if e.get("min_items") else len(poi) <= 3
    r["C3 grounded ids"] = all(i["poi_id"] in known_ids for i in poi) if known_ids is not None else None
    route = resp.get("route")
    r["C4 time budget"] = budget_ok(resp, budget)
    requested_budget = sc.get("request", {}).get("time_budget_min")
    if requested_budget is not None:
        r["C4 time budget"] = (r["C4 time budget"] and type(requested_budget) is int
                               and budget <= requested_budget and budget_ok(resp, requested_budget))
    if e.get("budget_max") is not None:
        r["C4 time budget"] = r["C4 time budget"] and budget <= e["budget_max"]
    r["C5 categories"] = all(i["category_detail"] in e["categories"] for i in poi) if e.get("categories") else None
    r["C6 source labels"] = all(i["source"] in ("poi_data", "generated") and i["source_label"] for i in items) and \
        all(i["source_url"] is None and i["open_status"] == "unknown" for i in items if i["source"] == "generated")
    r["C7 language"] = resp.get("lang") == e.get("lang") if e.get("lang") else None
    texts = " ".join(f"{i['why']} {i['what_to_do']}" for i in items)
    r["C8 no invented hours"] = not re.search(r"\b([01]?\d|2[0-3]):[0-5]\d\b|сейчас открыт|open now|қазір ашық", texts, re.I)
    loc = used.get("location") or {}
    r["C9 coords rounded"] = all(len(str(loc.get(k, 0)).split(".")[-1]) <= 3 for k in ("lat", "lon"))
    safety = True
    if e.get("kids_safe"):
        safety &= not any(i["category_detail"] in ADULT for i in poi)
    if e.get("night_safe"):
        safety &= not any(i["category_detail"] in OUTDOOR_NIGHT and not any("освещ" in f for f in i["features"]) for i in poi)
    if e.get("indoor_only"):
        safety &= not any("outdoor" in i["badges"] for i in poi)
    if e.get("no_inaccessible"):
        safety &= not any(i["accessibility"] == "no" for i in poi)
    r["C10 safety rules"] = safety if any(e.get(k) for k in ("kids_safe", "night_safe", "indoor_only", "no_inaccessible")) else None
    r["C11 not closed"] = not any(i["open_status"] == "closed" for i in poi)
    r["C12 latency<8s"] = ms <= 8000
    s_ok = True
    if e.get("origin_source"):
        s_ok &= (loc or {}).get("source", used.get("location_source")) == e["origin_source"]
    if e.get("origin_label_contains"):
        s_ok &= e["origin_label_contains"].lower() in (used.get("location_label") or "").lower()
    if e.get("leave_by"):
        s_ok &= bool(poi) and all(i["leave_by"] for i in poi)
    for frag in e.get("notes_contains", []):
        s_ok &= any(frag.lower() in n.lower() for n in resp.get("notes", []))
    if e.get("kazakh_text") and resp.get("llm", {}).get("mode") == "llm":
        s_ok &= any(c in KK for c in texts.lower())
    if e.get("travel_mode"):
        s_ok &= used.get("mode") == e["travel_mode"]
    if e.get("no_leak"):
        s_ok &= not re.search(r"you are seruendesh|hard rules|system prompt|системн\w* промпт", json.dumps(resp, ensure_ascii=False), re.I)
    r["S scenario"] = s_ok
    return r


def budget_ok(resp: dict, budget: int) -> bool:
    """Independent arithmetic over the final serialized cards, never planner internals."""
    def number(value):
        return type(value) in (int, float) and math.isfinite(value) and value >= 0

    if not number(budget):
        return False
    items = [item for item in resp.get("recommendations", []) if item.get("source") == "poi_data"]
    for item in items:
        travel, visit = item.get("travel_min"), item.get("visit_suggested_min")
        limits = item.get("visit_min")
        if (not number(travel) or not number(visit) or not isinstance(limits, (list, tuple))
                or len(limits) != 2 or not all(number(v) for v in limits)
                or not limits[0] <= visit <= limits[1]):
            return False
    route = resp.get("route")
    if route is None:
        return all(number(item.get("return_min", 0)) and
                   item["travel_min"] + item["visit_suggested_min"] + item.get("return_min", 0) <= budget for item in items)
    order, legs = route.get("order", []), route.get("legs", [])
    by_id = {item["poi_id"]: item for item in items}
    if not order or len(set(order)) != len(order) or set(order) != set(by_id):
        return False
    leg_times = [leg.get("travel_min") for leg in legs]
    back = route.get("back_min", 0)
    total = route.get("total_min")
    if not all(number(v) for v in [*leg_times, back, total]):
        return False
    actual = sum(leg_times) + back + sum(by_id[key]["visit_suggested_min"] for key in order)
    return total == actual and total <= budget and route.get("fits_budget") is True


JUDGE_SYSTEM = """You grade a city-walk recommender for Astana. Given the user's request, the context the system
used and its recommendations (with the facts from its database), score:
- relevance (1-5): do the places fit the request, location, time budget and party?
- why_quality (1-5): are the explanations specific, short and convincing?
- actionability (1-5): is "what to do" concrete and useful?
- faithful (true/false): do the texts avoid claims that contradict or go beyond the given facts?
Be strict and brief."""


def judge(sc: dict, resp: dict):
    from pydantic import BaseModel, Field

    from app.config import get_settings
    from openai import OpenAI

    class Verdict(BaseModel):
        relevance: int = Field(ge=1, le=5)
        why_quality: int = Field(ge=1, le=5)
        actionability: int = Field(ge=1, le=5)
        faithful: bool
        comment: str

    s = get_settings()
    c = OpenAI(api_key=s.openai_api_key, timeout=30)
    items = [{k: i.get(k) for k in ("name", "category_label", "distance_m", "travel_min", "visit_min", "why", "what_to_do",
                                    "features", "badges", "accessibility", "source", "description")}
             | {"hours": i["opening"]["label"], "facts_note": "badges/category/description/features are the database facts"}
             for i in resp["recommendations"]]
    u = resp["used_context"]
    user = json.dumps({"request": sc["request"]["query"], "context": {k: u[k] for k in ("location", "local_time", "weather",
                       "time_budget_min", "mode", "party", "filters")}, "recommendations": items,
                       "route": (resp["route"] or {}).get("summary")}, ensure_ascii=False)
    r = c.responses.parse(model=s.llm_parse_model, input=[{"role": "system", "content": JUDGE_SYSTEM},
                          {"role": "user", "content": user}], text_format=Verdict, store=False,
                          reasoning={"effort": "low"})
    return r.output_parsed.model_dump() if r.output_parsed else None


def local_identity(root: Path) -> dict:
    """Read the same POI view as the API (our snapshot by default, the canonical one when opted in)."""
    if os.getenv("DATA_SNAPSHOT_MODE", "legacy") != "canonical":
        path = root / "data/processed/pois.jsonl"
        ids = {json.loads(line)["id"] for line in path.open(encoding="utf-8") if line.strip()}
        return {"known_ids": ids, "canonical_path": path, "snapshot_version": "legacy"}
    from data.snapshot import resolve_snapshot
    from app.team_data import load_team_snapshot

    selected = resolve_snapshot(root / "data/processed", legacy=os.getenv("DATA_SNAPSHOT_MODE", "") == "legacy")
    canonical = selected.path / "pois.json"
    quarantine = selected.path / "quarantine.json" if selected.version != "legacy" else root / "data/quarantine.json"
    pois, _, _ = load_team_snapshot(canonical, quarantine_path=quarantine if quarantine.exists() else None)
    return {"known_ids": {p["id"] for p in pois}, "canonical_path": canonical,
            "snapshot_version": selected.version}


def provenance_report(results: list[dict], metadata: dict, planned: int) -> dict:
    failed = sum(bool(row.get("error")) or row.get("passed") is not True for row in results)
    unexecuted = max(0, planned - len(results))
    return {"report_version": 1, "report_format": "ayat_evaluation", "response_schema": "ayat.RecommendResponse",
            "metadata": metadata, "input_errors": metadata.get("provenance_errors", []),
            "passed": bool(planned) and failed == 0 and unexecuted == 0 and not metadata.get("provenance_errors"),
            "summary": {"planned": planned, "attempted": len(results), "passed": len(results) - failed,
                        "failed": failed, "unexecuted": unexecuted}, "results": results}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url")
    ap.add_argument("--no-llm", action="store_true")
    ap.add_argument("--judge", action="store_true")
    ap.add_argument("--only")
    ap.add_argument("--out", default=str(ROOT.parent / "docs" / "EVAL_RESULTS.md"))
    ap.add_argument("--results-out", type=Path, help="Legacy results-array destination; use with custom --out to preserve historical results")
    ap.add_argument("--profile", choices=("template", "llm"), help="Requested readiness profile (defaults to template for --no-llm, otherwise llm)")
    a = ap.parse_args()
    if a.no_llm:
        os.environ["LLM_ENABLED"] = "false"
    scenarios = yaml.safe_load((ROOT / "eval" / "scenarios.yaml").read_text())
    if a.only:
        scenarios = [s for s in scenarios if s["id"] in a.only.split(",")]
    results = []
    from eval.run_eval import endpoint_url, file_sha256, git_state, source_fingerprint
    project = ROOT.parent
    metadata = {"runtime_id": "ayat", "profile": a.profile or ("template" if a.no_llm else "llm"),
                "timestamp_utc": datetime.now(timezone.utc).isoformat(), "scenario_sha256": file_sha256(ROOT / "eval/scenarios.yaml"),
                "source_sha256": source_fingerprint(project), **git_state(project), "provenance_errors": [],
                "known_ids_verified": False, "health": None}
    try:
        identity = local_identity(project)
        metadata.update(canonical_data_sha256=file_sha256(identity["canonical_path"]),
                        dataset_sha256=file_sha256(identity["canonical_path"]), snapshot_version=identity["snapshot_version"],
                        known_ids_verified=True)
        known = identity["known_ids"]
    except (OSError, ValueError, KeyError) as exc:
        known = None
        metadata["provenance_errors"].append("Local canonical identity unavailable: " + type(exc).__name__)
    if a.base_url:
        client = httpx.Client(base_url=endpoint_url(a.base_url), timeout=30)
        metadata.update(base_url=endpoint_url(a.base_url), execution_kind=(
            "live_http" if isinstance(client._transport, httpx.HTTPTransport) else "fixture_transport"))
        post = lambda body: client.post("/api/recommend", json=body)  # noqa: E731
        ctx = None
        health_client = client
    else:
        from fastapi.testclient import TestClient

        from app.main import RT, app
        ctx = TestClient(app)
        ctx.__enter__()
        known = set(RT["rt"].store.by_id)
        metadata.update(base_url=None, execution_kind="in_process")
        health_client = ctx
        post = lambda body: ctx.post("/api/recommend", json=body)  # noqa: E731
    try:
        try:
            health_response = health_client.get("/api/health")
            health_response.raise_for_status()
            from app.schemas import HealthResponse
            health = health_response.json()
            HealthResponse.model_validate(health)
            metadata["health"] = health  # retain missing identity fields; schema defaults are not evidence
            if (health.get("runtime_id") != "ayat" or health.get("readiness_profile") != metadata["profile"]
                    or health.get("ready") is not True or health.get("status") != "ok"
                    or health.get("snapshot_version") != metadata.get("snapshot_version")
                    or known is None or health.get("poi_count") != len(known)):
                metadata["provenance_errors"].append("Health runtime/profile/snapshot does not match local canonical identity")
            if metadata["profile"] == "llm" and (health.get("llm") != "ok" or not health.get("provider_verified_at")):
                metadata["provenance_errors"].append("Health does not report verified LLM readiness")
        except (httpx.HTTPError, ValueError) as exc:
            metadata["provenance_errors"].append("Health identity unavailable: " + type(exc).__name__)
        for sc in scenarios:
            t0 = time.perf_counter()
            try:
                r = post(sc["request"])
                resp = r.json()
            except (httpx.HTTPError, ValueError) as exc:
                results.append({"id": sc["id"], "title": sc["title"], "error": type(exc).__name__,
                                "checks": {"C1 schema": False}, "ms": int((time.perf_counter() - t0) * 1000),
                                "executed": True, "passed": False, "http_status": None})
                continue
            ms = int((time.perf_counter() - t0) * 1000)
            if r.status_code != 200:
                results.append({"id": sc["id"], "title": sc["title"], "error": {"http_status": r.status_code},
                                "checks": {"C1 schema": False}, "ms": ms, "executed": True, "passed": False,
                                "http_status": r.status_code})
                print(sc["id"], "HTTP", r.status_code)
                continue
            checks = run_checks(sc, resp, ms, known)
            if checks.get("C1 schema") is False:
                results.append({"id": sc["id"], "title": sc["title"], "ms": ms,
                                "error": "invalid_response_schema", "checks": checks, "executed": True,
                                "passed": False, "http_status": r.status_code})
                continue
            row = {"id": sc["id"], "title": sc["title"], "ms": ms, "mode": resp["llm"]["mode"], "model": resp["llm"]["model"],
                   "checks": checks, "items": [f"{i['name']} ({i['category_label']}, {i['travel_min']} мин)" if i["source"] == "poi_data"
                                               else f"✨ {i['name']}" for i in resp["recommendations"]],
                   "route": (resp["route"] or {}).get("summary"), "executed": True, "http_status": r.status_code,
                   "passed": not any(v is False for v in checks.values()), "response": resp}
            if a.judge and resp["recommendations"]:
                try:
                    row["judge"] = judge(sc, resp)
                except Exception as ex:
                    row["judge"] = {"error": type(ex).__name__}
                    row.update(error="judge_failed", passed=False)
            # an expected empty answer (no location, outside Astana) is decided before any model call
            expected_empty = (sc.get("expect") or {}).get("empty") and not resp.get("recommendations")
            if resp["llm"]["mode"] != metadata["profile"] and not expected_empty:
                row.update(error="response_profile_mismatch", passed=False)
            fails = [k for k, v in checks.items() if v is False]
            print(f"{sc['id']:24s} {ms:5d} ms  {resp['llm']['mode']:8s} {'OK' if not fails else 'FAIL ' + ', '.join(fails)}")
            results.append(row)
    finally:
        if ctx is not None:
            ctx.__exit__(None, None, None)
        else:
            client.close()
    if metadata["source_sha256"] != source_fingerprint(project):
        metadata["provenance_errors"].append("Source fingerprint changed during evaluation")
    metadata["generation_models"] = sorted({row["model"] for row in results if isinstance(row.get("model"), str)})
    array_path = a.results_out or ROOT / "eval/results.json"
    array_path.parent.mkdir(parents=True, exist_ok=True)
    array_path.write_text(json.dumps(results, ensure_ascii=False, indent=1))
    write_md(results, Path(a.out), a)
    report = provenance_report(results, metadata, len(scenarios))
    Path(a.out).with_suffix(".json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return 0 if report["passed"] else 1


def write_md(results: list[dict], out: Path, a) -> None:
    ok = lambda v: "✅" if v is True else "❌" if v is False else "—"  # noqa: E731
    n_checks = sum(1 for r in results for v in r["checks"].values() if v is not None)
    n_pass = sum(1 for r in results for v in r["checks"].values() if v is True)
    failed = sum(bool(r.get("error")) or any(v is False for v in r["checks"].values()) for r in results)
    lat = [r["ms"] for r in results if "ms" in r]
    lines = [
        "# Результаты автоматической оценки", "",
        f"Режим: {'шаблоны (без LLM)' if a.no_llm else 'LLM'} · сценариев: {len(results)} · "
        f"проверок пройдено: **{n_pass}/{n_checks}** · латентность p50 {statistics.median(lat) if lat else 0:.0f} мс, "
        f"max {max(lat) if lat else 0} мс", "",
        f"Сценариев: planned={len(results)}, executed={len(results)}, failed={failed}. HTTP/transport failures count as failures.", "",
        "Проверки: " + "; ".join(CHECKS) + ".", "",
        "| Сценарий | " + " | ".join(c.split(" ")[0] for c in CHECKS) + " | мс |",
        "|---|" + "---|" * (len(CHECKS) + 1),
    ]
    for r in results:
        lines.append(f"| {r['id']} | " + " | ".join(ok(r["checks"].get(c)) for c in CHECKS) + f" | {r['ms']} |")
    if any("judge" in r for r in results):
        js = [r["judge"] for r in results if isinstance(r.get("judge"), dict) and "relevance" in r["judge"]]
        if js:
            lines += ["", "## LLM-as-judge (1–5)", "",
                      f"Релевантность {statistics.mean(j['relevance'] for j in js):.2f} · качество «почему» "
                      f"{statistics.mean(j['why_quality'] for j in js):.2f} · конкретность {statistics.mean(j['actionability'] for j in js):.2f} · "
                      f"фактическая точность {sum(j['faithful'] for j in js)}/{len(js)}"]
    lines += ["", "## Выдача по сценариям", ""]
    for r in results:
        lines.append(f"- **{r['id']}** — {r['title']}: " + "; ".join(r.get("items", [])) +
                     (f"  \n  Маршрут: {r['route']}" if r.get("route") else ""))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("wrote", out)


if __name__ == "__main__":
    raise SystemExit(main())

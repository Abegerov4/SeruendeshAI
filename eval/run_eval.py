"""Evaluation harness: runs eval/scenarios.yaml against the API and checks hard constraints.

    cd backend && uv run python ../eval/run_eval.py                 # in-process, LLM on
    cd backend && uv run python ../eval/run_eval.py --no-llm        # template mode (no API key needed)
    cd backend && uv run python ../eval/run_eval.py --judge         # + LLM-as-judge scores (1–5)
    cd backend && uv run python ../eval/run_eval.py --base-url http://localhost:8000

Writes docs/EVAL_RESULTS.md and eval/results.json.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

CHECKS = ["C1 schema", "C2 1–3 items", "C3 grounded ids", "C4 time budget", "C5 categories", "C6 source labels",
          "C7 language", "C8 no invented hours", "C9 coords rounded", "C10 safety rules", "C11 not closed",
          "C12 latency<8s", "S scenario"]
ADULT = {"bar", "nightclub", "hookah"}
OUTDOOR_NIGHT = {"park", "garden", "playground"}
KK = set("әғқңөұүһі")


def run_checks(sc: dict, resp: dict, ms: int, known_ids: set[str] | None) -> dict[str, bool | None]:
    from app.schemas import RecommendResponse
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
    r["C4 time budget"] = all((i["travel_min"] or 0) <= budget for i in poi) and \
        (route is None or route["total_min"] <= budget + 5)
    if e.get("budget_max"):
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url")
    ap.add_argument("--no-llm", action="store_true")
    ap.add_argument("--judge", action="store_true")
    ap.add_argument("--only")
    ap.add_argument("--out", default=str(ROOT / "docs" / "EVAL_RESULTS.md"))
    a = ap.parse_args()
    if a.no_llm:
        os.environ["LLM_ENABLED"] = "false"
    scenarios = yaml.safe_load((ROOT / "eval" / "scenarios.yaml").read_text())
    if a.only:
        scenarios = [s for s in scenarios if s["id"] in a.only.split(",")]
    results = []
    if a.base_url:
        import httpx
        client, known = httpx.Client(base_url=a.base_url, timeout=30), None
        post = lambda body: client.post("/api/recommend", json=body)  # noqa: E731
        ctx = None
    else:
        from fastapi.testclient import TestClient

        from app.main import RT, app
        ctx = TestClient(app)
        ctx.__enter__()
        known = set(RT["rt"].store.by_id)
        post = lambda body: ctx.post("/api/recommend", json=body)  # noqa: E731
    try:
        for sc in scenarios:
            t0 = time.perf_counter()
            r = post(sc["request"])
            ms = int((time.perf_counter() - t0) * 1000)
            resp = r.json()
            if r.status_code != 200:
                results.append({"id": sc["id"], "title": sc["title"], "error": resp, "checks": {}, "ms": ms})
                print(sc["id"], "HTTP", r.status_code)
                continue
            checks = run_checks(sc, resp, ms, known)
            row = {"id": sc["id"], "title": sc["title"], "ms": ms, "mode": resp["llm"]["mode"], "model": resp["llm"]["model"],
                   "checks": checks, "items": [f"{i['name']} ({i['category_label']}, {i['travel_min']} мин)" if i["source"] == "poi_data"
                                               else f"✨ {i['name']}" for i in resp["recommendations"]],
                   "route": (resp["route"] or {}).get("summary")}
            if a.judge and resp["recommendations"]:
                try:
                    row["judge"] = judge(sc, resp)
                except Exception as ex:
                    row["judge"] = {"error": type(ex).__name__}
            fails = [k for k, v in checks.items() if v is False]
            print(f"{sc['id']:24s} {ms:5d} ms  {resp['llm']['mode']:8s} {'OK' if not fails else 'FAIL ' + ', '.join(fails)}")
            results.append(row)
    finally:
        if ctx is not None:
            ctx.__exit__(None, None, None)
    (ROOT / "eval" / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=1))
    write_md(results, Path(a.out), a)


def write_md(results: list[dict], out: Path, a) -> None:
    ok = lambda v: "✅" if v is True else "❌" if v is False else "—"  # noqa: E731
    n_checks = sum(1 for r in results for v in r["checks"].values() if v is not None)
    n_pass = sum(1 for r in results for v in r["checks"].values() if v is True)
    lat = [r["ms"] for r in results if "ms" in r]
    lines = [
        "# Результаты автоматической оценки", "",
        f"Режим: {'шаблоны (без LLM)' if a.no_llm else 'LLM'} · сценариев: {len(results)} · "
        f"проверок пройдено: **{n_pass}/{n_checks}** · латентность p50 {statistics.median(lat) if lat else 0:.0f} мс, "
        f"max {max(lat) if lat else 0} мс", "",
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
    main()

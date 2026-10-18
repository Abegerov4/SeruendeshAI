"""A/B-эксперимент: какая модель лучше в роли decision model (выбор мест + «почему»).

Гипотеза: свежая reasoning-модель (gpt-6.1-sol) пишет более обоснованные и релевантные объяснения,
но медленнее и дороже, чем быстрая gpt-5.4-mini. Вопрос — стоит ли прирост качества задержки и денег.

Метрики:
  - auto (кодом): valid_ids, count_ok (1–3), fits_budget (дорога + визит ≤ бюджет), no_false_open
  - LLM-as-a-judge (отдельная модель-судья): faithfulness 1–5, relevance 1–5
  - latency, cost_usd на запрос

Запуск из корня:  python -m backend.experiments.ab_decision [--configs gpt-6.1-sol,gpt-5.4-mini] [--judge gpt-5.5]
"""
import argparse
import json
import statistics
import time
from datetime import datetime
from pathlib import Path

from backend.app import llm, tracing
from backend.app import rag_adapter as rag
from backend.app.config import ASTANA_TZ
from backend.app.pipeline import recommend_with_stats
from backend.app.schemas import RecommendRequest

OUT_DIR = Path(__file__).parent / "results"
CASES = json.loads((Path(__file__).parent / "scenarios.json").read_text(encoding="utf-8"))

JUDGE_PROMPT = """Ты строгий оценщик городского помощника по прогулкам в Астане.
Тебе дают запрос пользователя, его ограничения и рекомендации системы вместе с данными о местах (POI), на которых система основывалась.

Оцени по шкале 1–5:
- faithfulness: насколько «why» и «what_to_do» опираются на данные POI (описание, теги, расстояние, часы). 5 — всё подтверждается данными, 1 — выдуманные факты (события, цены, «открыто сейчас» без данных).
- relevance: насколько выбранные места подходят под запрос, локацию, бюджет времени и ограничения (дети, ночь, тишина и т.п.). 5 — идеально, 1 — не по запросу.

Верни ТОЛЬКО JSON: {"faithfulness": int, "relevance": int, "comment": "одно предложение"}"""


def judge(case: dict, resp: dict, pois: dict, judge_model: str) -> dict:
    recs = [{
        "name": r["name"], "why": r["why"], "what_to_do": r["what_to_do"], "visit_min": r["visit_min"],
        "distance_m": r["distance_m"], "travel_min": r["travel_min"], "open_status": r["open_status"],
        "poi_data": {k: pois[r["poi_id"]].get(k) for k in ("category", "tags", "description", "opening_hours",
                                                            "kid_friendly", "wheelchair")},
    } for r in resp["recommendations"]]
    payload = {"query": case["query"], "used_context": resp["used_context"], "recommendations": recs}
    data = llm.chat_json(JUDGE_PROMPT, json.dumps(payload, ensure_ascii=False, default=str),
                         role="decision", name="ab-judge", model_override=judge_model) or {}
    return {"faithfulness": data.get("faithfulness"), "relevance": data.get("relevance"),
            "comment": data.get("comment", "")}


def auto_checks(resp: dict, pois: dict, budget: int) -> dict:
    recs = resp["recommendations"]
    return {
        "valid_ids": all(r["poi_id"] in pois for r in recs),
        "count_ok": 1 <= len(recs) <= 3,
        "fits_budget": all((r["travel_min"] or 0) + r["visit_min"][0] <= budget for r in recs),
        "no_false_open": all(not (pois[r["poi_id"]].get("opening_hours") is None and r["open_status"] == "open")
                             for r in recs),
    }


def run(configs: list[str], judge_model: str) -> list[dict]:
    pois = {p["id"]: p for p in rag.all_pois()}
    rows = []
    for model in configs:
        for case in CASES:
            req = RecommendRequest.model_validate(case["request"])
            # "auto" — боевой путь: decision-модель из .env с таймаутом и fallback на fast
            with llm.override_decision_model(None if model == "auto" else model):
                t0 = time.perf_counter()
                resp, stats = recommend_with_stats(req, use_cache=False)
                latency = time.perf_counter() - t0
            resp_d = resp.model_dump(mode="json")
            budget = resp_d["used_context"]["time_budget_min"]
            row = {
                "config": model, "case": case["id"], "latency_s": round(latency, 2),
                "cost_usd": stats.get("cost_usd"), "n_recs": len(resp_d["recommendations"]),
                "decision_used": [c["model"] for c in stats.get("calls", []) if c["name"] == "decide-recommendations"],
                **auto_checks(resp_d, pois, budget),
                "recs": [r["name"] for r in resp_d["recommendations"]],
            }
            row.update(judge(case, resp_d, pois, judge_model) if resp_d["recommendations"] else
                       {"faithfulness": None, "relevance": None, "comment": "нет рекомендаций"})
            rows.append(row)
            print(f"{model:14} {case['id']:22} {row['latency_s']:5.1f}s  F={row['faithfulness']} R={row['relevance']}  {row['recs']}")
    tracing.flush()
    return rows


def _mean(xs):
    xs = [x for x in xs if isinstance(x, (int, float))]
    return round(statistics.mean(xs), 2) if xs else None


def _cost_mean(rs: list[dict]) -> str:
    costs = [r["cost_usd"] for r in rs if isinstance(r["cost_usd"], (int, float))]
    return f"{statistics.mean(costs):.4f}" if costs else "—"


def report(rows: list[dict], configs: list[str], judge_model: str) -> str:
    lines = [
        "# A/B: decision model", "",
        f"Дата: {datetime.now(ASTANA_TZ):%Y-%m-%d %H:%M}, сценариев: {len(CASES)}, судья: `{judge_model}`, RAG: `{rag.backend_name()}`", "",
        "| Конфигурация | Faithfulness (1–5) | Relevance (1–5) | Auto-checks pass | Latency p50, s | Latency max, s | $ / запрос |",
        "|---|---|---|---|---|---|---|",
    ]
    for cfg in configs:
        rs = [r for r in rows if r["config"] == cfg]
        checks = [r[k] for r in rs for k in ("valid_ids", "count_ok", "fits_budget", "no_false_open")]
        lat = [r["latency_s"] for r in rs]
        lines.append(
            f"| `{cfg}` | {_mean([r['faithfulness'] for r in rs])} | {_mean([r['relevance'] for r in rs])} | "
            f"{sum(checks)}/{len(checks)} | {statistics.median(lat):.1f} | {max(lat):.1f} | {_cost_mean(rs)} |"
        )
    lines += ["", "## По сценариям", "", "| Сценарий | Конфигурация | F | R | Latency, s | Рекомендации | Комментарий судьи |", "|---|---|---|---|---|---|---|"]
    for r in sorted(rows, key=lambda x: (x["case"], x["config"])):
        lines.append(f"| {r['case']} | `{r['config']}` | {r['faithfulness']} | {r['relevance']} | {r['latency_s']} | "
                     f"{', '.join(r['recs'])} | {r['comment']} |")
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--configs", default="gpt-6.1-sol,gpt-5.4-mini")
    ap.add_argument("--judge", default="gpt-5.5")
    ap.add_argument("--tag", default="", help="метка прогона в имени файла, например prompt_v2")
    args = ap.parse_args()
    configs = [c.strip() for c in args.configs.split(",") if c.strip()]
    if not llm.is_enabled():
        raise SystemExit("Нужен OPENAI_API_KEY в .env")
    rows = run(configs, args.judge)
    OUT_DIR.mkdir(exist_ok=True)
    name = f"ab_decision_{datetime.now(ASTANA_TZ):%Y%m%d_%H%M}" + (f"_{args.tag}" if args.tag else "")
    (OUT_DIR / f"{name}.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    md = report(rows, configs, args.judge)
    (OUT_DIR / f"{name}.md").write_text(md, encoding="utf-8")
    print("\n" + md)


if __name__ == "__main__":
    main()

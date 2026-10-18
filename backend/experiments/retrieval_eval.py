"""Оценка ПОИСКА отдельно от генерации: Hit@K, MRR@10, NDCG@K (идея метрик — из MAVSPOI).

Сравниваем 3 конфигурации на одном golden set (retrieval_golden.json):
  bm25         — только лексический поиск rag/ по сырому запросу
  hybrid       — dense + BM25 → RRF по сырому запросу
  hybrid+intent — как в боевом пайплайне: LLM переписывает запрос и выбирает категории, затем гибрид
                  (если с категориями мало результатов — добор без категорий, как в pipeline._search)

Метрики:
  Hit@K   — есть ли хотя бы одно релевантное место в top-K
  MRR@10  — 1 / позиция первого релевантного (насколько высоко)
  NDCG@K  — учитывает позиции и градацию релевантности (2 — точное, 1 — приемлемое)
  P@5     — для nearby-запросов: доля подходящих мест в top-5

Запуск:  python -m backend.experiments.retrieval_eval [--configs bm25,hybrid,hybrid+intent]
"""
import argparse
import json
import math
import os
import statistics
from datetime import datetime
from pathlib import Path

os.environ.setdefault("MOCK_RAG", "0")

from backend.app import rag_adapter as rag  # noqa: E402
from backend.app.config import ASTANA_TZ  # noqa: E402

HERE = Path(__file__).parent
GOLDEN = json.loads((HERE / "retrieval_golden.json").read_text(encoding="utf-8"))["queries"]
K_LIST = (1, 3, 5, 10)


def relevance(q: dict, poi: dict) -> int:
    if q["type"] == "named":
        return q["relevant"].get(poi["id"], 0)
    if poi["category"] not in q["categories"]:
        return 0
    return int(rag.haversine_m(q["lat"], q["lon"], poi["lat"], poi["lon"]) <= q["radius_m"])


def ideal_gains(q: dict, pois: list[dict]) -> list[int]:
    if q["type"] == "named":
        return sorted(q["relevant"].values(), reverse=True)
    return [1] * sum(relevance(q, p) for p in pois)


def dcg(gains: list[int], k: int) -> float:
    return sum((2 ** g - 1) / math.log2(i + 2) for i, g in enumerate(gains[:k]))


def retrieve(q: dict, config: str) -> list[dict]:
    lat, lon = q.get("lat"), q.get("lon")
    radius = q.get("radius_m", 20_000)
    if config in ("bm25", "hybrid"):
        os.environ["RAG_SEARCH_MODE"] = config
        from rag.retriever import search
        return search(q["query"], lat, lon, radius, None, 10)
    # hybrid+intent: тот же путь, что в пайплайне
    os.environ["RAG_SEARCH_MODE"] = "hybrid"
    from backend.app.intent import parse_intent
    from backend.app.pipeline import _search
    from backend.app.schemas import RecommendRequest
    req = RecommendRequest(query=q["query"])
    intent, _ = parse_intent(req, q["query"])
    query = intent.search_query or q["query"]
    return _search(query, lat, lon, radius, intent.categories, raw_query=q["query"])[:10]


def evaluate(config: str, pois: list[dict]) -> list[dict]:
    rows = []
    for q in GOLDEN:
        hits = retrieve(q, config)
        gains = [relevance(q, h) for h in hits]
        ideal = ideal_gains(q, pois)
        first = next((i for i, g in enumerate(gains) if g > 0), None)
        row = {"config": config, "id": q["id"], "type": q["type"], "lang": q["lang"],
               "mrr": 0.0 if first is None else 1 / (first + 1),
               "top3": [h["name"] for h in hits[:3]]}
        for k in K_LIST:
            row[f"hit@{k}"] = int(any(g > 0 for g in gains[:k]))
            idcg = dcg(ideal, k)
            row[f"ndcg@{k}"] = dcg(gains, k) / idcg if idcg else 0.0
        if q["type"] == "nearby":
            row["p@5"] = sum(g > 0 for g in gains[:5]) / 5
        rows.append(row)
    return rows


def _m(rows, key):
    vals = [r[key] for r in rows if key in r]
    return f"{statistics.mean(vals):.2f}" if vals else "—"


def report(rows: list[dict], configs: list[str]) -> str:
    out = [
        "# Оценка поиска (retrieval)", "",
        f"Дата: {datetime.now(ASTANA_TZ):%Y-%m-%d %H:%M} · запросов: {len(GOLDEN)} "
        f"({sum(q['type'] == 'named' for q in GOLDEN)} по названию, {sum(q['type'] == 'nearby' for q in GOLDEN)} по смыслу рядом) · "
        f"POI в базе: {len(rag.all_pois())}", "",
        "| Конфигурация | Hit@1 | Hit@3 | Hit@5 | MRR@10 | NDCG@5 | NDCG@10 | P@5 (nearby) |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for c in configs:
        rs = [r for r in rows if r["config"] == c]
        out.append(f"| `{c}` | {_m(rs, 'hit@1')} | {_m(rs, 'hit@3')} | {_m(rs, 'hit@5')} | {_m(rs, 'mrr')} | "
                   f"{_m(rs, 'ndcg@5')} | {_m(rs, 'ndcg@10')} | {_m(rs, 'p@5')} |")
    out += ["", "### По типу и языку запроса (NDCG@5)", "", "| Срез | " + " | ".join(f"`{c}`" for c in configs) + " |",
            "|---|" + "---|" * len(configs)]
    for label, pred in [("по названию", lambda r: r["type"] == "named"), ("по смыслу рядом", lambda r: r["type"] == "nearby"),
                        ("ru", lambda r: r["lang"] == "ru"), ("en", lambda r: r["lang"] == "en"), ("kk", lambda r: r["lang"] == "kk")]:
        out.append(f"| {label} | " + " | ".join(_m([r for r in rows if r["config"] == c and pred(r)], "ndcg@5") for c in configs) + " |")
    out += ["", "### Промахи (Hit@5 = 0)", "", "| Запрос | Конфигурация | Top-3 |", "|---|---|---|"]
    q_by_id = {q["id"]: q for q in GOLDEN}
    for r in rows:
        if not r["hit@5"]:
            out.append(f"| {r['id']}: {q_by_id[r['id']]['query']} | `{r['config']}` | {', '.join(r['top3']) or '—'} |")
    return "\n".join(out) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--configs", default="bm25,hybrid,hybrid+intent")
    args = ap.parse_args()
    configs = [c.strip() for c in args.configs.split(",") if c.strip()]
    if rag.backend_name() != "real":
        raise SystemExit("Нужен пакет rag/ и MOCK_RAG=0")
    pois = rag.all_pois()
    rows = [r for c in configs for r in evaluate(c, pois)]
    md = report(rows, configs)
    out_dir = HERE / "results"
    out_dir.mkdir(exist_ok=True)
    name = f"retrieval_{datetime.now(ASTANA_TZ):%Y%m%d_%H%M}"
    (out_dir / f"{name}.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / f"{name}.md").write_text(md, encoding="utf-8")
    print(md)


if __name__ == "__main__":
    main()

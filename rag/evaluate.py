"""Evaluate labelled retrieval cases with the real, offline BM25 search path.

Accepts QA arrays (nested ``request``/``expect``), legacy QA arrays, or an
experimental ``{"queries": [...]}`` document. Missing relevance labels are
NOT_EVALUATED, never misses or successful empty-denominator evaluations.
"""
import argparse
import hashlib
import importlib
import json
import math
import os
import sys
from collections import defaultdict
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(__file__).resolve().parents[1]
TOP_K = 5
DEFAULT_RADIUS_M = 2500


def _json_bytes(path, description, provenance):
    raw = path.read_bytes()
    provenance.update(path=str(path.resolve()), sha256=hashlib.sha256(raw).hexdigest())
    try:
        return json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError(f"Invalid {description} JSON: {exc}") from exc


def _source_provenance():
    files = {}
    for name in ("rag/evaluate.py", "rag/retriever.py", "rag/text.py", "rag/geo.py"):
        files[name] = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
    digest = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
    return files, digest


def _id_index(pois):
    if not isinstance(pois, list):
        raise ValueError("Dataset must be an array of POIs")
    index = defaultdict(set)
    primary = set()
    for poi in pois:
        if not isinstance(poi, dict) or not isinstance(poi.get("id"), str) or not poi["id"].strip():
            raise ValueError("Dataset POIs must have nonempty string IDs")
        key = poi["id"]
        if key in primary:
            raise ValueError(f"Duplicate dataset primary ID: {key}")
        primary.add(key)
        index[key].add(key)
        records = poi.get("source_records", [])
        if not isinstance(records, list):
            raise ValueError(f"Invalid source_records for {key}")
        for record in records:
            if not isinstance(record, dict) or not isinstance(record.get("id"), str) or not record["id"].strip():
                raise ValueError(f"Invalid source_records ID for {key}")
            index[record["id"]].add(key)
    return index


def _canonical(key, index):
    if not isinstance(key, str) or not key.strip():
        raise ValueError("Relevance labels must be nonempty string POI IDs")
    matches = index.get(key, set())
    if not matches:
        raise ValueError(f"Unknown relevance label POI ID: {key}")
    if len(matches) != 1:
        raise ValueError(f"Ambiguous relevance label POI ID: {key} maps to {sorted(matches)}")
    return next(iter(matches))


def _labels(row, index):
    grades, mapping = {}, {}
    if "relevant" in row:
        supplied = row["relevant"]
        if not isinstance(supplied, dict):
            raise ValueError("relevant must be an object of POI IDs and nonnegative grades")
        for key, grade in supplied.items():
            if isinstance(grade, bool) or not isinstance(grade, (int, float)) or not math.isfinite(grade) or grade < 0:
                raise ValueError(f"Invalid relevance grade for {key}: {grade}")
            canonical = _canonical(key, index)
            mapping[key] = canonical
            if grade > 0:
                grades[canonical] = max(grade, grades.get(canonical, 0))
        scope = "provided_graded_poi_ids"
    else:
        expect = row.get("expect", {})
        if not isinstance(expect, dict):
            raise ValueError("expect must be an object")
        for name in ("relevant_poi_ids", "must_include_any"):
            supplied = expect.get(name, [])
            if not isinstance(supplied, list):
                raise ValueError(f"expect.{name} must be an array of POI IDs")
            for key in supplied:
                canonical = _canonical(key, index)
                mapping[key] = canonical
                grades[canonical] = 1
        scope = "provided_poi_ids"
    return grades, mapping, scope


def _request(row):
    request = row.get("request", row)
    if not isinstance(request, dict):
        raise ValueError("request must be an object for labelled retrieval cases")
    query = request.get("query")
    if not isinstance(query, str) or not query.strip():
        raise ValueError("Labelled retrieval cases require a nonempty string query")
    location = request.get("location")
    if location is not None:
        if not isinstance(location, dict) or "lat" not in location or "lon" not in location:
            raise ValueError("location must contain both lat and lon")
        lat, lon = location["lat"], location["lon"]
        if lat is None or lon is None:
            raise ValueError("Explicit location coordinates must be numbers, not null")
    else:
        lat, lon = request.get("lat"), request.get("lon")
    if (lat is None) != (lon is None):
        raise ValueError("Provide both explicit latitude and longitude, or neither")
    if lat is not None:
        for value, limit in ((lat, 90), (lon, 180)):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or abs(value) > limit:
                raise ValueError("Invalid explicit coordinates")
    radius = request.get("radius_m", row.get("radius_m", DEFAULT_RADIUS_M))
    if isinstance(radius, bool) or not isinstance(radius, (int, float)) or not math.isfinite(radius) or radius < 0:
        raise ValueError("radius_m must be a finite nonnegative number")
    categories = request.get("categories", row.get("categories"))
    if categories is not None and (not isinstance(categories, list) or
                                   any(not isinstance(c, str) or not c.strip() for c in categories)):
        raise ValueError("categories must be an array of nonempty strings, or null")
    return dict(query=query, lat=lat, lon=lon, radius_m=radius, categories=categories, top_k=TOP_K)


def _case(row, number, pois, index, retriever, seen):
    result = {"id": f"row:{number}", "type": "unknown", "lang": "unknown",
              "status": "ERROR", "top5_ids": [], "retrieved": [], "expected_ids": [],
              "label_grades": {}, "label_id_mapping": {}, "label_scope": None,
              "matched_ids": [], "hit_at_5": None, "recall_at_5": None}
    try:
        if not isinstance(row, dict):
            raise ValueError("Golden case must be an object")
        key = row.get("id")
        if not isinstance(key, str) or not key.strip():
            raise ValueError("Golden case requires a nonempty string id")
        result["id"] = key
        if key in seen:
            raise ValueError(f"Duplicate golden case ID: {key}")
        seen.add(key)
        request = row.get("request")
        result.update(type=row.get("type", "qa" if "request" in row else "legacy"),
                      lang=(request.get("lang", row.get("lang", "unknown"))
                            if isinstance(request, dict) else row.get("lang", "unknown")),
                      query=(request.get("query") if isinstance(request, dict) else row.get("query")))
        if not isinstance(result["type"], str) or not isinstance(result["lang"], str):
            result.update(type="unknown", lang="unknown")
            raise ValueError("Case type and lang must be strings")
        if row.get("type") == "nearby":
            result["label_scope"] = "dataset_category_and_radius_structural"
            if "relevant" in row:
                grades, mapping, _ = _labels(row, index)
                result.update(expected_ids=sorted(grades), label_grades=grades, label_id_mapping=mapping,
                              label_source="frozen_explicit_ids")
            arguments = _request(row)
            result["retrieval_request"] = arguments
            if arguments["lat"] is None:
                result.update(status="NOT_EVALUATED", reason="Nearby labels require an explicit coordinate point")
                return result
            if arguments["categories"] is None:
                raise ValueError("Nearby labels require explicit categories")
            if "relevant" not in row:
                from rag.geo import haversine_m
                grades = {poi["id"]: 1 for poi in pois
                          if poi["category"] in arguments["categories"] and
                          haversine_m(arguments["lat"], arguments["lon"], poi["lat"], poi["lon"]) <= arguments["radius_m"]}
                mapping = {key: key for key in grades}
                result["label_source"] = "derived_from_current_dataset"
        else:
            grades, mapping, result["label_scope"] = _labels(row, index)
            result["label_source"] = "explicit_ids"
            arguments = None
        result.update(expected_ids=sorted(grades), label_grades=grades, label_id_mapping=mapping)
        if not grades:
            result.update(status="NOT_EVALUATED", reason="No positive relevance labels; no metric denominator")
            return result
        arguments = arguments or _request(row)
        result["retrieval_request"] = arguments
        try:
            retrieved = retriever.search(**arguments)
            if not isinstance(retrieved, list) or len(retrieved) > TOP_K:
                raise ValueError("search must return a list with at most five POIs")
            ids = []
            primary_ids = {p["id"] for p in pois}
            for poi in retrieved:
                if not isinstance(poi, dict) or poi.get("id") not in primary_ids:
                    raise ValueError("search returned a missing or unknown primary POI ID")
                ids.append(poi["id"])
            if len(ids) != len(set(ids)):
                raise ValueError("search returned duplicate primary POI IDs")
        except Exception as exc:
            raise ValueError(f"Retrieval failed ({type(exc).__name__}): {exc}") from exc
        matched = sorted(set(ids) & grades.keys())
        result.update(status="HIT" if matched else "MISS", top5_ids=ids, retrieved=retrieved,
                      matched_ids=matched, hit_at_5=bool(matched), recall_at_5=len(matched) / len(grades))
    except (ValueError, KeyError, TypeError) as exc:
        result["error"] = str(exc)
    return result


def _metrics(cases):
    evaluated = [row for row in cases if row["status"] in ("HIT", "MISS")]
    relevant = sum(len(row["expected_ids"]) for row in evaluated)
    matched = sum(len(row["matched_ids"]) for row in evaluated)
    hits = sum(row["hit_at_5"] for row in evaluated)
    return {"total_cases": len(cases), "evaluated_cases": len(evaluated),
            "not_evaluated_cases": sum(row["status"] == "NOT_EVALUATED" for row in cases),
            "error_cases": sum(row["status"] == "ERROR" for row in cases),
            "hit_cases": hits, "miss_cases": len(evaluated) - hits,
            "relevant_ids": relevant, "matched_relevant_ids": matched,
            "hit_at_5": hits / len(evaluated) if evaluated else None,
            "macro_recall_at_5": sum(row["recall_at_5"] for row in evaluated) / len(evaluated) if evaluated else None,
            "micro_recall_at_5": matched / relevant if relevant else None}


def _write(report, output_dir):
    if output_dir is None:
        return
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    (output / "cases.jsonl").write_text("".join(json.dumps(case, ensure_ascii=False) + "\n"
                                                 for case in report["cases"]), encoding="utf-8")
    summary = {key: value for key, value in report.items() if key != "cases"}
    for name, value in (("summary.json", summary), ("report.json", report)):
        (output / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def evaluate(golden_path, *, output_dir=None, mode="bm25"):
    """Return a JSON-compatible report; ``exit_code`` is nonzero on invalid/empty evaluation.

    Uses the canonical ``rag.retriever`` dataset and direct search function, with
    no intent model, geocoding, dense embeddings, generation, or tracing. The
    temporary process environment setting is restored, even after an error;
    callers should serialize concurrent evaluations that share that environment.
    """
    report = {"cases": [], "errors": [], "provenance": {
        "dataset": {}, "golden": {}, "config": {
            "mode": mode, "top_k": TOP_K, "default_radius_m": DEFAULT_RADIUS_M,
            "search_path": "rag.retriever.search", "location_scope": "explicit_coordinates_only",
            "missing_location_scope": "citywide", "categories_scope": "explicit_request_categories_only",
            "evaluation_scope": "retrieval_only_no_intent_generation_geocoding_or_cloud",
            "label_scope": "provided_ID_labels_or_dataset_geo_category_structure_not_human_semantic_judgement",
            "metric_denominator": "successfully_retrieved_cases_with_positive_labels_only",
            "hit_at_5_definition": "fraction_of_evaluated_cases_with_any_expected_ID_in_top5",
            "macro_recall_at_5_definition": "mean_per_case_fraction_of_relevant_IDs_retrieved",
            "micro_recall_at_5_definition": "sum_matched_relevant_IDs_divided_by_sum_relevant_IDs",
        }}}
    try:
        if mode != "bm25":
            raise ValueError("Only explicit offline mode bm25 is supported")
        files, digest = _source_provenance()
        report["provenance"].update(source_files=files, code_sha256=digest)
        document = _json_bytes(Path(golden_path), "golden", report["provenance"]["golden"])
        rows = document.get("queries") if isinstance(document, dict) else document
        if not isinstance(rows, list):
            raise ValueError("Golden must be an array or an object with a queries array")
        report["provenance"]["golden"]["count"] = len(rows)
        try:
            retriever = importlib.import_module("rag.retriever")
            if not callable(getattr(retriever, "search", None)):
                raise ImportError("rag.retriever.search is missing")
        except Exception as exc:
            raise ValueError(f"Retrieval implementation unavailable: {exc}") from exc
        path = retriever.ROOT / "data/processed/pois.json"
        pois = _json_bytes(path, "dataset", report["provenance"]["dataset"])
        index = _id_index(pois)
        report["provenance"]["dataset"]["count"] = len(pois)
        previous_mode = os.environ.get("RAG_SEARCH_MODE")
        os.environ["RAG_SEARCH_MODE"] = mode
        try:
            seen = set()
            for number, row in enumerate(rows, 1):
                report["cases"].append(_case(row, number, pois, index, retriever, seen))
        finally:
            if previous_mode is None:
                os.environ.pop("RAG_SEARCH_MODE", None)
            else:
                os.environ["RAG_SEARCH_MODE"] = previous_mode
    except (OSError, ValueError, TypeError) as exc:
        report["errors"].append(str(exc))
    summary = _metrics(report["cases"])
    for field in ("type", "lang"):
        summary[f"by_{field}"] = {value: _metrics([row for row in report["cases"] if row[field] == value])
                                  for value in sorted({row[field] for row in report["cases"]})}
    report["summary"] = summary
    report["exit_code"] = int(bool(report["errors"] or summary["error_cases"] or not summary["evaluated_cases"]))
    _write(report, output_dir)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("golden", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--mode", choices=("bm25",), default="bm25")
    args = parser.parse_args(argv)
    report = evaluate(args.golden, output_dir=args.output_dir, mode=args.mode)
    for case in report["cases"]:
        if case["status"] == "ERROR":
            print(json.dumps({key: case[key] for key in ("id", "status", "error")}, ensure_ascii=False))
    print(json.dumps({key: value for key, value in report.items() if key != "cases"}, ensure_ascii=False))
    return report["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())

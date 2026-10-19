"""Retrieval evaluation contracts, using hand-labelled, real BM25 fixtures."""
import hashlib
import json
import os
from pathlib import Path

import pytest

from rag import evaluate as evaluator
from rag import retriever


@pytest.fixture
def dataset(tmp_path, monkeypatch):
    # These documents have independent distinctive words and known coordinates.
    rows = [
        {"id": "p:a", "name": "alpha", "category": "cafe", "lat": 0, "lon": 0,
         "tags": [], "source_records": [{"id": "old:a"}], "wheelchair": None,
         "opening_hours": None, "kid_friendly": None, "description_kind": "structured_template"},
        {"id": "p:b", "name": "beta", "category": "cafe", "lat": 0, "lon": 0.001,
         "tags": [], "source_records": [{"id": "old:b"}], "wheelchair": "yes",
         "opening_hours": "24/7", "kid_friendly": None},
        {"id": "p:c", "name": "gamma", "category": "park", "lat": 0, "lon": 1,
         "tags": [], "source_records": []},
    ]
    path = tmp_path / "data/processed/pois.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(rows), encoding="utf-8")
    monkeypatch.setattr(retriever, "ROOT", tmp_path)
    monkeypatch.setenv("RAG_SEARCH_MODE", "hybrid")
    return path


def golden(tmp_path, rows):
    path = tmp_path / "golden.json"
    path.write_text(json.dumps(rows), encoding="utf-8")
    return path


def run(golden_path, **kwargs):
    assert callable(getattr(evaluator, "evaluate", None)), "Reusable evaluate API is missing"
    return evaluator.evaluate(golden_path, **kwargs)


def test_qa_nested_requests_have_distinct_hit_macro_and_micro_denominators(dataset, tmp_path):
    # Wrongly calling any-hit recall, or counting unlabelled rows, breaks these literals.
    path = golden(tmp_path, [
        {"id": "partial", "request": {"query": "alpha", "lang": "en"},
         "expect": {"relevant_poi_ids": ["p:a", "p:b"]}},
        {"id": "complete", "request": {"query": "gamma", "lang": "en"},
         "expect": {"must_include_any": ["p:c"]}},
        {"id": "unlabelled", "request": {"query": "beta"},
         "expect": {"relevant_poi_ids": [], "candidate_poi_ids": ["p:b"]}},
    ])
    report = run(path)
    summary = report["summary"]
    assert summary["total_cases"] == 3
    assert summary["evaluated_cases"] == 2
    assert summary["not_evaluated_cases"] == 1
    assert summary["hit_cases"] == 2
    assert summary["hit_at_5"] == 1.0
    assert summary["macro_recall_at_5"] == 0.75
    assert summary["micro_recall_at_5"] == pytest.approx(2 / 3)
    assert report["cases"][2]["status"] == "NOT_EVALUATED"
    assert report["cases"][2]["hit_at_5"] is None
    assert summary["by_lang"]["en"]["evaluated_cases"] == 2
    assert report["exit_code"] == 0


def test_wrong_retrieved_id_is_a_miss_not_an_error(dataset, tmp_path):
    report = run(golden(tmp_path, [{"id": "wrong", "query": "alpha",
                                   "expect": {"must_include_any": ["p:b"]}}]))
    assert report["cases"][0]["top5_ids"] == ["p:a"]
    assert report["cases"][0]["status"] == "MISS"
    assert report["summary"]["hit_at_5"] == 0
    assert report["summary"]["macro_recall_at_5"] == 0
    assert report["exit_code"] == 0


def test_experimental_labels_canonicalize_stale_ids_and_collapse_duplicates(dataset, tmp_path):
    report = run(golden(tmp_path, {"queries": [
        {"id": "named", "type": "named", "lang": "en", "query": "alpha",
         "relevant": {"old:a": 1, "p:a": 2, "old:b": 1}},
    ]}))
    row = report["cases"][0]
    assert row["expected_ids"] == ["p:a", "p:b"]
    assert row["label_grades"] == {"p:a": 2, "p:b": 1}
    assert row["label_id_mapping"]["old:a"] == "p:a"
    assert row["recall_at_5"] == 0.5
    assert report["summary"]["relevant_ids"] == 2
    assert report["summary"]["by_type"]["named"]["hit_at_5"] == 1


def test_duplicate_qa_labels_are_one_relevant_place(dataset, tmp_path):
    report = run(golden(tmp_path, [{"id": "duplicates", "query": "alpha",
                                   "expect": {"relevant_poi_ids": ["p:a", "old:a", "p:a"]}}]))
    assert report["cases"][0]["expected_ids"] == ["p:a"]
    assert report["summary"]["micro_recall_at_5"] == 1


def test_nearby_labels_use_category_and_radius_not_query_words(dataset, tmp_path):
    report = run(golden(tmp_path, {"queries": [
        {"id": "geo", "type": "nearby", "query": "alpha", "lang": "kk",
         "lat": 0, "lon": 0, "radius_m": 120, "categories": ["cafe"]},
    ]}))
    row = report["cases"][0]
    assert row["expected_ids"] == ["p:a", "p:b"]
    assert row["top5_ids"] == ["p:a"]
    assert row["recall_at_5"] == 0.5
    assert row["label_scope"] == "dataset_category_and_radius_structural"
    assert report["summary"]["by_lang"]["kk"]["hit_at_5"] == 1


def test_nearby_missing_explicit_point_is_not_evaluated(dataset, tmp_path):
    report = run(golden(tmp_path, {"queries": [
        {"id": "no-point", "type": "nearby", "query": "Байтерек", "categories": ["cafe"]},
    ]}))
    assert report["cases"][0]["status"] == "NOT_EVALUATED"
    assert "explicit" in report["cases"][0]["reason"]
    assert report["summary"]["hit_at_5"] is None
    assert report["exit_code"] != 0


def test_frozen_nearby_labels_do_not_change_with_live_category_membership(dataset, tmp_path):
    report = run(golden(tmp_path, {"queries": [
        {"id": "frozen", "type": "nearby", "query": "alpha", "lat": 0, "lon": 0,
         "categories": ["cafe"], "radius_m": 120, "relevant": {"p:a": 1}},
    ]}))
    # p:b is inside the radius too, but was not labelled in this frozen corpus.
    assert report["cases"][0]["expected_ids"] == ["p:a"]
    assert report["cases"][0]["label_source"] == "frozen_explicit_ids"
    assert report["cases"][0]["label_scope"] == "dataset_category_and_radius_structural"
    assert report["summary"]["micro_recall_at_5"] == 1


def test_fact_cases_use_explicit_ids_without_promoting_unknown_facts(dataset, tmp_path):
    report = run(golden(tmp_path, {"queries": [
        {"id": "fact", "type": "fact", "query": "alpha", "relevant": {"p:a": 2}},
    ]}))
    assert report["cases"][0]["status"] == "HIT"
    assert report["cases"][0]["retrieved"][0]["wheelchair"] is None
    assert report["summary"]["by_type"]["fact"]["evaluated_cases"] == 1


def test_missing_nearby_point_does_not_hide_unknown_frozen_label(dataset, tmp_path):
    report = run(golden(tmp_path, {"queries": [
        {"id": "bad-frozen", "type": "nearby", "query": "alpha",
         "categories": ["cafe"], "relevant": {"missing:poi": 1}},
    ]}))
    assert report["cases"][0]["status"] == "ERROR"
    assert "missing:poi" in report["cases"][0]["error"]


@pytest.mark.parametrize("rows", [[], [{"id": "none", "request": {"query": "alpha"},
                                       "expect": {"relevant_poi_ids": []}}]])
def test_empty_metric_denominator_is_not_success(dataset, tmp_path, rows):
    report = run(golden(tmp_path, rows))
    assert report["summary"]["evaluated_cases"] == 0
    assert report["summary"]["hit_at_5"] is None
    assert report["summary"]["macro_recall_at_5"] is None
    assert report["summary"]["micro_recall_at_5"] is None
    assert report["exit_code"] != 0


@pytest.mark.parametrize("label", ["missing:id", "shared:alias"])
def test_unknown_or_ambiguous_labels_are_visible_errors(dataset, tmp_path, label):
    pois = json.loads(dataset.read_text())
    pois[0]["source_records"].append({"id": "shared:alias"})
    pois[1]["source_records"].append({"id": "shared:alias"})
    dataset.write_text(json.dumps(pois), encoding="utf-8")
    report = run(golden(tmp_path, [{"id": "invalid-label", "query": "alpha",
                                   "expect": {"must_include_any": [label]}}]))
    assert report["cases"][0]["status"] == "ERROR"
    assert label in report["cases"][0]["error"]
    assert report["summary"]["error_cases"] == 1
    assert report["summary"]["hit_at_5"] is None
    assert report["exit_code"] != 0


@pytest.mark.parametrize("rows", [
    {"wrong": []},
    [{"id": "bad-labels", "query": "alpha", "expect": {"must_include_any": "p:a"}}],
    [{"id": "bad-query", "query": 7, "expect": {"must_include_any": ["p:a"]}}],
    {"queries": [{"id": "grade", "type": "named", "query": "alpha", "relevant": {"p:a": -1}}]},
    [{"id": "half-point", "query": "alpha", "location": {"lat": 0},
      "expect": {"must_include_any": ["p:a"]}}],
    [{"id": "null-point", "request": {"query": "alpha", "location": {"lat": None, "lon": None}},
      "expect": {"must_include_any": ["p:a"]}}],
])
def test_malformed_cases_fail_visibly(dataset, tmp_path, rows):
    report = run(golden(tmp_path, rows))
    assert report["exit_code"] != 0
    assert report["errors"] or report["summary"]["error_cases"]


def test_retrieval_failure_is_not_converted_to_empty_results(dataset, tmp_path):
    pois = json.loads(dataset.read_text())
    del pois[0]["tags"]  # The real retriever cannot construct this document.
    dataset.write_text(json.dumps(pois), encoding="utf-8")
    report = run(golden(tmp_path, [{"id": "broken-retrieval", "query": "alpha",
                                   "expect": {"must_include_any": ["p:a"]}}]))
    assert report["cases"][0]["status"] == "ERROR"
    assert "retrieval" in report["cases"][0]["error"].lower()
    assert report["summary"]["evaluated_cases"] == 0
    assert report["exit_code"] != 0


def test_bm25_real_responses_preserve_fact_fields_and_restore_mode(dataset, tmp_path):
    report = run(golden(tmp_path, [{"id": "facts", "query": "alpha",
                                   "expect": {"must_include_any": ["p:a"]}}]))
    # A hybrid fallback would fail on this temporary dataset's absent dense index.
    row = report["cases"][0]
    assert row["status"] == "HIT"
    assert row["retrieved"][0]["id"] == "p:a"
    assert row["retrieved"][0]["wheelchair"] is None
    assert row["retrieved"][0]["opening_hours"] is None
    assert row["retrieved"][0]["description_kind"] == "structured_template"
    assert row["retrieved"][0]["score"] > 0
    assert row["retrieved"][0]["distance_m"] is None
    assert os.environ["RAG_SEARCH_MODE"] == "hybrid"


def test_output_artifacts_include_input_and_source_provenance(dataset, tmp_path):
    path = golden(tmp_path, [{"id": "one", "query": "alpha",
                              "expect": {"must_include_any": ["p:a"]}}])
    output = tmp_path / "results"
    report = run(path, output_dir=output, mode="bm25")
    assert json.loads((output / "report.json").read_text()) == report
    assert json.loads((output / "summary.json").read_text())["summary"]["hit_at_5"] == 1
    assert json.loads((output / "cases.jsonl").read_text())["top5_ids"] == ["p:a"]
    provenance = report["provenance"]
    assert provenance["dataset"]["sha256"] == hashlib.sha256(dataset.read_bytes()).hexdigest()
    assert provenance["dataset"]["count"] == 3
    assert provenance["golden"]["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert "rag/retriever.py" in provenance["source_files"]
    assert len(provenance["code_sha256"]) == 64
    assert provenance["config"]["mode"] == "bm25"
    assert provenance["config"]["location_scope"] == "explicit_coordinates_only"


def test_cli_keeps_positional_golden_and_returns_failure_for_unlabelled(dataset, tmp_path, capsys):
    path = golden(tmp_path, [{"id": "none", "request": {"query": "alpha"}, "expect": {}}])
    output = tmp_path / "cli"
    result = evaluator.main([str(path), "--mode", "bm25", "--output-dir", str(output)])
    assert result != 0
    assert json.loads(capsys.readouterr().out.strip().splitlines()[-1])["summary"]["hit_at_5"] is None
    assert (output / "report.json").exists()


def test_cli_keeps_full_poi_cards_in_artifacts_and_omits_them_from_stdout(dataset, tmp_path, capsys):
    path = golden(tmp_path, [{"id": "concise", "query": "alpha",
                              "expect": {"must_include_any": ["p:a"]}}])
    output = tmp_path / "concise"
    assert evaluator.main([str(path), "--output-dir", str(output)]) == 0
    stdout = capsys.readouterr().out
    assert '"retrieved"' not in stdout
    assert '"description_kind"' not in stdout
    assert json.loads(stdout.strip().splitlines()[-1])["summary"]["hit_at_5"] == 1
    assert json.loads((output / "report.json").read_text())["cases"][0]["retrieved"][0]["name"] == "alpha"


def test_cli_label_errors_are_actionable_even_without_output_directory(dataset, tmp_path, capsys):
    path = golden(tmp_path, [{"id": "unknown-cli-label", "query": "alpha",
                              "expect": {"must_include_any": ["missing:poi"]}}])
    assert evaluator.main([str(path)]) != 0
    stdout = capsys.readouterr().out
    assert "missing:poi" in stdout
    assert "unknown-cli-label" in stdout


def test_malformed_json_writes_actionable_failure_report(dataset, tmp_path):
    path = tmp_path / "invalid.json"
    path.write_text("{not json", encoding="utf-8")
    report = run(path, output_dir=tmp_path / "broken")
    assert report["exit_code"] != 0
    assert "golden" in report["errors"][0].lower()
    assert (tmp_path / "broken/report.json").exists()

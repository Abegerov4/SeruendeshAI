"""Hand-derived metric examples: missing evidence must never become a score."""

import math

import pytest

from eval.metrics import latency_percentiles, retrieval_metrics


def test_retrieval_deduplicates_before_taking_k():
    result = retrieval_metrics(["a", "a", "b", "c"], ["b", "c", "c", "d"], k=2)
    assert result["hit_at_k"] == 1.0
    assert result["recall_at_k"] == pytest.approx(1 / 3)
    assert result["precision_at_k"] == 0.5


def test_hit_is_not_recall():
    result = retrieval_metrics(["a"], ["a", "b", "c", "d"], k=5)
    assert result["hit_at_k"] == 1.0
    assert result["recall_at_k"] == 0.25


def test_retrieval_miss_and_empty_retrieval_have_zero_scores():
    for retrieved in (["x"], []):
        result = retrieval_metrics(retrieved, ["a"], k=5)
        assert result["hit_at_k"] == 0
        assert result["recall_at_k"] == 0
        assert result["precision_at_k"] == 0


def test_unlabelled_relevance_is_not_evaluated():
    result = retrieval_metrics(["a"], [], k=5)
    assert result["hit_at_k"] is None
    assert result["recall_at_k"] is None
    assert result["precision_at_k"] is None


@pytest.mark.parametrize("k", [0, -1, True, 1.5])
def test_retrieval_rejects_invalid_cutoffs(k):
    with pytest.raises(ValueError):
        retrieval_metrics(["a"], ["a"], k=k)


def test_latency_interpolates_linear_order_statistics():
    # Sorted values 10,20,30,100: (n-1)*.5=1.5 and *.95=2.85.
    assert latency_percentiles([100, 10, 30, 20]) == pytest.approx({
        "p50_ms": 25.0,
        "p95_ms": 89.5,
    })


def test_latency_without_samples_is_not_evaluated():
    assert latency_percentiles([]) == {"p50_ms": None, "p95_ms": None}
    assert latency_percentiles([7]) == {"p50_ms": 7.0, "p95_ms": 7.0}


@pytest.mark.parametrize("value", [True, -1, math.nan, math.inf, "3", None, 10 ** 1000])
def test_latency_rejects_non_finite_non_numeric_or_negative_samples(value):
    with pytest.raises(ValueError):
        latency_percentiles([value])

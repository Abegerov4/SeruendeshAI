"""Small deterministic metrics. Missing labels/samples have null scores."""

from math import floor, isfinite


def _valid_latency(value):
    try:
        return isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value) and value >= 0
    except OverflowError:
        return False


def _unique_ids(values: list[str]) -> list[str]:
    if not isinstance(values, list) or any(not isinstance(v, str) or not v.strip() for v in values):
        raise ValueError("IDs must be a list of nonempty strings")
    return list(dict.fromkeys(values))


def retrieval_metrics(retrieved_ids: list[str], relevant_ids: list[str], k: int = 5) -> dict:
    """Deduplicate before top-k; precision uses returned unique top-k count.

    hit@k is 0 or 1, recall@k divides by all unique relevant IDs. An empty
    relevance list means unannotated, so every relevance score is None.
    """
    if isinstance(k, bool) or not isinstance(k, int) or k <= 0:
        raise ValueError("k must be a positive integer")
    retrieved = _unique_ids(retrieved_ids)[:k]
    relevant = set(_unique_ids(relevant_ids))
    if not relevant:
        return {"hit_at_k": None, "recall_at_k": None, "precision_at_k": None}
    matched = len(set(retrieved) & relevant)
    return {
        "hit_at_k": float(matched > 0),
        "recall_at_k": matched / len(relevant),
        "precision_at_k": matched / len(retrieved) if retrieved else 0.0,
    }


def latency_percentiles(values_ms: list[float]) -> dict:
    """Return p50/p95 using linear interpolation at index (n - 1) * p.

    This is the common type-7 sample quantile. Empty samples yield None;
    invalid, nonfinite, negative, or boolean samples raise ValueError.
    """
    if not isinstance(values_ms, list) or any(not _valid_latency(v) for v in values_ms):
        raise ValueError("latencies must be finite nonnegative numbers")
    values = sorted(float(v) for v in values_ms)
    if not values:
        return {"p50_ms": None, "p95_ms": None}

    def percentile(p):
        position = (len(values) - 1) * p
        lower = floor(position)
        upper = min(lower + 1, len(values) - 1)
        return values[lower] + (values[upper] - values[lower]) * (position - lower)

    return {"p50_ms": percentile(0.5), "p95_ms": percentile(0.95)}

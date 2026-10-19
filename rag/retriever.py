import hashlib
import json
import math
import os
from collections import Counter
from functools import lru_cache
from pathlib import Path

from .geo import haversine_m
from .text import document, tokens

ROOT = Path(__file__).resolve().parents[1]

@lru_cache(maxsize=2)
def _load(path, modified, size):
    raw = Path(path).read_bytes()
    pois = json.loads(raw)
    docs = [Counter(tokens(document(p))) for p in pois]
    frequencies = Counter(t for doc in docs for t in doc)
    average = sum(sum(d.values()) for d in docs) / max(1, len(docs))
    return pois, docs, frequencies, average, hashlib.sha256(raw).hexdigest()

@lru_cache(maxsize=4)
def _catalog(root, legacy):
    from data.snapshot import resolve_snapshot
    from data.eligibility import load_reviews, review_matches, exclusion_reasons, safe_facts, evidence_for_hours
    handle = resolve_snapshot(Path(root) / "data/processed", legacy=legacy)
    path = handle.path / "pois.json"
    raw = path.read_bytes()
    rows = json.loads(raw)
    overlay = handle.path / "fact_reviews.json"
    if overlay.exists():
        from data.eligibility import apply_fact_reviews
        rows = apply_fact_reviews(rows, json.loads(overlay.read_bytes()), canonical_sha256=hashlib.sha256(raw).hexdigest())
    review_path = handle.path / "quarantine.json" if handle.version != "legacy" else Path(root) / "data/quarantine.json"
    matches, unmatched, ambiguous = review_matches(rows, load_reviews(review_path))
    evidence_path = handle.path / "field_evidence.json"
    external = json.loads(evidence_path.read_bytes()) if evidence_path.exists() else {}
    from data.eligibility import source_ids
    pois = [dict(safe_facts(p), **evidence_for_hours(p, [e for ident in source_ids(p) for e in external.get(ident, [])])) for p in rows]
    eligible = {i for i, row in enumerate(rows) if not exclusion_reasons(row, row["id"] in matches)}
    docs = [Counter(tokens(document(p))) for p in pois]
    frequencies = Counter(t for doc in docs for t in doc)
    average = sum(sum(d.values()) for d in docs) / max(1, len(docs))
    return {"handle": handle, "pois": pois, "eligible": eligible, "docs": docs,
            "frequencies": frequencies, "average": average, "digest": hashlib.sha256(raw).hexdigest(),
            "quarantine_unmatched_ids": unmatched, "quarantine_ambiguous_ids": ambiguous}


def catalog():
    """One bound version for search, map and ID lookup; restart to adopt current."""
    return _catalog(str(ROOT), os.getenv("DATA_SNAPSHOT_MODE", "") == "legacy")


def all_pois():
    selected = catalog()
    return [p for i, p in enumerate(selected["pois"]) if i in selected["eligible"]]


def _bm25(query_tokens, docs, frequencies, average, indices):
    scores = {}
    n = len(docs)
    for i in indices:
        doc = docs[i]
        length = sum(doc.values())
        score = 0.0
        for token in set(query_tokens):
            tf = doc[token]
            if tf:
                idf = math.log(1 + (n - frequencies[token] + .5)/(frequencies[token] + .5))
                score += idf * tf * 2.5/(tf + 1.5*(.25 + .75*length/max(average, 1)))
        if score > 0:
            scores[i] = score
    return sorted(scores, key=lambda i: (-scores[i], i))[:30]

def _dense(query, pois, indices, digest):
    manifest_path = ROOT / 'rag/chroma/manifest.json'
    if not manifest_path.exists():
        raise RuntimeError('Dense index missing; run python rag/build_index.py')
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    if manifest['sha256'] != digest:
        raise RuntimeError('Dense index is stale; rebuild after changing pois.json')
    import chromadb
    from .embeddings import embed
    collection = chromadb.PersistentClient(path=str(manifest_path.parent)).get_collection(manifest['collection'])
    query_embedding = embed([query], manifest['provider'], manifest['model'])
    # Restrict candidate IDs BEFORE nearest-neighbour search, including geo filtering.
    lookup = {pois[i]['id']: i for i in indices}
    response = collection.query(query_embeddings=query_embedding, n_results=min(30, len(indices)),
                                where={'id': {'$in': list(lookup)}}, include=['distances'])
    return [lookup[key] for key in response['ids'][0] if key in lookup]

def search(query: str, lat: float | None, lon: float | None,
           radius_m: int = 2000, categories: list[str] | None = None,
           top_k: int = 15) -> list[dict]:
    if (lat is None) != (lon is None):
        raise ValueError('Provide both latitude and longitude, or neither')
    if radius_m < 0 or top_k < 0:
        raise ValueError('radius_m and top_k must be nonnegative')
    if not query.strip() or top_k == 0:
        return []
    selected = catalog()
    pois, docs = selected["pois"], selected["docs"]
    frequencies, average, digest = selected["frequencies"], selected["average"], selected["digest"]
    distances, indices = {}, []
    for i, poi in enumerate(pois):
        if i not in selected["eligible"]:
            continue
        if categories is not None and poi['category'] not in categories:
            continue
        distance = None if lat is None else haversine_m(lat, lon, poi['lat'], poi['lon'])
        if distance is not None and distance > radius_m:
            continue
        indices.append(i)
        distances[i] = distance
    if not indices:
        return []
    lexical = _bm25(tokens(query), docs, frequencies, average, indices)
    rankings = [lexical]
    mode = os.getenv('RAG_SEARCH_MODE', 'hybrid')
    if mode not in ('hybrid', 'bm25'):
        raise ValueError('RAG_SEARCH_MODE must be hybrid or bm25')
    if mode == 'hybrid':
        # Fail explicitly rather than disguising a broken dense index as hybrid search.
        rankings.append(_dense(query, pois, indices, digest))
    scores = Counter()
    for ranking in rankings:
        for rank, i in enumerate(ranking, 1):
            scores[i] += 1 / (60 + rank)
    for i in scores:
        distance = distances[i]
        proximity = 0 if distance is None else .05 * max(0, 1-distance/max(radius_m, 1))
        popularity = .02 if any(t.startswith('wikipedia=') for t in pois[i]['tags']) else 0
        scores[i] *= 1 + proximity + popularity
    ordered = sorted(scores, key=lambda i: (-scores[i], pois[i]['id']))[:top_k]
    return [dict(pois[i], distance_m=distances[i], score=float(scores[i])) for i in ordered]

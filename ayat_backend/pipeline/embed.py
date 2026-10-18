"""Precompute POI passage embeddings (row-aligned with pois.jsonl)."""
from __future__ import annotations

import json
import logging
import time

import numpy as np

from app.embedder import Embedder
from app.paths import EMBEDDINGS_FILE, MANIFEST_FILE, POIS_FILE
from app.store import poi_document

log = logging.getLogger("pipeline.embed")


def embed_pois(model: str) -> dict:
    pois = [json.loads(line) for line in POIS_FILE.open(encoding="utf-8") if line.strip()]
    t0 = time.time()
    emb = Embedder(model).passages([poi_document(p)[:1000] for p in pois])
    np.save(EMBEDDINGS_FILE, emb.astype(np.float16))  # float16 halves the committed file; cast back at load
    man = json.loads(MANIFEST_FILE.read_text())
    man["embedding_model"] = model
    man["embedding_dim"] = int(emb.shape[1])
    man["embedding_pois_sha"] = man.get("pois_sha")
    MANIFEST_FILE.write_text(json.dumps(man, ensure_ascii=False, indent=1))
    info = {"model": model, "rows": int(emb.shape[0]), "secs": round(time.time() - t0, 1)}
    log.info("embeddings: %s", info)
    return info

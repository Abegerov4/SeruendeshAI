"""Local multilingual embeddings (multilingual-e5, int8 ONNX via fastembed; no torch).

e5 requires the "query: " / "passage: " prefixes. Model choice is an env setting:
e5-large (best RU/KK quality, ~1 GB RSS), e5-small (~0.55 GB) or off.
"""
from __future__ import annotations

import logging
import os
from functools import lru_cache

import numpy as np

from app.paths import MODELS_DIR

log = logging.getLogger("app.embedder")

MODELS = {
    "e5-large": ("Xenova/multilingual-e5-large", 1024),
    "e5-base": ("Xenova/multilingual-e5-base", 768),
    "e5-small": ("Xenova/multilingual-e5-small", 384),
}


class Embedder:
    def __init__(self, name: str, threads: int = 4):
        from fastembed import TextEmbedding
        from fastembed.common.model_description import ModelSource, PoolingType

        repo, dim = MODELS[name]
        self.name, self.dim = name, dim
        try:
            TextEmbedding.add_custom_model(model=repo, pooling=PoolingType.MEAN, normalization=True,
                                           sources=ModelSource(hf=repo), dim=dim, model_file="onnx/model_quantized.onnx")
        except ValueError:
            pass  # already registered in this process
        MODELS_DIR.mkdir(parents=True, exist_ok=True)
        self.model = TextEmbedding(repo, threads=threads, cache_dir=str(MODELS_DIR))

    def passages(self, texts: list[str], batch_size: int = 32) -> np.ndarray:
        it = self.model.embed(["passage: " + t for t in texts], batch_size=batch_size)
        return np.asarray(list(it), dtype=np.float32)

    def query(self, text: str) -> np.ndarray:
        return np.asarray(next(iter(self.model.embed(["query: " + text]))), dtype=np.float32)


@lru_cache(maxsize=1)
def get_embedder(name: str) -> Embedder | None:
    if name in ("", "off", "none"):
        return None
    try:
        if (MODELS_DIR / ".offline").exists():
            os.environ.setdefault("HF_HUB_OFFLINE", "1")
        return Embedder(name)
    except Exception as e:  # missing model / no network: API still works with BM25 only
        log.warning("embedder %s unavailable: %s", name, e)
        return None

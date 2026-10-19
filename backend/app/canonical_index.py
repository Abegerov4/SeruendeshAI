"""A canonical dense matrix is usable only for its exact reviewed document view."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import uuid

import numpy as np

from app.embedder import MODELS


def policy_hashes(snapshot_dir: Path) -> dict[str, str | None]:
    from data import eligibility
    from app import store
    root = Path(snapshot_dir)
    quarantine = root / "quarantine.json"
    if not quarantine.exists():
        quarantine = root.parent / "quarantine.json"
    paths = {"quarantine": quarantine, "field_evidence": root / "field_evidence.json",
             "fact_reviews": root / "fact_reviews.json", "eligibility_code": Path(eligibility.__file__),
             "document_code": Path(store.__file__),"place_details":root / "place_details.json",
             "place_details_code":Path(__file__).resolve().parents[2]/"data"/"place_details.py"}
    return {key: hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None for key, path in paths.items()}


def _view(pois, model, policies):
    from app.store import poi_document
    if model not in MODELS:
        raise ValueError("Unknown canonical embedding model")
    documents = [poi_document(row)[:1000] for row in pois]
    return {"schema_version": 1, "model": model, "model_repo": MODELS[model][0], "dimension": MODELS[model][1],
            "ordered_ids": [row["id"] for row in pois], "policy_hashes": policies,
            "documents_sha256": hashlib.sha256(json.dumps(documents, ensure_ascii=False).encode()).hexdigest()}, documents


def build_index(pois, encoder, output_dir, *, policy_hashes: dict) -> dict:
    manifest, documents = _view(pois, encoder.name, policy_hashes)
    matrix = np.asarray(encoder.passages(documents), dtype=np.float32)
    if matrix.shape != (len(pois), manifest["dimension"]) or not np.isfinite(matrix).all():
        raise ValueError("Invalid canonical embedding matrix")
    norm = np.linalg.norm(matrix, axis=1, keepdims=True)
    if (norm <= 0).any():
        raise ValueError("Zero embedding vector")
    matrix /= norm
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    temporary = output / (".vectors-" + uuid.uuid4().hex)
    with temporary.open("wb") as handle:
        np.save(handle, matrix, allow_pickle=False)
        handle.flush()
        os.fsync(handle.fileno())
    digest = hashlib.sha256(temporary.read_bytes()).hexdigest()
    artifact = "vectors-" + digest[:24] + ".npy"
    os.replace(temporary, output / artifact)
    manifest.update(artifact=artifact, artifact_sha256=digest, rows=len(pois))
    pending = output / (".manifest-" + uuid.uuid4().hex)
    with pending.open("w") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(pending, output / "manifest.json")
    return manifest


def load_index(pois, model, index_dir, *, policy_hashes: dict) -> np.ndarray:
    root = Path(index_dir)
    manifest_path = root / "canonical_index_manifest.json"
    if not manifest_path.exists():
        manifest_path = root / "manifest.json"
    metadata = json.loads(manifest_path.read_text())
    expected, _ = _view(pois, model, policy_hashes)
    if any(metadata.get(key) != value for key, value in expected.items()):
        raise ValueError("Canonical index is stale for IDs/documents/model/policy")
    name = metadata.get("artifact", "")
    if Path(name).name != name or not name.endswith(".npy"):
        raise ValueError("Canonical index is corrupt: invalid artifact")
    path = root / name
    if hashlib.sha256(path.read_bytes()).hexdigest() != metadata.get("artifact_sha256"):
        raise ValueError("Canonical index is corrupt: hash mismatch")
    matrix = np.load(path, allow_pickle=False)
    if matrix.shape != (len(pois), expected["dimension"]) or not np.isfinite(matrix).all():
        raise ValueError("Canonical index is corrupt: shape/values")
    return matrix.astype(np.float32)

import copy

import numpy as np
import pytest


def pois():
    return [{"id": "a", "name": "Alpha cafe", "category": "cafe", "features": {}},
            {"id": "b", "name": "Beta cafe", "category": "cafe", "features": {}}]


class LocalEncoder:
    name, dim = "e5-small", 384

    def passages(self, docs):
        matrix = np.zeros((len(docs), 384), dtype=np.float32)
        matrix[:, 0] = 1
        return matrix


def test_canonical_index_checks_order_documents_policy_and_model(tmp_path):
    from ayat_backend.app.canonical_index import build_index, load_index
    rows = pois()
    build_index(rows, LocalEncoder(), tmp_path, policy_hashes={"reviews": "one"})
    assert load_index(rows, "e5-small", tmp_path, policy_hashes={"reviews": "one"}).shape == (2, 384)
    for changed in [list(reversed(rows)), [{**rows[0], "name": "Changed"}, rows[1]]]:
        with pytest.raises(ValueError, match="stale"):
            load_index(changed, "e5-small", tmp_path, policy_hashes={"reviews": "one"})
    with pytest.raises(ValueError, match="stale"):
        load_index(rows, "e5-small", tmp_path, policy_hashes={"reviews": "two"})
    with pytest.raises(ValueError, match="stale"):
        load_index(rows, "e5-large", tmp_path, policy_hashes={"reviews": "one"})


def test_corrupt_index_is_rejected_instead_of_used(tmp_path):
    from ayat_backend.app.canonical_index import build_index, load_index
    build_index(pois(), LocalEncoder(), tmp_path, policy_hashes={})
    artifact = next(tmp_path.glob("*.npy"))
    artifact.write_bytes(b"broken")
    with pytest.raises(ValueError, match="corrupt"):
        load_index(pois(), "e5-small", tmp_path, policy_hashes={})

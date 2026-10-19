"""Build local, version-aligned canonical embeddings; never uses a paid provider."""
import argparse
import json
from pathlib import Path

from ayat_backend.app.canonical_index import build_index, policy_hashes
from ayat_backend.app.embedder import Embedder, MODELS
from ayat_backend.app.store import load_store


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", choices=MODELS, default="e5-small")
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)
    store = load_store("off")
    snapshot = Path(store.manifest["snapshot_path"])
    if store.manifest.get("snapshot_version") != "legacy" and (args.output_dir is None or args.output_dir.resolve().is_relative_to(snapshot.resolve())):
        parser.error("An active immutable snapshot cannot be edited; use --output-dir for a staged derived index, then publish a new bundle")
    output = args.output_dir or snapshot / "canonical_index"
    result = build_index(store.pois, Embedder(args.model), output, policy_hashes=policy_hashes(snapshot))
    print(json.dumps({key: result[key] for key in ("model", "rows", "dimension", "documents_sha256")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

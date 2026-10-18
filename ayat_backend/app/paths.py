from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
ROOT_DIR = BACKEND_DIR.parent
DATA_DIR = ROOT_DIR / "data"
RAW_DIR = DATA_DIR / "raw"  # gitignored HTTP caches / raw downloads
PROCESSED_DIR = DATA_DIR / "processed"  # committed snapshot the API loads
MODELS_DIR = ROOT_DIR / "models"  # gitignored embedding model cache

POIS_FILE = PROCESSED_DIR / "pois.jsonl"
GAZETTEER_FILE = PROCESSED_DIR / "gazetteer.json"
MANIFEST_FILE = PROCESSED_DIR / "manifest.json"
EMBEDDINGS_FILE = PROCESSED_DIR / "embeddings.npy"
GRAPH_FILE = PROCESSED_DIR / "walk_graph.npz"
RIVER_FILE = PROCESSED_DIR / "river.json"
EVENTS_FILE = PROCESSED_DIR / "events.jsonl"
BOUNDARY_FILE = PROCESSED_DIR / "astana_boundary.geojson"

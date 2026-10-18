"""Build a versioned persistent index; switch manifest only after success."""
import hashlib
import json
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from rag.text import document
from rag.embeddings import embed, config

def main():
    import chromadb
    path = ROOT / 'data/processed/pois.json'
    raw = path.read_bytes()
    pois = json.loads(raw)
    if not pois:
        raise ValueError('Dataset is empty')
    provider, model = config()
    directory = ROOT / 'rag/chroma'
    client = chromadb.PersistentClient(path=str(directory))
    name = 'pois-' + uuid.uuid4().hex
    collection = client.create_collection(name, metadata={'provider': provider, 'model': model, 'hnsw:space': 'cosine'})
    for offset in range(0, len(pois), 64):
        batch = pois[offset:offset+64]
        texts = [document(p) for p in batch]
        metadata = [{k: p[k] for k in ('id', 'category', 'lat', 'lon', 'kid_friendly', 'wheelchair') if p[k] is not None} for p in batch]
        collection.add(ids=[p['id'] for p in batch], documents=texts, metadatas=metadata, embeddings=embed(texts, provider, model))
        print(f'Indexed {min(offset+64, len(pois))}/{len(pois)}', flush=True)
    manifest = {'collection': name, 'sha256': hashlib.sha256(raw).hexdigest(), 'provider': provider, 'model': model}
    tmp = directory / 'manifest.tmp'
    tmp.write_text(json.dumps(manifest), encoding='utf-8')
    tmp.replace(directory / 'manifest.json')

if __name__ == '__main__':
    main()

import os

def embed(texts, provider, model):
    if provider == 'openai':
        from openai import OpenAI
        client = OpenAI(timeout=45, max_retries=2)
        response = client.embeddings.create(model=model, input=texts)
        return [row.embedding for row in sorted(response.data, key=lambda r: r.index)]
    if provider == 'bge':
        return _local(model).encode(texts, normalize_embeddings=True).tolist()
    raise ValueError('Embedding provider must be openai or bge')

from functools import lru_cache

@lru_cache(maxsize=1)
def _local(model):
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(model)

def config():
    provider = os.getenv('RAG_EMBEDDING_PROVIDER', 'openai')
    model = os.getenv('RAG_EMBEDDING_MODEL', 'BAAI/bge-m3' if provider == 'bge' else 'text-embedding-3-small')
    return provider, model

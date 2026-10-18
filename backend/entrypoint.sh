#!/bin/sh
# Собираем dense-индекс при первом старте (rag/chroma не входит в образ). Без ключа — rag/ уйдёт в BM25.
set -e
if [ -f rag/build_index.py ] && [ ! -f rag/chroma/manifest.json ] && [ -n "${OPENAI_API_KEY:-${openai_api_key:-}}" ]; then
  python -c "import backend.app.config, runpy, sys; sys.argv=['rag/build_index.py']; runpy.run_path('rag/build_index.py', run_name='__main__')" \
    || echo "index build failed, search will degrade to BM25"
fi
exec "$@"

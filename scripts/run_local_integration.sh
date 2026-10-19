#!/bin/sh
# Local UI/API profile: actual canonical data, accounts in local SQLite, no providers.
set -eu
repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$repo_root"
mkdir -p ayat_backend/.local
exec env \
  OPENAI_API_KEY= openai_api_key= LLM_API_KEY= \
  LANGFUSE_PUBLIC_KEY= LANGFUSE_SECRET_KEY= \
  LLM_ENABLED=false EMBED_MODEL=off WEATHER_ENABLED=false \
  SMTP_HOST= SMTP_USER= SMTP_PASSWORD= SMTP_FROM= \
  DATABASE_URL="sqlite:///$repo_root/ayat_backend/.local/integration.db" \
  SECRET_KEY=local-integration-only RATE_LIMIT_PER_MIN=300 \
  "${SERU_PYTHON:-$repo_root/.venv/bin/python}" -m uvicorn ayat_backend.app.main:app \
  --host 127.0.0.1 --port "${SERU_LOCAL_PORT:-8001}" "$@"

FROM node:22-alpine AS frontend
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.12.23 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1 HF_HUB_OFFLINE=0
WORKDIR /srv/ayat_backend
COPY ayat_backend/pyproject.toml ayat_backend/uv.lock ayat_backend/.python-version ./
RUN uv sync --python /usr/local/bin/python --frozen --no-dev --no-group pipeline --no-install-project
COPY ayat_backend/app ./app
COPY ayat_backend/pipeline ./pipeline
COPY ayat_backend/__init__.py ./__init__.py
COPY data/ /srv/data/
COPY runtime_support/ /srv/runtime_support/
COPY --from=frontend /web/dist /srv/frontend/dist
# Dense models are opt-in; canonical indexes must match the selected snapshot.
ARG EMBED_MODEL=off
ENV EMBED_MODEL=${EMBED_MODEL} PYTHONPATH=/srv PATH="/srv/ayat_backend/.venv/bin:$PATH" PORT=8000 FORWARDED_ALLOW_IPS=127.0.0.1
RUN if [ "$EMBED_MODEL" != "off" ]; then python -c "from ayat_backend.app.embedder import Embedder; Embedder('${EMBED_MODEL}')"; fi
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')"
CMD ["sh", "-c", "uvicorn ayat_backend.app.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips=${FORWARDED_ALLOW_IPS}"]

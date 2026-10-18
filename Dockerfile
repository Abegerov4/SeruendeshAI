# One image = API + built frontend (served by FastAPI on the same domain).
# Railway builds this file from branch `ayat` (see railway.json).

# --- 1. frontend (React + Vite) ---------------------------------------------------------------
FROM node:22-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# --- 2. backend (FastAPI) ---------------------------------------------------------------------
FROM python:3.13-slim
COPY --from=ghcr.io/astral-sh/uv:0.12.23 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never PYTHONUNBUFFERED=1
WORKDIR /srv/backend
COPY backend/pyproject.toml backend/uv.lock backend/.python-version ./
RUN uv sync --frozen --no-dev --no-group pipeline --no-install-project
COPY backend/app ./app
COPY data/processed /srv/data/processed
COPY --from=web /web/dist /srv/frontend/dist

# embedding model baked into the image (no download at start-up); EMBED_MODEL=off skips it
ARG EMBED_MODEL=e5-large
ENV EMBED_MODEL=${EMBED_MODEL} PATH="/srv/backend/.venv/bin:$PATH" PORT=8000 FRONTEND_DIST=/srv/frontend/dist
RUN if [ "$EMBED_MODEL" != "off" ]; then \
      python -c "from app.embedder import Embedder; Embedder('${EMBED_MODEL}')" && touch /srv/models/.offline; \
    fi

EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]

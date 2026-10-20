# One image = API + built frontend (served by FastAPI on the same domain).
# Railway builds this file (see railway.json); main and ayat carry the same app.

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
# small pure-Python helpers of the team catalogue (data/), imported by app.evidence and the opt-in canonical mode
COPY data/__init__.py data/meal_cost.py data/eligibility.py data/snapshot.py data/city_services.py data/place_details.py /srv/data/
COPY runtime_support /srv/runtime_support
# the Telegram bot (Abegerov4's API client) runs in this process by webhook when TELEGRAM_BOT_TOKEN is set
COPY bot/__init__.py bot/telegram_bot.py bot/format.py /srv/bot/
# only the snapshot the API reads (the team's research catalogue in data/ stays out of the image)
COPY data/processed/pois.jsonl data/processed/gazetteer.json data/processed/manifest.json data/processed/embeddings.npy \
     data/processed/walk_graph.npz data/processed/drive_graph.npz data/processed/events.jsonl data/processed/river.json \
     data/processed/astana_boundary.geojson data/processed/photos_extra.json data/processed/place_facts.json \
     data/processed/place_names.json data/processed/place_descriptions_kk.json /srv/data/processed/
COPY --from=web /web/dist /srv/frontend/dist

# embedding model baked into the image (no download at start-up); EMBED_MODEL=off skips it
ARG EMBED_MODEL=e5-large
ENV EMBED_MODEL=${EMBED_MODEL} PATH="/srv/backend/.venv/bin:$PATH" PORT=8000 FRONTEND_DIST=/srv/frontend/dist
RUN if [ "$EMBED_MODEL" != "off" ]; then \
      python -c "from app.embedder import Embedder; Embedder('${EMBED_MODEL}')" && touch /srv/models/.offline; \
    fi

EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*' --no-access-log"]

FROM python:3.13-slim
COPY --from=ghcr.io/astral-sh/uv:0.12.23 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1 HF_HUB_OFFLINE=0
WORKDIR /srv/backend
COPY ayat_backend/pyproject.toml ayat_backend/uv.lock ayat_backend/.python-version ./
RUN uv sync --frozen --no-dev --no-group pipeline --no-install-project
COPY ayat_backend/app ./app
COPY data/processed /srv/data/processed
# pre-fetch the embedding model into the image (set EMBED_MODEL=off at build time to skip)
ARG EMBED_MODEL=e5-large
ENV EMBED_MODEL=${EMBED_MODEL} PATH="/srv/backend/.venv/bin:$PATH" PORT=8000
RUN if [ "$EMBED_MODEL" != "off" ]; then python -c "from app.embedder import Embedder; Embedder('${EMBED_MODEL}')"; fi
EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]

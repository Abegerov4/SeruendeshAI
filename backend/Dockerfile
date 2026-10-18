# Сборка из корня репозитория:  docker build -f backend/Dockerfile -t seruendesh-backend .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend/ backend/
# rag/ и data/ появятся после merge ветки feature/data-rag; без них бэкенд работает на mock-фикстуре
COPY . /tmp/repo
RUN if [ -d /tmp/repo/rag ]; then cp -r /tmp/repo/rag /app/rag && pip install --no-cache-dir -r /app/rag/requirements.txt || true; fi \
 && if [ -d /tmp/repo/data/processed ]; then mkdir -p /app/data && cp -r /tmp/repo/data/processed /app/data/processed; fi \
 && rm -rf /tmp/repo

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')"
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]

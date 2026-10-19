# Сборка из корня репозитория:  docker build -f backend/Dockerfile -t seruendesh-backend .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY backend/requirements.txt backend/requirements.txt
COPY rag/requirements.txt rag/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt -r rag/requirements.txt

COPY backend/ backend/
COPY rag/ rag/
COPY data/ data/
COPY runtime_support/ runtime_support/

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')"
ENTRYPOINT ["backend/entrypoint.sh"]
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]

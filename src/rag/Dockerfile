# Dockerfile para a app Python de RAG Query Builder (Ollama-only, FastAPI)
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Dependência para API
RUN pip install --no-cache-dir fastapi uvicorn

COPY app.py /app/app.py

RUN mkdir -p /app/corpus

# Rodar a API FastAPI
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
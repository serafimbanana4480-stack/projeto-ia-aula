FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# System deps for chromadb, psutil and docker SDK
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copy docker-specific lightweight requirements (NO PyTorch/CUDA)
COPY docker/backend/requirements-docker.txt /app/requirements-docker.txt
RUN pip install --upgrade pip && pip install -r /app/requirements-docker.txt && pip install mcp

COPY backend /app/backend
COPY config  /app/config
COPY pyproject.toml /app/pyproject.toml

RUN mkdir -p /app/logs /app/data \
    && groupadd -r nexus \
    && useradd -r -g nexus nexus \
    && chown -R nexus:nexus /app

USER nexus

EXPOSE 8000
CMD ["uvicorn", "backend.orchestrator.main:app", "--host", "0.0.0.0", "--port", "8000"]

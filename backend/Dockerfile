# =============================================================================
# Sentinel-KE Backend — Production Dockerfile
#
# Build:  docker compose build
# Run:    docker compose up -d
#
# Code changes require a rebuild:
#   docker compose build backend && docker compose up -d backend
#
# GPU:    edit requirements.txt — change --extra-index-url to:
#           https://download.pytorch.org/whl/cu121
# =============================================================================
FROM python:3.12-slim

WORKDIR /app

ENV PYTHONPATH=/app \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=600 \
    PIP_RETRIES=25

# Install dependencies first — this layer is cached until requirements.txt changes
COPY requirements.txt .
RUN pip install --retries 25 --timeout 600 -r requirements.txt

# Copy application code
COPY app app
COPY alembic.ini* ./
COPY scripts scripts
RUN chmod +x scripts/*.sh 2>/dev/null || true

# Artifact directory for trained GNN models (also mounted as a named volume)
RUN mkdir -p /app/artifacts/gnn

EXPOSE 8000

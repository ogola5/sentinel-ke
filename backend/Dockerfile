# syntax=docker/dockerfile:1
# =============================================================================
# Sentinel-KE Backend — Production Dockerfile
#
# Build:  DOCKER_BUILDKIT=1 docker compose build
# Run:    docker compose up -d
#
# The BuildKit pip cache mount (--mount=type=cache) caches every downloaded
# wheel on the HOST machine. If a download is interrupted, the next build
# resumes from the cache instead of re-downloading from 0 bytes.
# torch (188 MB) is only fetched from pytorch.org once, ever.
#
# GPU: edit requirements.txt — change --extra-index-url to:
#        https://download.pytorch.org/whl/cu121
# =============================================================================
FROM python:3.12-slim

WORKDIR /app

ENV PYTHONPATH=/app \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

ARG INSTALL_ALL_REQUIREMENTS=0

COPY requirements-runtime.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --timeout 600 --retries 10 -r requirements-runtime.txt

COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    if [ "$INSTALL_ALL_REQUIREMENTS" = "1" ]; then \
      pip install --timeout 3600 --retries 10 -r requirements.txt; \
    fi

# Copy application code
COPY app app
COPY alembic.ini* ./
COPY scripts scripts
RUN chmod +x scripts/*.sh 2>/dev/null || true

# Artifact directory for trained GNN models (also mounted as a named volume)
RUN mkdir -p /app/artifacts/gnn

EXPOSE 8000

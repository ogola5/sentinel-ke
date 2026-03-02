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
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Install dependencies in two steps so a slow torch download doesn't block
# all other packages or blow the socket timeout.
COPY requirements.txt .

# Step 1 — everything except torch (~2 min, all small wheels)
RUN grep -v -E "^(--extra-index-url|torch)" requirements.txt \
      > /tmp/requirements-notorch.txt && \
    pip install --retries 5 --timeout 180 -r /tmp/requirements-notorch.txt

# Step 2 — torch alone with a high timeout (188 MB wheel from pytorch.org)
#           Retries up to 5 times on network drop.
RUN pip install --retries 5 --timeout 3600 \
    --extra-index-url https://download.pytorch.org/whl/cpu \
    torch

# Copy application code
COPY app app
COPY alembic.ini* ./
COPY scripts scripts
RUN chmod +x scripts/*.sh 2>/dev/null || true

# Artifact directory for trained GNN models (also mounted as a named volume)
RUN mkdir -p /app/artifacts/gnn

EXPOSE 8000

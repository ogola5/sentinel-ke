# syntax=docker/dockerfile:1.7
# =============================================================================
# Sentinel-KE Backend Dockerfile
#
# Build strategy (BUILD ONCE):
#   docker compose build  → installs ALL deps into the image layer
#   docker compose up     → volume-mounts ./backend:/app → --reload handles
#                           every Python change without rebuilding
#
# Args:
#   INSTALL_ALL_REQUIREMENTS=1   install requirements.txt (full bundle, default)
#   INSTALL_ML=1                 install torch only (set by notebook service)
#   INSTALL_DEV=1                install dev tools only (no torch)
# =============================================================================
FROM python:3.11-slim

WORKDIR /app

# pip tuning: caching ON, long timeout for torch wheel (~900 MB)
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=600 \
    PIP_RETRIES=25 \
    PIP_NO_CACHE_DIR=0 \
    PYTHONPATH=/app \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Copy requirement files first (Docker layer-cache: only invalidated when
# a requirements file changes, NOT when app code changes)
COPY requirements.txt \
     requirements-runtime.txt \
     requirements-dev.txt \
     requirements-ml.txt \
     ./

ARG INSTALL_ALL_REQUIREMENTS=1
ARG INSTALL_ML=0
ARG INSTALL_DEV=0

# Single RUN keeps layer count low; BuildKit pip cache avoids re-downloading
RUN --mount=type=cache,target=/root/.cache/pip \
    if [ "$INSTALL_ALL_REQUIREMENTS" = "1" ]; then \
        echo "[sentinel] Installing full bundle (requirements.txt)"; \
        pip install --retries 25 --timeout 600 -r requirements.txt; \
    elif [ "$INSTALL_ML" = "1" ]; then \
        echo "[sentinel] Installing runtime + ML (torch)"; \
        pip install --retries 25 --timeout 600 -r requirements-dev.txt; \
        pip install --retries 25 --timeout 600 -r requirements-ml.txt; \
    elif [ "$INSTALL_DEV" = "1" ]; then \
        echo "[sentinel] Installing runtime + dev tools (no torch)"; \
        pip install --retries 25 --timeout 600 -r requirements-dev.txt; \
    else \
        echo "[sentinel] Installing runtime only"; \
        pip install --retries 25 --timeout 600 -r requirements-runtime.txt; \
    fi

# Copy application code AFTER deps so code changes don't bust the pip cache
# (In dev the entire ./backend dir is volume-mounted, so this layer is only
# relevant for production builds)
COPY app app
COPY alembic.ini* ./

# Copy startup scripts (render_startup.sh, render_gnn_worker.sh, etc.)
COPY scripts scripts
RUN chmod +x scripts/*.sh 2>/dev/null || true

# Artifact directory for trained GNN models (also mounted as a named volume)
RUN mkdir -p /app/artifacts/gnn

EXPOSE 8000

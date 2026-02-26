# Sentinel-KE Edge Agent — Dockerfile
# =====================================
# Multi-stage build:
#   Stage 1 (builder): installs Python wheels (including heavy torch stack)
#   Stage 2 (runtime): slim image — copies only installed packages + app code
#
# To build without PyTorch (heuristic mode, ~200 MB smaller):
#   docker build --build-arg INSTALL_TORCH=0 -t sentinel-edge-agent .

ARG PYTHON_VERSION=3.11
ARG INSTALL_TORCH=1

# ---- Stage 1: builder -------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc g++ && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

ARG INSTALL_TORCH
RUN pip install --no-cache-dir --prefix=/install \
        fastapi uvicorn[standard] httpx pydantic pydantic-settings && \
    if [ "$INSTALL_TORCH" = "1" ]; then \
        pip install --no-cache-dir --prefix=/install \
            torch torch-geometric; \
    fi


# ---- Stage 2: runtime -------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS runtime

WORKDIR /agent

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application source
COPY app/ ./app/

# Non-root user for security
RUN useradd -m -u 1001 agentuser && chown -R agentuser /agent
USER agentuser

EXPOSE 8080

# Health-check: hit /status every 30 s
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD python -c "import httpx; r=httpx.get('http://localhost:8080/status'); r.raise_for_status()"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]

# syntax=docker/dockerfile:1.7
FROM python:3.11-slim

WORKDIR /app

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=600 \
    PIP_RETRIES=25 \
    PIP_NO_CACHE_DIR=0

# Heavy ML dependencies are installed in their own cacheable layer.
COPY requirements-ml.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --retries 25 --timeout 600 -r requirements-ml.txt

COPY requirements-runtime.txt .
COPY requirements.txt .
COPY requirements-dev.txt .

ARG INSTALL_DEV=0
RUN --mount=type=cache,target=/root/.cache/pip \
    if [ "$INSTALL_DEV" = "1" ]; then \
        pip install --retries 25 --timeout 600 -r requirements-dev.txt; \
    else \
        pip install --retries 25 --timeout 600 -r requirements-runtime.txt; \
    fi

COPY app app

EXPOSE 8000

# syntax=docker/dockerfile:1.7
FROM python:3.11-slim

WORKDIR /app

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=600 \
    PIP_RETRIES=25 \
    PIP_NO_CACHE_DIR=0

COPY requirements.txt .
COPY requirements-runtime.txt .
COPY requirements-dev.txt .
COPY requirements-ml.txt .

ARG INSTALL_ML=0
ARG INSTALL_DEV=0
ARG INSTALL_ALL_REQUIREMENTS=0

RUN --mount=type=cache,target=/root/.cache/pip \
    if [ "$INSTALL_ALL_REQUIREMENTS" = "1" ]; then \
        echo "Installing full backend dependency bundle from requirements.txt"; \
        pip install --retries 25 --timeout 600 -r requirements.txt; \
    else \
        if [ "$INSTALL_ML" = "1" ]; then \
            pip install --retries 25 --timeout 600 -r requirements-ml.txt; \
        else \
            echo "Skipping ML dependencies (INSTALL_ML=$INSTALL_ML)"; \
        fi; \
        if [ "$INSTALL_DEV" = "1" ]; then \
            pip install --retries 25 --timeout 600 -r requirements-dev.txt; \
        else \
            pip install --retries 25 --timeout 600 -r requirements-runtime.txt; \
        fi; \
    fi

COPY app app

EXPOSE 8000

FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
COPY requirements-dev.txt .

ARG INSTALL_DEV=0
RUN if [ "$INSTALL_DEV" = "1" ]; then \
        pip install --no-cache-dir -r requirements-dev.txt; \
    else \
        pip install --no-cache-dir -r requirements.txt; \
    fi

COPY app app

EXPOSE 8000

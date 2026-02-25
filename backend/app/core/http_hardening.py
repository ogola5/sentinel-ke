from __future__ import annotations

import logging
import time
import uuid

from fastapi import FastAPI, Request

from app.core.config import settings


http_log = logging.getLogger("sentinel.http")

_VALID_REQUEST_ID_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_")


def normalize_request_id(raw: str | None) -> str:
    value = (raw or "").strip()
    if 8 <= len(value) <= 128 and all(ch in _VALID_REQUEST_ID_CHARS for ch in value):
        return value
    return uuid.uuid4().hex


def _apply_security_headers(request: Request, response) -> None:
    if not settings.http_security_headers_enabled:
        return

    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Cache-Control", "no-store")
    response.headers.setdefault("Pragma", "no-cache")
    response.headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
    response.headers.setdefault("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'; base-uri 'none'")

    xfp = (request.headers.get("x-forwarded-proto") or "").lower().strip()
    if request.url.scheme == "https" or xfp == "https":
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")


def install_http_hardening(app: FastAPI) -> None:
    @app.middleware("http")
    async def _request_context_middleware(request: Request, call_next):
        request_id = normalize_request_id(request.headers.get("X-Request-ID"))
        request.state.request_id = request_id

        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            duration_ms = (time.perf_counter() - started) * 1000.0
            http_log.exception(
                "request_failed request_id=%s method=%s path=%s duration_ms=%.3f",
                request_id,
                request.method,
                request.url.path,
                duration_ms,
            )
            raise

        response.headers["X-Request-ID"] = request_id
        _apply_security_headers(request, response)

        if settings.http_request_logging_enabled:
            duration_ms = (time.perf_counter() - started) * 1000.0
            http_log.info(
                "request_complete request_id=%s method=%s path=%s status=%s duration_ms=%.3f",
                request_id,
                request.method,
                request.url.path,
                response.status_code,
                duration_ms,
            )

        return response

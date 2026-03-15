from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


log = logging.getLogger("sentinel.api.error")


def _coerce_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        detail = value.get("detail")
        if isinstance(detail, str):
            return detail
    return "request_failed"


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    return str(value)


def normalize_error_code(*, detail: Any, status_code: int) -> str:
    if isinstance(detail, str):
        code = detail.strip().lower().replace(" ", "_")
        if code:
            return code
    if status_code == 401:
        return "unauthorized"
    if status_code == 403:
        return "forbidden"
    if status_code == 404:
        return "not_found"
    if status_code == 409:
        return "conflict"
    if status_code == 422:
        return "validation_error"
    if status_code >= 500:
        return "internal_error"
    return "request_failed"


def request_id_from_request(request: Request) -> str:
    rid = getattr(getattr(request, "state", object()), "request_id", None)
    if isinstance(rid, str) and rid.strip():
        return rid.strip()
    hdr = request.headers.get("X-Request-ID", "")
    if hdr.strip():
        return hdr.strip()
    return "unknown"


def build_error_payload(
    *,
    request: Request,
    status_code: int,
    detail: Any,
    message: str | None = None,
) -> dict[str, Any]:
    rid = request_id_from_request(request)
    msg = (message or _coerce_text(detail)).strip() or "request_failed"
    code = normalize_error_code(detail=detail, status_code=status_code)
    return {
        "detail": _json_safe(detail),
        "error": {
            "code": code,
            "message": msg,
            "status": int(status_code),
            "request_id": rid,
            "path": request.url.path,
        },
    }


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def _http_exception_handler(request: Request, exc: StarletteHTTPException):
        payload = build_error_payload(
            request=request,
            status_code=exc.status_code,
            detail=exc.detail,
        )
        return JSONResponse(status_code=exc.status_code, content=payload)

    @app.exception_handler(RequestValidationError)
    async def _validation_exception_handler(request: Request, exc: RequestValidationError):
        payload = build_error_payload(
            request=request,
            status_code=422,
            detail=exc.errors(),
            message="validation_error",
        )
        return JSONResponse(status_code=422, content=payload)

    @app.exception_handler(Exception)
    async def _unhandled_exception_handler(request: Request, exc: Exception):
        rid = request_id_from_request(request)
        log.exception(
            "unhandled_exception request_id=%s method=%s path=%s",
            rid,
            request.method,
            request.url.path,
        )
        payload = build_error_payload(
            request=request,
            status_code=500,
            detail="internal_error",
            message="internal_server_error",
        )
        return JSONResponse(status_code=500, content=payload)

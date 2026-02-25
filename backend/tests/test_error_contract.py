from __future__ import annotations

from types import SimpleNamespace

from app.api.error_contract import build_error_payload, normalize_error_code, request_id_from_request


def _request(*, path: str = "/x", request_id: str | None = None, header_rid: str | None = None):
    headers = {}
    if header_rid:
        headers["X-Request-ID"] = header_rid
    return SimpleNamespace(
        state=SimpleNamespace(request_id=request_id),
        headers=headers,
        url=SimpleNamespace(path=path),
        method="GET",
    )


def test_normalize_error_code_uses_http_mappings():
    assert normalize_error_code(detail="ignored", status_code=401) == "ignored"
    assert normalize_error_code(detail={"detail": "x"}, status_code=403) == "forbidden"
    assert normalize_error_code(detail=None, status_code=422) == "validation_error"


def test_request_id_prefers_state_then_header():
    req_state = _request(request_id="state-123", header_rid="header-123")
    assert request_id_from_request(req_state) == "state-123"

    req_header = _request(request_id="", header_rid="header-abc")
    assert request_id_from_request(req_header) == "header-abc"


def test_build_error_payload_contains_legacy_detail_and_structured_error():
    req = _request(path="/v1/auth/login", request_id="rid-1")
    payload = build_error_payload(request=req, status_code=403, detail="insufficient_scope")

    assert payload["detail"] == "insufficient_scope"
    assert payload["error"]["code"] == "insufficient_scope"
    assert payload["error"]["status"] == 403
    assert payload["error"]["request_id"] == "rid-1"
    assert payload["error"]["path"] == "/v1/auth/login"

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.api.deps import (
    AuthPrincipal,
    require_central_access,
    require_request_principal,
    require_step_up,
)
from app.core.config import settings


def _request() -> Request:
    return Request({"type": "http", "method": "GET", "path": "/v1/test", "headers": []})


def test_require_request_principal_accepts_valid_api_key(monkeypatch):
    monkeypatch.setattr(settings, "api_auth_disabled", False)
    monkeypatch.setattr(settings, "api_auth_optional_dev", False)
    monkeypatch.setattr(settings, "frontend_api_key", "frontend-secret")
    monkeypatch.setattr(settings, "ingest_api_key", "")

    principal = require_request_principal(
        request=_request(),
        authorization=None,
        x_api_key="frontend-secret",
        db=object(),
    )
    assert principal.principal_type == "service"
    assert principal.access_level == "central"


def test_require_request_principal_accepts_bearer(monkeypatch):
    monkeypatch.setattr(settings, "api_auth_disabled", False)
    monkeypatch.setattr(settings, "api_auth_optional_dev", False)
    monkeypatch.setattr(settings, "frontend_api_key", "frontend-secret")
    monkeypatch.setattr(settings, "ingest_api_key", "")

    class _Svc:
        def __init__(self, db):
            self.db = db

        def authenticate_access_token(self, *, access_token: str):
            assert access_token == "token-1"
            return {
                "principal_type": "user",
                "actor_id": "u-1",
                "user_id": "u-1",
                "username": "alice",
                "role": "analyst",
                "access_level": "section",
                "section_code": "sec-a",
                "scopes": ["events.read"],
            }

    monkeypatch.setattr("app.api.deps.AuthService", _Svc)

    principal = require_request_principal(
        request=_request(),
        authorization="Bearer token-1",
        x_api_key=None,
        db=object(),
    )
    assert principal.principal_type == "user"
    assert principal.username == "alice"


def test_require_request_principal_prefers_bearer_over_api_key(monkeypatch):
    monkeypatch.setattr(settings, "api_auth_disabled", False)
    monkeypatch.setattr(settings, "api_auth_optional_dev", False)
    monkeypatch.setattr(settings, "frontend_api_key", "frontend-secret")
    monkeypatch.setattr(settings, "ingest_api_key", "")

    class _Svc:
        def __init__(self, db):
            self.db = db

        def authenticate_access_token(self, *, access_token: str):
            return {
                "principal_type": "user",
                "actor_id": "u-1",
                "user_id": "u-1",
                "username": "alice",
                "role": "analyst",
                "access_level": "section",
                "section_code": "sec-a",
                "scopes": ["events.read"],
            }

    monkeypatch.setattr("app.api.deps.AuthService", _Svc)

    principal = require_request_principal(
        request=_request(),
        authorization="Bearer token-1",
        x_api_key="frontend-secret",
        db=object(),
    )
    assert principal.principal_type == "user"
    assert principal.username == "alice"


def test_require_request_principal_accepts_breakglass_when_enabled(monkeypatch):
    monkeypatch.setattr(settings, "api_auth_disabled", False)
    monkeypatch.setattr(settings, "auth_enabled", True)
    monkeypatch.setattr(settings, "frontend_api_key", "frontend-secret")
    monkeypatch.setattr(settings, "ingest_api_key", "")
    monkeypatch.setattr(settings, "auth_breakglass_enabled", True)
    monkeypatch.setattr(settings, "auth_breakglass_allow_in_production", False)
    monkeypatch.setattr(settings, "app_env", "development")
    monkeypatch.setattr(settings, "auth_breakglass_local_only", False)
    monkeypatch.setattr(settings, "auth_breakglass_password", "dev-breakglass-secret")
    monkeypatch.setattr(settings, "auth_breakglass_password_sha3_512", "")
    monkeypatch.setattr(settings, "auth_breakglass_username", "developer")

    principal = require_request_principal(
        request=_request(),
        authorization=None,
        x_api_key=None,
        x_breakglass_password="dev-breakglass-secret",
        db=object(),
    )
    assert principal.principal_type == "breakglass"
    assert principal.username == "developer"
    assert principal.access_level == "central"


def test_require_central_access_rejects_section_user():
    principal = AuthPrincipal(
        principal_type="user",
        actor_id="u-1",
        user_id="u-1",
        username="alice",
        role="analyst",
        access_level="section",
        section_code="sec-a",
        scopes=["events.read"],
    )
    with pytest.raises(HTTPException) as e:
        require_central_access(principal=principal)
    assert e.value.status_code == 403
    assert e.value.detail == "central_access_required"


def test_require_central_access_rejects_service_when_disabled(monkeypatch):
    monkeypatch.setattr(settings, "auth_service_central_access", False)
    principal = AuthPrincipal(
        principal_type="service",
        actor_id="svc-1",
        role="service",
        access_level="central",
        scopes=["*"],
    )
    with pytest.raises(HTTPException) as e:
        require_central_access(principal=principal)
    assert e.value.status_code == 403
    assert e.value.detail == "central_user_session_required"


def test_require_step_up_skips_when_disabled(monkeypatch):
    monkeypatch.setattr(settings, "auth_central_mfa_required", False)
    dep = require_step_up()
    principal = AuthPrincipal(
        principal_type="user",
        actor_id="u-1",
        user_id="u-1",
        username="alice",
        role="central_operator",
        access_level="central",
        section_code=None,
        scopes=["*"],
        mfa_authenticated=False,
        mfa_at=None,
    )
    out = dep(principal=principal)
    assert out is principal


def test_require_step_up_rejects_expired(monkeypatch):
    monkeypatch.setattr(settings, "auth_central_mfa_required", True)
    monkeypatch.setattr(settings, "auth_step_up_minutes", 15)
    dep = require_step_up()
    principal = AuthPrincipal(
        principal_type="user",
        actor_id="u-1",
        user_id="u-1",
        username="alice",
        role="central_operator",
        access_level="central",
        section_code=None,
        scopes=["*"],
        mfa_authenticated=True,
        mfa_at=(datetime.now(timezone.utc) - timedelta(minutes=60)).isoformat(),
    )
    with pytest.raises(HTTPException) as e:
        dep(principal=principal)
    assert e.value.status_code == 403
    assert e.value.detail == "mfa_step_up_expired"

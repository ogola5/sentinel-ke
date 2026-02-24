from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.api.deps import AuthPrincipal, require_central_access, require_request_principal
from app.core.config import settings


def test_require_request_principal_accepts_valid_api_key(monkeypatch):
    monkeypatch.setattr(settings, "api_auth_disabled", False)
    monkeypatch.setattr(settings, "api_auth_optional_dev", False)
    monkeypatch.setattr(settings, "frontend_api_key", "frontend-secret")
    monkeypatch.setattr(settings, "ingest_api_key", "")

    principal = require_request_principal(
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
        authorization="Bearer token-1",
        x_api_key=None,
        db=object(),
    )
    assert principal.principal_type == "user"
    assert principal.username == "alice"


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

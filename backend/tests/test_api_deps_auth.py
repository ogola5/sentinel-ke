from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.api.deps import require_api_key
from app.core.config import settings


def test_require_api_key_allows_when_disabled(monkeypatch):
    monkeypatch.setattr(settings, "api_auth_disabled", True)
    require_api_key(x_api_key=None)


def test_require_api_key_rejects_when_not_configured(monkeypatch):
    monkeypatch.setattr(settings, "api_auth_disabled", False)
    monkeypatch.setattr(settings, "api_auth_optional_dev", False)
    monkeypatch.setattr(settings, "frontend_api_key", "")
    monkeypatch.setattr(settings, "ingest_api_key", "")
    with pytest.raises(HTTPException) as e:
        require_api_key(x_api_key="anything")
    assert e.value.status_code == 503
    assert e.value.detail == "api_auth_not_configured"


def test_require_api_key_rejects_invalid_key(monkeypatch):
    monkeypatch.setattr(settings, "api_auth_disabled", False)
    monkeypatch.setattr(settings, "api_auth_optional_dev", False)
    monkeypatch.setattr(settings, "frontend_api_key", "frontend-secret")
    monkeypatch.setattr(settings, "ingest_api_key", "")
    with pytest.raises(HTTPException) as e:
        require_api_key(x_api_key="wrong")
    assert e.value.status_code == 401
    assert e.value.detail == "invalid_api_key"


def test_require_api_key_accepts_valid_key(monkeypatch):
    monkeypatch.setattr(settings, "api_auth_disabled", False)
    monkeypatch.setattr(settings, "api_auth_optional_dev", False)
    monkeypatch.setattr(settings, "frontend_api_key", "frontend-secret")
    monkeypatch.setattr(settings, "ingest_api_key", "")
    require_api_key(x_api_key="frontend-secret")


import os
from fastapi import Header, HTTPException, Query

from app.core.config import settings
from app.ledger.db import SessionLocal


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _env_bool(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "y", "on")


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """
    Simple API-key guard for all routes.
    - Can be disabled only via API_AUTH_DISABLED=true
    - Expected key: FRONTEND_API_KEY (falls back to INGEST_API_KEY)
    """
    if settings.api_auth_disabled:
        return
    app_env = settings.app_env
    if app_env == "development" and settings.api_auth_optional_dev:
        if not x_api_key:
            return
    expected = settings.frontend_api_key or settings.ingest_api_key
    if not expected:
        raise HTTPException(status_code=503, detail="api_auth_not_configured")
    if not x_api_key or x_api_key != expected:
        raise HTTPException(status_code=401, detail="invalid_api_key")


def pagination_params(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0, le=10_000),
):
    return {"limit": limit, "offset": offset}

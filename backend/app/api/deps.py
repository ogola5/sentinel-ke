import os
from fastapi import Header, HTTPException, Query

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
    - Skips in development if API_AUTH_DISABLED=true
    - Expected key: FRONTEND_API_KEY (falls back to INGEST_API_KEY)
    """
    if _env_bool("API_AUTH_DISABLED", False):
        return
    app_env = os.getenv("APP_ENV", "development").lower()
    if app_env == "development" and _env_bool("API_AUTH_OPTIONAL_DEV", True):
        if not x_api_key:
            return
    expected = os.getenv("FRONTEND_API_KEY") or os.getenv("INGEST_API_KEY") or "dev-secret-key"
    if not x_api_key or x_api_key != expected:
        raise HTTPException(status_code=401, detail="invalid_api_key")


def pagination_params(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0, le=10_000),
):
    return {"limit": limit, "offset": offset}

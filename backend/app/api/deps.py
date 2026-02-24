from __future__ import annotations

from dataclasses import dataclass, field

from fastapi import Depends, Header, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth.service import AuthService
from app.core.config import settings


@dataclass
class AuthPrincipal:
    principal_type: str
    actor_id: str
    user_id: str | None = None
    username: str | None = None
    role: str = "service"
    access_level: str = "central"
    section_code: str | None = None
    scopes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "principal_type": self.principal_type,
            "actor_id": self.actor_id,
            "user_id": self.user_id,
            "username": self.username,
            "role": self.role,
            "access_level": self.access_level,
            "section_code": self.section_code,
            "scopes": list(self.scopes or []),
        }


def get_db():
    from app.ledger.db import SessionLocal

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


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


def _extract_bearer_token(authorization: str | None) -> str | None:
    raw = (authorization or "").strip()
    if not raw:
        return None
    parts = raw.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1].strip():
        raise HTTPException(status_code=401, detail="invalid_authorization_header")
    return parts[1].strip()


def require_request_principal(
    authorization: str | None = Header(default=None, alias="Authorization"),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    db: Session = Depends(get_db),
) -> AuthPrincipal:
    """
    Unified authentication resolver.

    Priority:
    1) Valid static API key (service-to-service)
    2) Bearer access token (user session)
    3) Development optional bypass (if configured)
    """
    if settings.api_auth_disabled:
        return AuthPrincipal(
            principal_type="service",
            actor_id="auth-disabled",
            role="system",
            access_level="central",
            scopes=["*"],
        )
    if not settings.auth_enabled:
        require_api_key(x_api_key=x_api_key)
        return AuthPrincipal(
            principal_type="service",
            actor_id="api-key",
            role="service",
            access_level="central",
            scopes=["*"],
        )

    token: str | None
    try:
        token = _extract_bearer_token(authorization)
    except HTTPException:
        # malformed auth header should not hide a valid API key
        if not x_api_key:
            raise
        token = None

    if x_api_key:
        try:
            require_api_key(x_api_key=x_api_key)
            return AuthPrincipal(
                principal_type="service",
                actor_id="api-key",
                role="service",
                access_level="central",
                scopes=["*"],
            )
        except HTTPException:
            if not token:
                raise

    if token:
        try:
            principal_dict = AuthService(db).authenticate_access_token(access_token=token)
        except ValueError as e:
            raise HTTPException(status_code=401, detail=str(e))
        return AuthPrincipal(
            principal_type=str(principal_dict.get("principal_type") or "user"),
            actor_id=str(principal_dict.get("actor_id") or principal_dict.get("user_id") or "user"),
            user_id=principal_dict.get("user_id"),
            username=principal_dict.get("username"),
            role=str(principal_dict.get("role") or "analyst"),
            access_level=str(principal_dict.get("access_level") or "section"),
            section_code=principal_dict.get("section_code"),
            scopes=list(principal_dict.get("scopes") or []),
        )

    require_api_key(x_api_key=x_api_key)
    return AuthPrincipal(
        principal_type="development",
        actor_id="dev-optional",
        role="developer",
        access_level="central",
        scopes=["*"],
    )


def require_section_access(
    principal: AuthPrincipal = Depends(require_request_principal),
) -> AuthPrincipal:
    if principal.access_level not in {"section", "central"}:
        raise HTTPException(status_code=403, detail="insufficient_access_level")
    return principal


def require_central_access(
    principal: AuthPrincipal = Depends(require_request_principal),
) -> AuthPrincipal:
    if principal.access_level != "central":
        raise HTTPException(status_code=403, detail="central_access_required")
    return principal


def require_scope(required_scope: str):
    def _dependency(
        principal: AuthPrincipal = Depends(require_request_principal),
    ) -> AuthPrincipal:
        scopes = set(principal.scopes or [])
        if "*" in scopes or required_scope in scopes:
            return principal
        raise HTTPException(status_code=403, detail="insufficient_scope")

    return _dependency


def pagination_params(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0, le=10_000),
):
    return {"limit": limit, "offset": offset}

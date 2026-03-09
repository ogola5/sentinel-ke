from __future__ import annotations

import hashlib
import hmac
import ipaddress
import logging
from datetime import datetime, timezone
from dataclasses import dataclass, field

from fastapi import Depends, Header, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.auth.service import AuthService
from app.core.config import settings

log = logging.getLogger("sentinel.auth.deps")


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
    mfa_authenticated: bool = False
    mfa_at: str | None = None

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
            "mfa_authenticated": bool(self.mfa_authenticated),
            "mfa_at": self.mfa_at,
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


def _is_loopback_client(client_host: str | None) -> bool:
    host = (client_host or "").strip()
    if not host:
        return False
    try:
        addr = ipaddress.ip_address(host)
        return bool(addr.is_loopback)
    except ValueError:
        return host in {"localhost"}


def _verify_breakglass_password(candidate: str) -> bool:
    provided = (candidate or "").strip()
    if not provided:
        return False
    expected_hash = (settings.auth_breakglass_password_sha3_512 or "").strip().lower()
    if expected_hash:
        digest = hashlib.sha3_512(provided.encode("utf-8")).hexdigest()
        return hmac.compare_digest(digest.lower(), expected_hash)
    expected_plain = (settings.auth_breakglass_password or "").strip()
    if not expected_plain:
        return False
    return hmac.compare_digest(provided, expected_plain)


def _build_service_principal(*, actor_id: str = "api-key") -> AuthPrincipal:
    return AuthPrincipal(
        principal_type="service",
        actor_id=actor_id,
        role="service",
        access_level="central",
        scopes=["*"],
    )


def _build_breakglass_principal() -> AuthPrincipal:
    now_iso = datetime.now(timezone.utc).isoformat()
    username = (settings.auth_breakglass_username or "dev-breakglass").strip()
    return AuthPrincipal(
        principal_type="breakglass",
        actor_id=f"breakglass:{username}",
        username=username,
        role="admin",
        access_level="central",
        scopes=["*"],
        mfa_authenticated=True,
        mfa_at=now_iso,
    )


def require_request_principal(
    request: Request,
    authorization: str | None = Header(default=None, alias="Authorization"),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    x_breakglass_password: str | None = Header(default=None, alias="X-Breakglass-Password"),
    db: Session = Depends(get_db),
) -> AuthPrincipal:
    """
    Unified authentication resolver.

    Priority:
    1) Bearer access token (user session)
    2) Breakglass header (explicitly enabled, local-only by default)
    3) Valid static API key (service-to-service)
    4) Development optional bypass (if configured)
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
        return _build_service_principal(actor_id="api-key")

    token: str | None
    try:
        token = _extract_bearer_token(authorization)
    except HTTPException:
        # malformed auth header should not hide a valid API key
        if not x_api_key and not x_breakglass_password:
            raise
        token = None

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
            mfa_authenticated=bool(principal_dict.get("mfa_authenticated") is True),
            mfa_at=principal_dict.get("mfa_at"),
        )

    if x_breakglass_password:
        if not settings.auth_breakglass_enabled:
            raise HTTPException(status_code=403, detail="breakglass_not_enabled")
        strict_env = settings.app_env not in {"development", "dev", "local", "test", "testing"}
        if strict_env and not settings.auth_breakglass_allow_in_production:
            raise HTTPException(status_code=403, detail="breakglass_disabled_in_env")
        if settings.auth_breakglass_local_only:
            client_host = request.client.host if request.client else None
            if not _is_loopback_client(client_host):
                raise HTTPException(status_code=403, detail="breakglass_local_only")
        if not _verify_breakglass_password(x_breakglass_password):
            raise HTTPException(status_code=401, detail="invalid_breakglass_password")
        principal = _build_breakglass_principal()
        log.warning(
            "auth_breakglass_used actor_id=%s client_ip=%s path=%s",
            principal.actor_id,
            request.client.host if request.client else None,
            request.url.path,
        )
        return principal

    if x_api_key:
        require_api_key(x_api_key=x_api_key)
        return _build_service_principal(actor_id="api-key")

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
    if principal.access_level == "section" and not (principal.section_code or "").strip():
        raise HTTPException(status_code=403, detail="principal_section_code_missing")
    return principal


def require_central_access(
    principal: AuthPrincipal = Depends(require_request_principal),
) -> AuthPrincipal:
    if principal.access_level != "central":
        raise HTTPException(status_code=403, detail="central_access_required")
    if principal.principal_type in {"service", "development"} and not settings.auth_service_central_access:
        raise HTTPException(status_code=403, detail="central_user_session_required")
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


def require_step_up(max_age_minutes: int | None = None):
    def _dependency(
        principal: AuthPrincipal = Depends(require_central_access),
    ) -> AuthPrincipal:
        if not settings.auth_central_mfa_required:
            return principal
        if principal.principal_type != "user":
            return principal
        if not principal.mfa_authenticated:
            raise HTTPException(status_code=403, detail="mfa_step_up_required")

        raw = (principal.mfa_at or "").strip()
        if not raw:
            raise HTTPException(status_code=403, detail="mfa_step_up_required")
        try:
            mfa_at = datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc)
        except Exception:
            raise HTTPException(status_code=403, detail="mfa_step_up_required")

        age_min = (datetime.now(timezone.utc) - mfa_at).total_seconds() / 60.0
        max_age = int(max_age_minutes if max_age_minutes is not None else settings.auth_step_up_minutes)
        if age_min > max_age:
            raise HTTPException(status_code=403, detail="mfa_step_up_expired")
        return principal

    return _dependency


def pagination_params(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0, le=10_000),
):
    return {"limit": limit, "offset": offset}

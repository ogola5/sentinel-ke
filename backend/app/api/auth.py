from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import (
    AuthPrincipal,
    get_db,
    pagination_params,
    require_central_access,
    require_section_access,
)
from app.auth.schemas import (
    AuthAdminPasswordResetRequest,
    AuthLoginRequest,
    AuthLogoutRequest,
    AuthMfaDisableRequest,
    AuthMfaEnrollVerifyRequest,
    AuthPasswordChangeRequest,
    AuthRefreshRequest,
    AuthUserCreateRequest,
)
from app.auth.service import AuthService
from app.core.rate_limit import limiter


router = APIRouter(prefix="/v1/auth", tags=["auth"])
log = logging.getLogger("sentinel.api.auth")


def _map_auth_error_to_http(detail: str) -> HTTPException:
    if detail in {
        "invalid_credentials",
        "token_signature_invalid",
        "token_payload_invalid",
        "token_type_mismatch",
        "token_issuer_invalid",
        "token_audience_invalid",
        "token_expired",
        "token_not_yet_valid",
        "session_not_found",
        "session_revoked",
        "refresh_token_mismatch",
        "refresh_token_user_mismatch",
        "access_token_mismatch",
        "access_token_expired",
        "access_token_user_mismatch",
        "mfa_code_required",
        "invalid_mfa_code",
    }:
        return HTTPException(status_code=401, detail=detail)
    if detail == "source_temporarily_blocked":
        return HTTPException(status_code=429, detail=detail)
    if detail == "account_locked":
        return HTTPException(status_code=423, detail=detail)
    if detail in {"account_inactive", "client_fingerprint_mismatch", "mfa_enrollment_required"}:
        return HTTPException(status_code=403, detail=detail)
    if detail == "user_not_found":
        return HTTPException(status_code=404, detail=detail)
    if detail == "username_conflict":
        return HTTPException(status_code=409, detail=detail)
    if detail in {
        "mfa_already_enabled",
        "mfa_enrollment_not_started",
        "mfa_secret_missing",
        "mfa_secret_invalid",
        "current_password_required",
    }:
        return HTTPException(status_code=422, detail=detail)
    return HTTPException(status_code=422, detail=detail)


def _extract_bearer(authorization: str | None) -> str | None:
    raw = (authorization or "").strip()
    if not raw:
        return None
    parts = raw.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status_code=401, detail="invalid_authorization_header")
    token = parts[1].strip()
    if not token:
        raise HTTPException(status_code=401, detail="invalid_authorization_header")
    return token


@router.post("/login")
@limiter.limit("10/minute")
def login(
    payload: AuthLoginRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    try:
        return AuthService(db).login(
            payload,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    except ValueError as e:
        raise _map_auth_error_to_http(str(e))
    except Exception:
        log.exception("auth_login_failed")
        raise HTTPException(status_code=500, detail="internal_error")


@router.post("/refresh")
@limiter.limit("20/minute")
def refresh(
    payload: AuthRefreshRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    try:
        return AuthService(db).refresh(
            payload,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    except ValueError as e:
        raise _map_auth_error_to_http(str(e))
    except Exception:
        log.exception("auth_refresh_failed")
        raise HTTPException(status_code=500, detail="internal_error")


@router.post("/logout")
def logout(
    payload: AuthLogoutRequest,
    authorization: str | None = Header(default=None, alias="Authorization"),
    principal: AuthPrincipal = Depends(require_section_access),
    db: Session = Depends(get_db),
):
    del principal
    try:
        access_token = _extract_bearer(authorization)
        return AuthService(db).logout(
            access_token=access_token,
            refresh_token=payload.refresh_token,
            reason="logout",
        )
    except ValueError as e:
        raise _map_auth_error_to_http(str(e))
    except Exception:
        log.exception("auth_logout_failed")
        raise HTTPException(status_code=500, detail="internal_error")


@router.get("/me")
def me(principal: AuthPrincipal = Depends(require_section_access)):
    return principal.as_dict()


@router.post("/users")
def create_user(
    payload: AuthUserCreateRequest,
    principal: AuthPrincipal = Depends(require_central_access),
    db: Session = Depends(get_db),
):
    try:
        return AuthService(db).create_user(payload, actor_id=principal.actor_id)
    except ValueError as e:
        raise _map_auth_error_to_http(str(e))
    except IntegrityError:
        raise HTTPException(status_code=409, detail="username_conflict")
    except Exception:
        log.exception("auth_create_user_failed")
        raise HTTPException(status_code=500, detail="internal_error")


@router.get("/users")
def list_users(
    pagination: dict = Depends(pagination_params),
    include_inactive: bool = Query(default=False),
    access_level: str | None = Query(default=None),
    section_code: str | None = Query(default=None),
    principal: AuthPrincipal = Depends(require_central_access),
    db: Session = Depends(get_db),
):
    del principal
    return AuthService(db).list_users(
        include_inactive=include_inactive,
        access_level=access_level,
        section_code=section_code,
        limit=pagination["limit"],
        offset=pagination["offset"],
    )


@router.post("/password/change")
def change_password(
    payload: AuthPasswordChangeRequest,
    principal: AuthPrincipal = Depends(require_section_access),
    db: Session = Depends(get_db),
):
    if principal.principal_type != "user" or not principal.user_id:
        raise HTTPException(status_code=403, detail="user_session_required")
    try:
        return AuthService(db).change_password(
            user_id=principal.user_id,
            current_password=payload.current_password,
            new_password=payload.new_password,
        )
    except ValueError as e:
        raise _map_auth_error_to_http(str(e))
    except Exception:
        log.exception("auth_change_password_failed")
        raise HTTPException(status_code=500, detail="internal_error")


@router.post("/users/{username}/password/reset")
def admin_reset_password(
    username: str,
    payload: AuthAdminPasswordResetRequest,
    principal: AuthPrincipal = Depends(require_central_access),
    db: Session = Depends(get_db),
):
    try:
        return AuthService(db).admin_reset_password(
            username=username,
            new_password=payload.new_password,
            revoke_existing_sessions=payload.revoke_existing_sessions,
            actor_id=principal.actor_id,
        )
    except ValueError as e:
        raise _map_auth_error_to_http(str(e))
    except Exception:
        log.exception("auth_admin_reset_password_failed")
        raise HTTPException(status_code=500, detail="internal_error")


@router.get("/policies")
def list_role_policies(
    principal: AuthPrincipal = Depends(require_central_access),
    db: Session = Depends(get_db),
):
    del principal
    return AuthService(db).get_role_policies()


@router.post("/mfa/enroll/start")
def mfa_enroll_start(
    principal: AuthPrincipal = Depends(require_section_access),
    db: Session = Depends(get_db),
):
    if principal.principal_type != "user" or not principal.user_id:
        raise HTTPException(status_code=403, detail="user_session_required")
    try:
        return AuthService(db).start_mfa_enrollment(user_id=principal.user_id)
    except ValueError as e:
        raise _map_auth_error_to_http(str(e))
    except Exception:
        log.exception("auth_mfa_enroll_start_failed")
        raise HTTPException(status_code=500, detail="internal_error")


@router.post("/mfa/enroll/verify")
@limiter.limit("10/minute")
def mfa_enroll_verify(
    request: Request,
    payload: AuthMfaEnrollVerifyRequest,
    principal: AuthPrincipal = Depends(require_section_access),
    db: Session = Depends(get_db),
):
    if principal.principal_type != "user" or not principal.user_id:
        raise HTTPException(status_code=403, detail="user_session_required")
    try:
        return AuthService(db).verify_mfa_enrollment(
            user_id=principal.user_id,
            otp_code=payload.otp_code,
        )
    except ValueError as e:
        raise _map_auth_error_to_http(str(e))
    except Exception:
        log.exception("auth_mfa_enroll_verify_failed")
        raise HTTPException(status_code=500, detail="internal_error")


@router.post("/mfa/disable")
def mfa_disable(
    payload: AuthMfaDisableRequest,
    principal: AuthPrincipal = Depends(require_section_access),
    db: Session = Depends(get_db),
):
    if principal.principal_type != "user" or not principal.user_id:
        raise HTTPException(status_code=403, detail="user_session_required")
    try:
        return AuthService(db).disable_mfa(
            user_id=principal.user_id,
            otp_code=payload.otp_code,
            current_password=payload.current_password,
        )
    except ValueError as e:
        raise _map_auth_error_to_http(str(e))
    except Exception:
        log.exception("auth_mfa_disable_failed")
        raise HTTPException(status_code=500, detail="internal_error")

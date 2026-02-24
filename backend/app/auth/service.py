from __future__ import annotations

import logging
import uuid
from datetime import timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import Session

from app.auth.models import AuthLoginEvent, AuthRolePolicy, AuthSession, AuthUser
from app.auth.schemas import AuthLoginRequest, AuthRefreshRequest, AuthUserCreateRequest
from app.auth.security import (
    PASSWORD_KDF,
    SIGNING_ALG,
    build_signed_token,
    fingerprint_digest,
    generate_salt,
    hash_password,
    hash_refresh_token,
    new_token_id,
    normalize_username,
    parse_signed_token,
    utcnow,
    validate_password_strength,
    verify_password,
    verify_token_claims,
)
from app.core.config import settings


log = logging.getLogger("sentinel.auth.service")


DEFAULT_ROLE_POLICIES = [
    {
        "role": "analyst",
        "access_level": "section",
        "allowed_scopes": [
            "events.read",
            "campaigns.read",
            "anomalies.read",
            "mitigations.read",
            "ai.read",
            "metrics.read",
        ],
        "central_only": False,
    },
    {
        "role": "section_commander",
        "access_level": "section",
        "allowed_scopes": [
            "events.read",
            "events.write",
            "campaigns.read",
            "campaigns.write",
            "anomalies.read",
            "mitigations.read",
            "ai.read",
            "ai.feedback.write",
            "metrics.read",
        ],
        "central_only": False,
    },
    {
        "role": "central_operator",
        "access_level": "central",
        "allowed_scopes": [
            "events.read",
            "events.write",
            "campaigns.read",
            "campaigns.write",
            "legal.read",
            "legal.write",
            "economy.read",
            "economy.write",
            "ai.read",
            "ai.feedback.write",
            "ai.rollout.write",
            "intel.read",
            "intel.write",
            "metrics.read",
        ],
        "central_only": True,
    },
    {
        "role": "admin",
        "access_level": "central",
        "allowed_scopes": ["*"],
        "central_only": True,
    },
]


class AuthService:
    def __init__(self, db: Session):
        self.db = db

    def _table_exists(self, table_name: str) -> bool:
        bind = self.db.get_bind()
        if bind is None:
            return False
        insp = sa_inspect(bind)
        return bool(insp.has_table(table_name))

    @staticmethod
    def _normalize_scopes(values: List[str]) -> List[str]:
        out = []
        seen = set()
        for item in values or []:
            x = str(item or "").strip()
            if not x:
                continue
            if x in seen:
                continue
            seen.add(x)
            out.append(x)
        return out

    @staticmethod
    def _effective_allowed(allowed_scopes_json: Any) -> List[str]:
        return AuthService._normalize_scopes(list(allowed_scopes_json or []))

    def _find_role_policy(self, role: str, access_level: str) -> AuthRolePolicy | None:
        return (
            self.db.query(AuthRolePolicy)
            .filter(
                AuthRolePolicy.role == role,
                AuthRolePolicy.access_level == access_level,
            )
            .first()
        )

    def _resolve_policy(self, role: str, access_level: str) -> Dict[str, Any]:
        row = self._find_role_policy(role=role, access_level=access_level)
        if row:
            return {
                "role": row.role,
                "access_level": row.access_level,
                "allowed_scopes": self._effective_allowed(row.allowed_scopes_json),
                "central_only": bool(row.central_only),
            }
        for item in DEFAULT_ROLE_POLICIES:
            if item["role"] == role and item["access_level"] == access_level:
                return {
                    "role": role,
                    "access_level": access_level,
                    "allowed_scopes": list(item["allowed_scopes"]),
                    "central_only": bool(item["central_only"]),
                }
        return {
            "role": role,
            "access_level": access_level,
            "allowed_scopes": [],
            "central_only": access_level == "central",
        }

    def bootstrap_defaults(self) -> Dict[str, Any]:
        if not self._table_exists("auth_role_policy"):
            return {"status": "skipped", "reason": "auth_role_policy_table_missing"}

        created = 0
        for item in DEFAULT_ROLE_POLICIES:
            row = self._find_role_policy(role=item["role"], access_level=item["access_level"])
            if row:
                continue
            self.db.add(
                AuthRolePolicy(
                    role=item["role"],
                    access_level=item["access_level"],
                    allowed_scopes_json=list(item["allowed_scopes"]),
                    central_only=bool(item["central_only"]),
                    metadata_json={"seeded": True},
                )
            )
            created += 1

        admin_created = False
        if self._table_exists("auth_user") and settings.auth_bootstrap_admin_enabled:
            admin_username = normalize_username(settings.auth_bootstrap_admin_username)
            admin_password = (settings.auth_bootstrap_admin_password or "").strip()
            if admin_username and admin_password:
                validate_password_strength(admin_password, min_length=12)
                existing = self.db.query(AuthUser).filter(AuthUser.username == admin_username).first()
                if not existing:
                    salt = generate_salt()
                    self.db.add(
                        AuthUser(
                            username=admin_username,
                            display_name=settings.auth_bootstrap_admin_display_name or "Bootstrap Admin",
                            password_hash=hash_password(
                                admin_password,
                                salt,
                                pepper=settings.auth_password_pepper,
                                iterations=settings.auth_password_iterations,
                            ),
                            password_salt=salt,
                            role="admin",
                            access_level="central",
                            section_code=None,
                            scopes_json=["*"],
                            created_by="bootstrap",
                        )
                    )
                    admin_created = True

        if created or admin_created:
            self.db.commit()

        return {
            "status": "ok",
            "seeded_policies": created,
            "bootstrap_admin_created": admin_created,
        }

    def _log_login(
        self,
        *,
        user: AuthUser | None,
        username: str,
        outcome: str,
        reason: str,
        ip_address: Optional[str],
        user_agent: Optional[str],
    ) -> None:
        self.db.add(
            AuthLoginEvent(
                user_id=getattr(user, "user_id", None),
                username=username,
                outcome=outcome,
                reason=reason,
                ip_address=ip_address,
                user_agent=user_agent,
            )
        )

    def _principal_dict(self, user: AuthUser) -> Dict[str, Any]:
        return {
            "principal_type": "user",
            "actor_id": str(user.user_id),
            "user_id": str(user.user_id),
            "username": user.username,
            "role": user.role,
            "access_level": user.access_level,
            "section_code": user.section_code,
            "scopes": list(user.scopes_json or []),
        }

    def _session_to_tokens(
        self,
        *,
        user: AuthUser,
        session: AuthSession,
    ) -> Dict[str, Any]:
        now = utcnow()
        access_payload = {
            "iss": settings.auth_token_issuer,
            "aud": settings.auth_token_audience,
            "typ": "access",
            "sub": str(user.user_id),
            "sid": str(session.session_id),
            "jti": session.token_id,
            "role": user.role,
            "acl": user.access_level,
            "sec": user.section_code,
            "scp": list(user.scopes_json or []),
            "iat": int(now.timestamp()),
            "nbf": int(now.timestamp()),
            "exp": int(session.access_expires_at.timestamp()),
            "sig_alg": SIGNING_ALG,
            "kdf_alg": PASSWORD_KDF,
        }
        refresh_payload = {
            "iss": settings.auth_token_issuer,
            "aud": settings.auth_token_audience,
            "typ": "refresh",
            "sub": str(user.user_id),
            "sid": str(session.session_id),
            "jti": new_token_id(),
            "iat": int(now.timestamp()),
            "nbf": int(now.timestamp()),
            "exp": int(session.refresh_expires_at.timestamp()),
            "sig_alg": SIGNING_ALG,
            "kdf_alg": PASSWORD_KDF,
            "fph": session.client_fingerprint or "",
        }
        refresh_token = build_signed_token(refresh_payload, settings.auth_token_secret)
        return {
            "token_type": "bearer",
            "access_token": build_signed_token(access_payload, settings.auth_token_secret),
            "refresh_token": refresh_token,
            "access_expires_at": session.access_expires_at.isoformat(),
            "refresh_expires_at": session.refresh_expires_at.isoformat(),
            "principal": self._principal_dict(user),
        }

    def _enforce_scope_rules(
        self,
        *,
        requested_scopes: List[str],
        allowed_scopes: List[str],
    ) -> List[str]:
        requested = self._normalize_scopes(requested_scopes)
        allowed = set(self._normalize_scopes(allowed_scopes))
        if not requested:
            return list(allowed_scopes)
        if "*" in allowed:
            return requested
        if any(scope not in allowed for scope in requested):
            raise ValueError("scope_not_allowed_by_role_policy")
        return requested

    def create_user(self, payload: AuthUserCreateRequest, *, actor_id: str) -> Dict[str, Any]:
        username = normalize_username(payload.username)
        if not username:
            raise ValueError("username_required")
        validate_password_strength(payload.password, min_length=12)

        if self.db.query(AuthUser).filter(AuthUser.username == username).first():
            raise ValueError("username_conflict")

        role = payload.role.strip()
        access_level = payload.access_level
        section_code = (payload.section_code or "").strip() or None
        if access_level == "central":
            section_code = None
        policy = self._resolve_policy(role=role, access_level=access_level)

        if bool(policy.get("central_only")) and access_level != "central":
            raise ValueError("role_requires_central_access")
        if access_level == "section" and not section_code:
            raise ValueError("section_code_required_for_section_access")

        scopes = self._enforce_scope_rules(
            requested_scopes=list(payload.scopes or []),
            allowed_scopes=list(policy.get("allowed_scopes") or []),
        )

        salt = generate_salt()
        row = AuthUser(
            user_id=uuid.uuid4(),
            username=username,
            display_name=(payload.display_name or "").strip() or None,
            password_hash=hash_password(
                payload.password,
                salt,
                pepper=settings.auth_password_pepper,
                iterations=settings.auth_password_iterations,
            ),
            password_salt=salt,
            role=role,
            access_level=access_level,
            section_code=section_code,
            scopes_json=scopes,
            created_by=actor_id,
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return self._user_to_dict(row)

    def list_users(
        self,
        *,
        include_inactive: bool,
        access_level: str | None,
        section_code: str | None,
        limit: int,
        offset: int,
    ) -> Dict[str, Any]:
        q = self.db.query(AuthUser)
        if not include_inactive:
            q = q.filter(AuthUser.is_active.is_(True))
        if access_level:
            q = q.filter(AuthUser.access_level == access_level)
        if section_code:
            q = q.filter(AuthUser.section_code == section_code)
        total = q.count()
        rows = (
            q.order_by(AuthUser.created_at.desc(), AuthUser.username.asc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return {"total": total, "items": [self._user_to_dict(r) for r in rows]}

    def login(
        self,
        payload: AuthLoginRequest,
        *,
        ip_address: str | None,
        user_agent: str | None,
    ) -> Dict[str, Any]:
        username = normalize_username(payload.username)
        user = self.db.query(AuthUser).filter(AuthUser.username == username).first()

        now = utcnow()
        if user is None:
            self._log_login(
                user=None,
                username=username,
                outcome="failed",
                reason="invalid_credentials",
                ip_address=ip_address,
                user_agent=user_agent,
            )
            self.db.commit()
            raise ValueError("invalid_credentials")

        if not bool(user.is_active):
            self._log_login(
                user=user,
                username=username,
                outcome="revoked",
                reason="account_inactive",
                ip_address=ip_address,
                user_agent=user_agent,
            )
            self.db.commit()
            raise ValueError("account_inactive")

        if user.locked_until and user.locked_until > now:
            self._log_login(
                user=user,
                username=username,
                outcome="locked",
                reason="account_locked",
                ip_address=ip_address,
                user_agent=user_agent,
            )
            self.db.commit()
            raise ValueError("account_locked")

        if not verify_password(
            payload.password,
            user.password_salt,
            user.password_hash,
            pepper=settings.auth_password_pepper,
        ):
            user.failed_login_count = int(user.failed_login_count or 0) + 1
            if user.failed_login_count >= settings.auth_login_max_failures:
                user.locked_until = now + timedelta(minutes=settings.auth_lock_minutes)
                reason = "account_locked"
                outcome = "locked"
            else:
                reason = "invalid_credentials"
                outcome = "failed"
            self._log_login(
                user=user,
                username=username,
                outcome=outcome,
                reason=reason,
                ip_address=ip_address,
                user_agent=user_agent,
            )
            self.db.commit()
            raise ValueError(reason if reason == "account_locked" else "invalid_credentials")

        user.failed_login_count = 0
        user.locked_until = None

        access_expires_at = now + timedelta(minutes=settings.auth_access_token_minutes)
        refresh_expires_at = now + timedelta(minutes=settings.auth_refresh_token_minutes)

        session = AuthSession(
            session_id=uuid.uuid4(),
            user_id=user.user_id,
            token_id=new_token_id(),
            refresh_token_hash=hash_refresh_token(new_token_id()),
            issued_at=now,
            access_expires_at=access_expires_at,
            refresh_expires_at=refresh_expires_at,
            client_fingerprint=fingerprint_digest(payload.client_fingerprint),
            metadata_json={
                "sig_alg": SIGNING_ALG,
                "kdf_alg": PASSWORD_KDF,
            },
        )
        self.db.add(session)
        tokens = self._session_to_tokens(user=user, session=session)
        session.refresh_token_hash = hash_refresh_token(tokens["refresh_token"])

        self._log_login(
            user=user,
            username=username,
            outcome="success",
            reason="ok",
            ip_address=ip_address,
            user_agent=user_agent,
        )
        self.db.commit()
        self.db.refresh(session)
        self.db.refresh(user)
        return tokens

    def refresh(
        self,
        payload: AuthRefreshRequest,
        *,
        ip_address: str | None,
        user_agent: str | None,
    ) -> Dict[str, Any]:
        del ip_address, user_agent

        token_payload = parse_signed_token(payload.refresh_token, settings.auth_token_secret)
        verify_token_claims(
            token_payload,
            expected_type="refresh",
            issuer=settings.auth_token_issuer,
            audience=settings.auth_token_audience,
        )

        session_id_raw = str(token_payload.get("sid") or "").strip()
        if not session_id_raw:
            raise ValueError("token_payload_invalid")
        try:
            session_id = uuid.UUID(session_id_raw)
        except ValueError:
            raise ValueError("token_payload_invalid")

        session = self.db.query(AuthSession).filter(AuthSession.session_id == session_id).first()
        if not session:
            raise ValueError("session_not_found")
        token_user_id = str(token_payload.get("sub") or "").strip()
        if token_user_id and str(session.user_id) != token_user_id:
            raise ValueError("refresh_token_user_mismatch")

        now = utcnow()
        if session.revoked_at is not None:
            raise ValueError("session_revoked")
        if session.refresh_expires_at <= now:
            raise ValueError("refresh_token_expired")

        expected_hash = hash_refresh_token(payload.refresh_token)
        if not expected_hash or expected_hash != session.refresh_token_hash:
            raise ValueError("refresh_token_mismatch")

        expected_fp = session.client_fingerprint or ""
        provided_fp = fingerprint_digest(payload.client_fingerprint)
        if expected_fp and expected_fp != provided_fp:
            session.revoked_at = now
            session.revoked_reason = "fingerprint_mismatch"
            self.db.commit()
            raise ValueError("client_fingerprint_mismatch")

        user = self.db.query(AuthUser).filter(AuthUser.user_id == session.user_id).first()
        if not user or not bool(user.is_active):
            session.revoked_at = now
            session.revoked_reason = "user_inactive"
            self.db.commit()
            raise ValueError("account_inactive")

        session.token_id = new_token_id()
        session.issued_at = now
        session.access_expires_at = now + timedelta(minutes=settings.auth_access_token_minutes)
        session.refresh_expires_at = now + timedelta(minutes=settings.auth_refresh_token_minutes)
        tokens = self._session_to_tokens(user=user, session=session)
        session.refresh_token_hash = hash_refresh_token(tokens["refresh_token"])
        self.db.commit()
        self.db.refresh(session)
        return tokens

    def authenticate_access_token(self, *, access_token: str) -> Dict[str, Any]:
        payload = parse_signed_token(access_token, settings.auth_token_secret)
        verify_token_claims(
            payload,
            expected_type="access",
            issuer=settings.auth_token_issuer,
            audience=settings.auth_token_audience,
        )

        session_id_raw = str(payload.get("sid") or "").strip()
        token_id = str(payload.get("jti") or "").strip()
        user_id = str(payload.get("sub") or "").strip()
        if not session_id_raw or not token_id or not user_id:
            raise ValueError("token_payload_invalid")
        try:
            session_id = uuid.UUID(session_id_raw)
        except ValueError:
            raise ValueError("token_payload_invalid")

        session = self.db.query(AuthSession).filter(AuthSession.session_id == session_id).first()
        now = utcnow()
        if not session:
            raise ValueError("session_not_found")
        if session.revoked_at is not None:
            raise ValueError("session_revoked")
        if session.access_expires_at <= now:
            raise ValueError("access_token_expired")
        if session.token_id != token_id:
            raise ValueError("access_token_mismatch")
        if str(session.user_id) != user_id:
            raise ValueError("access_token_user_mismatch")

        user = self.db.query(AuthUser).filter(AuthUser.user_id == session.user_id).first()
        if not user:
            raise ValueError("user_not_found")
        if not bool(user.is_active):
            raise ValueError("account_inactive")

        return self._principal_dict(user)

    def logout(
        self,
        *,
        access_token: str | None = None,
        refresh_token: str | None = None,
        reason: str = "logout",
    ) -> Dict[str, Any]:
        session = None
        now = utcnow()

        if refresh_token:
            payload = parse_signed_token(refresh_token, settings.auth_token_secret)
            session_id_raw = str(payload.get("sid") or "").strip()
            try:
                session_id = uuid.UUID(session_id_raw) if session_id_raw else None
            except ValueError:
                session_id = None
            if session_id:
                session = self.db.query(AuthSession).filter(AuthSession.session_id == session_id).first()

        if session is None and access_token:
            payload = parse_signed_token(access_token, settings.auth_token_secret)
            session_id_raw = str(payload.get("sid") or "").strip()
            token_id = str(payload.get("jti") or "").strip()
            try:
                session_id = uuid.UUID(session_id_raw) if session_id_raw else None
            except ValueError:
                session_id = None
            if session_id:
                q = self.db.query(AuthSession).filter(AuthSession.session_id == session_id)
                if token_id:
                    q = q.filter(AuthSession.token_id == token_id)
                session = q.first()

        if not session:
            return {"status": "no_session"}

        session.revoked_at = now
        session.revoked_reason = reason
        self.db.commit()
        return {"status": "revoked", "session_id": str(session.session_id)}

    def revoke_all_user_sessions(self, *, user_id: str, reason: str) -> int:
        try:
            user_uuid = uuid.UUID(str(user_id))
        except ValueError:
            raise ValueError("user_id_invalid")
        now = utcnow()
        rows = (
            self.db.query(AuthSession)
            .filter(
                AuthSession.user_id == user_uuid,
                AuthSession.revoked_at.is_(None),
            )
            .all()
        )
        for row in rows:
            row.revoked_at = now
            row.revoked_reason = reason
        if rows:
            self.db.commit()
        return len(rows)

    def change_password(self, *, user_id: str, current_password: str, new_password: str) -> Dict[str, Any]:
        try:
            user_uuid = uuid.UUID(str(user_id))
        except ValueError:
            raise ValueError("user_not_found")
        user = self.db.query(AuthUser).filter(AuthUser.user_id == user_uuid).first()
        if not user:
            raise ValueError("user_not_found")
        validate_password_strength(new_password, min_length=12)
        if not verify_password(
            current_password,
            user.password_salt,
            user.password_hash,
            pepper=settings.auth_password_pepper,
        ):
            raise ValueError("invalid_credentials")

        salt = generate_salt()
        user.password_salt = salt
        user.password_hash = hash_password(
            new_password,
            salt,
            pepper=settings.auth_password_pepper,
            iterations=settings.auth_password_iterations,
        )
        user.password_changed_at = utcnow()
        self.db.commit()
        revoked = self.revoke_all_user_sessions(user_id=str(user.user_id), reason="password_changed")
        return {"status": "ok", "revoked_sessions": revoked}

    def admin_reset_password(
        self,
        *,
        username: str,
        new_password: str,
        revoke_existing_sessions: bool,
        actor_id: str,
    ) -> Dict[str, Any]:
        row = self.db.query(AuthUser).filter(AuthUser.username == normalize_username(username)).first()
        if not row:
            raise ValueError("user_not_found")
        validate_password_strength(new_password, min_length=12)

        salt = generate_salt()
        row.password_salt = salt
        row.password_hash = hash_password(
            new_password,
            salt,
            pepper=settings.auth_password_pepper,
            iterations=settings.auth_password_iterations,
        )
        row.password_changed_at = utcnow()
        row.updated_at = utcnow()
        self.db.commit()

        revoked = 0
        if revoke_existing_sessions:
            revoked = self.revoke_all_user_sessions(user_id=str(row.user_id), reason="admin_password_reset")

        return {"status": "ok", "username": row.username, "revoked_sessions": revoked}

    def _user_to_dict(self, row: AuthUser) -> Dict[str, Any]:
        return {
            "user_id": str(row.user_id),
            "username": row.username,
            "display_name": row.display_name,
            "role": row.role,
            "access_level": row.access_level,
            "section_code": row.section_code,
            "scopes": list(row.scopes_json or []),
            "is_active": bool(row.is_active),
            "failed_login_count": int(row.failed_login_count or 0),
            "locked_until": row.locked_until.isoformat() if row.locked_until else None,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }

    def get_role_policies(self) -> Dict[str, Any]:
        rows = (
            self.db.query(AuthRolePolicy)
            .order_by(AuthRolePolicy.role.asc(), AuthRolePolicy.access_level.asc())
            .all()
        )
        return {
            "items": [
                {
                    "policy_id": str(x.policy_id),
                    "role": x.role,
                    "access_level": x.access_level,
                    "allowed_scopes": list(x.allowed_scopes_json or []),
                    "central_only": bool(x.central_only),
                    "created_at": x.created_at.isoformat() if x.created_at else None,
                }
                for x in rows
            ]
        }

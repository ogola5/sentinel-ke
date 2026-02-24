from __future__ import annotations

import uuid
from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.db.base import Base, utcnow


class AuthUser(Base):
    __tablename__ = "auth_user"

    user_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username = Column(String, nullable=False, unique=True)
    display_name = Column(String, nullable=True)
    password_hash = Column(String, nullable=False)
    password_salt = Column(String, nullable=False)

    role = Column(String, nullable=False, default="analyst")
    access_level = Column(String, nullable=False, default="section")  # section | central
    section_code = Column(String, nullable=True)
    scopes_json = Column(JSONB, nullable=False, default=list)

    is_active = Column(Boolean, nullable=False, default=True)
    failed_login_count = Column(Integer, nullable=False, default=0)
    locked_until = Column(DateTime(timezone=True), nullable=True)
    password_changed_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    created_by = Column(String, nullable=False, default="system")
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    __table_args__ = (
        CheckConstraint("access_level IN ('section','central')", name="ck_auth_user_access_level"),
        Index("ix_auth_user_access_level", "access_level"),
        Index("ix_auth_user_section_code", "section_code"),
        Index("ix_auth_user_active", "is_active"),
    )


class AuthSession(Base):
    __tablename__ = "auth_session"

    session_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("auth_user.user_id", ondelete="CASCADE"),
        nullable=False,
    )

    token_id = Column(String, nullable=False, unique=True)  # JWT-like jti
    refresh_token_hash = Column(String, nullable=False, unique=True)

    issued_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    access_expires_at = Column(DateTime(timezone=True), nullable=False)
    refresh_expires_at = Column(DateTime(timezone=True), nullable=False)

    client_fingerprint = Column(String, nullable=True)
    metadata_json = Column(JSONB, nullable=False, default=dict)

    revoked_at = Column(DateTime(timezone=True), nullable=True)
    revoked_reason = Column(String, nullable=True)

    __table_args__ = (
        Index("ix_auth_session_user", "user_id"),
        Index("ix_auth_session_access_exp", "access_expires_at"),
        Index("ix_auth_session_refresh_exp", "refresh_expires_at"),
    )


class AuthLoginEvent(Base):
    __tablename__ = "auth_login_event"

    event_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("auth_user.user_id", ondelete="SET NULL"), nullable=True)
    username = Column(String, nullable=False)
    outcome = Column(String, nullable=False)  # success|failed|locked|revoked
    ip_address = Column(String, nullable=True)
    user_agent = Column(String, nullable=True)
    reason = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    __table_args__ = (
        Index("ix_auth_login_event_username", "username"),
        Index("ix_auth_login_event_created", "created_at"),
        Index("ix_auth_login_event_outcome", "outcome"),
    )


class AuthRolePolicy(Base):
    __tablename__ = "auth_role_policy"

    policy_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    role = Column(String, nullable=False)
    access_level = Column(String, nullable=False, default="section")
    allowed_scopes_json = Column(JSONB, nullable=False, default=list)
    central_only = Column(Boolean, nullable=False, default=False)
    metadata_json = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    __table_args__ = (
        CheckConstraint("access_level IN ('section','central')", name="ck_auth_role_policy_access_level"),
        UniqueConstraint("role", "access_level", name="uq_auth_role_policy"),
        Index("ix_auth_role_policy_role", "role"),
    )

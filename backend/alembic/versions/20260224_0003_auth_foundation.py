"""add auth login/session/rbac tables

Revision ID: 20260224_0003
Revises: 20260224_0002
Create Date: 2026-02-24 18:00:00
"""

from __future__ import annotations

import uuid

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "20260224_0003"
down_revision = "20260224_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "auth_user",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("username", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=True),
        sa.Column("password_hash", sa.String(), nullable=False),
        sa.Column("password_salt", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=False, server_default="analyst"),
        sa.Column("access_level", sa.String(), nullable=False, server_default="section"),
        sa.Column("section_code", sa.String(), nullable=True),
        sa.Column(
            "scopes_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("failed_login_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("created_by", sa.String(), nullable=False, server_default="system"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("user_id"),
        sa.CheckConstraint("access_level IN ('section','central')", name="ck_auth_user_access_level"),
        sa.UniqueConstraint("username"),
    )
    op.create_index("ix_auth_user_access_level", "auth_user", ["access_level"], unique=False)
    op.create_index("ix_auth_user_section_code", "auth_user", ["section_code"], unique=False)
    op.create_index("ix_auth_user_active", "auth_user", ["is_active"], unique=False)

    op.create_table(
        "auth_session",
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_id", sa.String(), nullable=False),
        sa.Column("refresh_token_hash", sa.String(), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("access_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("refresh_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("client_fingerprint", sa.String(), nullable=True),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_reason", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["auth_user.user_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("session_id"),
        sa.UniqueConstraint("token_id"),
        sa.UniqueConstraint("refresh_token_hash"),
    )
    op.create_index("ix_auth_session_user", "auth_session", ["user_id"], unique=False)
    op.create_index("ix_auth_session_access_exp", "auth_session", ["access_expires_at"], unique=False)
    op.create_index("ix_auth_session_refresh_exp", "auth_session", ["refresh_expires_at"], unique=False)

    op.create_table(
        "auth_login_event",
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("username", sa.String(), nullable=False),
        sa.Column("outcome", sa.String(), nullable=False),
        sa.Column("ip_address", sa.String(), nullable=True),
        sa.Column("user_agent", sa.String(), nullable=True),
        sa.Column("reason", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["user_id"], ["auth_user.user_id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("event_id"),
    )
    op.create_index("ix_auth_login_event_username", "auth_login_event", ["username"], unique=False)
    op.create_index("ix_auth_login_event_created", "auth_login_event", ["created_at"], unique=False)
    op.create_index("ix_auth_login_event_outcome", "auth_login_event", ["outcome"], unique=False)

    op.create_table(
        "auth_role_policy",
        sa.Column("policy_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("access_level", sa.String(), nullable=False, server_default="section"),
        sa.Column(
            "allowed_scopes_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("central_only", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("policy_id"),
        sa.CheckConstraint("access_level IN ('section','central')", name="ck_auth_role_policy_access_level"),
        sa.UniqueConstraint("role", "access_level", name="uq_auth_role_policy"),
    )
    op.create_index("ix_auth_role_policy_role", "auth_role_policy", ["role"], unique=False)

    policy_table = sa.table(
        "auth_role_policy",
        sa.column("policy_id", postgresql.UUID(as_uuid=True)),
        sa.column("role", sa.String()),
        sa.column("access_level", sa.String()),
        sa.column("allowed_scopes_json", postgresql.JSONB(astext_type=sa.Text())),
        sa.column("central_only", sa.Boolean()),
        sa.column("metadata_json", postgresql.JSONB(astext_type=sa.Text())),
    )
    op.bulk_insert(
        policy_table,
        [
            {
                "policy_id": uuid.uuid4(),
                "role": "analyst",
                "access_level": "section",
                "allowed_scopes_json": [
                    "events.read",
                    "campaigns.read",
                    "anomalies.read",
                    "mitigations.read",
                    "ai.read",
                    "metrics.read",
                ],
                "central_only": False,
                "metadata_json": {"seeded": True},
            },
            {
                "policy_id": uuid.uuid4(),
                "role": "section_commander",
                "access_level": "section",
                "allowed_scopes_json": [
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
                "metadata_json": {"seeded": True},
            },
            {
                "policy_id": uuid.uuid4(),
                "role": "central_operator",
                "access_level": "central",
                "allowed_scopes_json": [
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
                "metadata_json": {"seeded": True},
            },
            {
                "policy_id": uuid.uuid4(),
                "role": "admin",
                "access_level": "central",
                "allowed_scopes_json": ["*"],
                "central_only": True,
                "metadata_json": {"seeded": True},
            },
        ],
    )


def downgrade() -> None:
    op.drop_index("ix_auth_role_policy_role", table_name="auth_role_policy")
    op.drop_table("auth_role_policy")

    op.drop_index("ix_auth_login_event_outcome", table_name="auth_login_event")
    op.drop_index("ix_auth_login_event_created", table_name="auth_login_event")
    op.drop_index("ix_auth_login_event_username", table_name="auth_login_event")
    op.drop_table("auth_login_event")

    op.drop_index("ix_auth_session_refresh_exp", table_name="auth_session")
    op.drop_index("ix_auth_session_access_exp", table_name="auth_session")
    op.drop_index("ix_auth_session_user", table_name="auth_session")
    op.drop_table("auth_session")

    op.drop_index("ix_auth_user_active", table_name="auth_user")
    op.drop_index("ix_auth_user_section_code", table_name="auth_user")
    op.drop_index("ix_auth_user_access_level", table_name="auth_user")
    op.drop_table("auth_user")

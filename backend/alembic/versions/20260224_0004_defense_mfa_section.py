"""add section tenancy, mfa columns, threat alerts, and defense tables

Revision ID: 20260224_0004
Revises: 20260224_0003
Create Date: 2026-02-24 23:30:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "20260224_0004"
down_revision = "20260224_0003"
branch_labels = None
depends_on = None


def _has_table(insp: sa.Inspector, table_name: str) -> bool:
    return bool(insp.has_table(table_name))


def _has_column(insp: sa.Inspector, table_name: str, column_name: str) -> bool:
    if not _has_table(insp, table_name):
        return False
    return column_name in {c["name"] for c in insp.get_columns(table_name)}


def _has_index(insp: sa.Inspector, table_name: str, index_name: str) -> bool:
    if not _has_table(insp, table_name):
        return False
    return any(ix.get("name") == index_name for ix in insp.get_indexes(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    # Section tenancy on source/event/audit paths.
    if _has_table(insp, "source_registry") and not _has_column(insp, "source_registry", "section_code"):
        op.add_column("source_registry", sa.Column("section_code", sa.String(), nullable=True))

    if _has_table(insp, "event_log") and not _has_column(insp, "event_log", "section_code"):
        op.add_column("event_log", sa.Column("section_code", sa.String(), nullable=True))
    if _has_table(insp, "event_log") and not _has_index(insp, "event_log", "ix_event_log_section"):
        op.create_index("ix_event_log_section", "event_log", ["section_code"], unique=False)

    if _has_table(insp, "audit_log") and not _has_column(insp, "audit_log", "section_code"):
        op.add_column("audit_log", sa.Column("section_code", sa.String(), nullable=True))

    if _has_table(insp, "source") and not _has_column(insp, "source", "section_code"):
        op.add_column("source", sa.Column("section_code", sa.String(), nullable=True))

    # MFA fields on auth_user.
    if _has_table(insp, "auth_user") and not _has_column(insp, "auth_user", "mfa_enabled"):
        op.add_column(
            "auth_user",
            sa.Column("mfa_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        )
    if _has_table(insp, "auth_user") and not _has_column(insp, "auth_user", "mfa_secret_enc"):
        op.add_column("auth_user", sa.Column("mfa_secret_enc", sa.String(), nullable=True))
    if _has_table(insp, "auth_user") and not _has_column(insp, "auth_user", "mfa_pending_secret_enc"):
        op.add_column("auth_user", sa.Column("mfa_pending_secret_enc", sa.String(), nullable=True))
    if _has_table(insp, "auth_user") and not _has_column(insp, "auth_user", "mfa_enrolled_at"):
        op.add_column("auth_user", sa.Column("mfa_enrolled_at", sa.DateTime(timezone=True), nullable=True))

    # Align seeded role policies with scope requirements used by routers.
    if _has_table(insp, "auth_role_policy"):
        policy_table = sa.table(
            "auth_role_policy",
            sa.column("role", sa.String()),
            sa.column("access_level", sa.String()),
            sa.column("allowed_scopes_json", postgresql.JSONB(astext_type=sa.Text())),
        )
        targets = [
            (
                "analyst",
                "section",
                [
                    "events.read",
                    "campaigns.read",
                    "ddos.read",
                    "infra.read",
                    "cases.read",
                    "intel.read",
                    "anomalies.read",
                    "mitigations.read",
                    "ai.read",
                    "metrics.read",
                    "defense.read",
                ],
            ),
            (
                "section_commander",
                "section",
                [
                    "events.read",
                    "events.write",
                    "campaigns.read",
                    "campaigns.write",
                    "ddos.read",
                    "infra.read",
                    "cases.read",
                    "intel.read",
                    "anomalies.read",
                    "mitigations.read",
                    "ai.read",
                    "ai.feedback.write",
                    "integrations.write",
                    "metrics.read",
                    "defense.read",
                    "defense.write",
                ],
            ),
            (
                "central_operator",
                "central",
                [
                    "events.read",
                    "events.write",
                    "graph.read",
                    "campaigns.read",
                    "campaigns.write",
                    "ddos.read",
                    "infra.read",
                    "cases.read",
                    "intel.read",
                    "anomalies.read",
                    "mitigations.read",
                    "legal.read",
                    "legal.write",
                    "economy.read",
                    "economy.write",
                    "ai.read",
                    "ai.feedback.write",
                    "ai.rollout.write",
                    "integrations.write",
                    "metrics.read",
                    "defense.read",
                    "defense.write",
                ],
            ),
        ]
        for role, access_level, scopes in targets:
            op.execute(
                policy_table.update()
                .where(policy_table.c.role == role)
                .where(policy_table.c.access_level == access_level)
                .values(allowed_scopes_json=scopes)
            )

    # Threat alert table.
    if not _has_table(insp, "threat_alert"):
        op.create_table(
            "threat_alert",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("alert_type", sa.String(), nullable=False),
            sa.Column("section_code", sa.String(), nullable=True),
            sa.Column("entity_key", sa.String(), nullable=False),
            sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
            sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
            sa.Column("score", sa.Float(), nullable=False, server_default="0"),
            sa.Column("severity", sa.String(), nullable=False, server_default="low"),
            sa.Column(
                "reason_codes",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'[]'::jsonb"),
            ),
            sa.Column(
                "indicators",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
            sa.Column(
                "recommended_actions",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'[]'::jsonb"),
            ),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("alert_type", "section_code", "entity_key", "window_end", name="uq_threat_alert_window"),
        )
        op.create_index("ix_threat_alert_created", "threat_alert", ["created_at"], unique=False)
        op.create_index("ix_threat_alert_type", "threat_alert", ["alert_type"], unique=False)
        op.create_index("ix_threat_alert_severity", "threat_alert", ["severity"], unique=False)
        op.create_index("ix_threat_alert_section", "threat_alert", ["section_code"], unique=False)

    # Defense-domain tables.
    if not _has_table(insp, "vulnerability_finding"):
        op.create_table(
            "vulnerability_finding",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("section_code", sa.String(), nullable=True),
            sa.Column("asset_id", sa.String(), nullable=False),
            sa.Column("cve_id", sa.String(), nullable=False),
            sa.Column("source", sa.String(), nullable=False, server_default="kev"),
            sa.Column("severity", sa.String(), nullable=False, server_default="medium"),
            sa.Column("epss", sa.Float(), nullable=True),
            sa.Column("kev", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("status", sa.String(), nullable=False, server_default="open"),
            sa.Column("discovered_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("patched_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("risk_score", sa.Float(), nullable=False, server_default="0"),
            sa.Column(
                "metadata_json",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("section_code", "asset_id", "cve_id", "source", name="uq_vulnerability_asset_cve"),
        )
        op.create_index("ix_vulnerability_section", "vulnerability_finding", ["section_code"], unique=False)
        op.create_index("ix_vulnerability_status", "vulnerability_finding", ["status"], unique=False)
        op.create_index("ix_vulnerability_due", "vulnerability_finding", ["due_at"], unique=False)
        op.create_index("ix_vulnerability_cve", "vulnerability_finding", ["cve_id"], unique=False)

    if not _has_table(insp, "patch_sla_decision"):
        op.create_table(
            "patch_sla_decision",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("finding_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("section_code", sa.String(), nullable=True),
            sa.Column("decision_status", sa.String(), nullable=False),
            sa.Column("score", sa.Float(), nullable=False, server_default="0"),
            sa.Column(
                "reason_codes",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'[]'::jsonb"),
            ),
            sa.Column(
                "evidence_json",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
            sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.ForeignKeyConstraint(["finding_id"], ["vulnerability_finding.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("finding_id", name="uq_patch_sla_finding"),
        )
        op.create_index("ix_patch_sla_section", "patch_sla_decision", ["section_code"], unique=False)
        op.create_index("ix_patch_sla_status", "patch_sla_decision", ["decision_status"], unique=False)
        op.create_index("ix_patch_sla_score", "patch_sla_decision", ["score"], unique=False)

    if not _has_table(insp, "backup_attestation"):
        op.create_table(
            "backup_attestation",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("section_code", sa.String(), nullable=True),
            sa.Column("asset_id", sa.String(), nullable=False),
            sa.Column("backup_id", sa.String(), nullable=False),
            sa.Column("immutable", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("object_lock_until", sa.DateTime(timezone=True), nullable=True),
            sa.Column("backup_hash", sa.String(), nullable=True),
            sa.Column("storage_tier", sa.String(), nullable=True),
            sa.Column("status", sa.String(), nullable=False, server_default="unknown"),
            sa.Column("rpo_hours", sa.Float(), nullable=True),
            sa.Column("attested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column(
                "evidence_json",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("section_code", "asset_id", "backup_id", name="uq_backup_attestation_asset_backup"),
        )
        op.create_index("ix_backup_attestation_section", "backup_attestation", ["section_code"], unique=False)
        op.create_index("ix_backup_attestation_asset", "backup_attestation", ["asset_id"], unique=False)
        op.create_index("ix_backup_attestation_status", "backup_attestation", ["status"], unique=False)

    if not _has_table(insp, "restore_drill"):
        op.create_table(
            "restore_drill",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("section_code", sa.String(), nullable=True),
            sa.Column("asset_id", sa.String(), nullable=False),
            sa.Column("backup_id", sa.String(), nullable=False),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("success", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("rto_target_minutes", sa.Integer(), nullable=False, server_default="240"),
            sa.Column("rto_actual_minutes", sa.Float(), nullable=True),
            sa.Column("operator_id", sa.String(), nullable=False),
            sa.Column("notes", sa.String(), nullable=True),
            sa.Column(
                "evidence_json",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_restore_drill_section", "restore_drill", ["section_code"], unique=False)
        op.create_index("ix_restore_drill_asset", "restore_drill", ["asset_id"], unique=False)
        op.create_index("ix_restore_drill_success", "restore_drill", ["success"], unique=False)
        op.create_index("ix_restore_drill_created", "restore_drill", ["created_at"], unique=False)

    if not _has_table(insp, "incident_playbook_run"):
        op.create_table(
            "incident_playbook_run",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("incident_key", sa.String(), nullable=False),
            sa.Column("section_code", sa.String(), nullable=True),
            sa.Column("severity", sa.String(), nullable=False, server_default="medium"),
            sa.Column("status", sa.String(), nullable=False, server_default="running"),
            sa.Column("created_by", sa.String(), nullable=False),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "metadata_json",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_ir_run_incident", "incident_playbook_run", ["incident_key"], unique=False)
        op.create_index("ix_ir_run_section", "incident_playbook_run", ["section_code"], unique=False)
        op.create_index("ix_ir_run_status", "incident_playbook_run", ["status"], unique=False)

    if not _has_table(insp, "containment_action"):
        op.create_table(
            "containment_action",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("section_code", sa.String(), nullable=True),
            sa.Column("action_type", sa.String(), nullable=False),
            sa.Column("target", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False, server_default="queued"),
            sa.Column("executed_by", sa.String(), nullable=False),
            sa.Column("executed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column(
                "details_json",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.ForeignKeyConstraint(["run_id"], ["incident_playbook_run.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_containment_run", "containment_action", ["run_id"], unique=False)
        op.create_index("ix_containment_section", "containment_action", ["section_code"], unique=False)
        op.create_index("ix_containment_action_type", "containment_action", ["action_type"], unique=False)
        op.create_index("ix_containment_status", "containment_action", ["status"], unique=False)

    if not _has_table(insp, "crypto_posture_snapshot"):
        op.create_table(
            "crypto_posture_snapshot",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("section_code", sa.String(), nullable=True),
            sa.Column("taken_by", sa.String(), nullable=False),
            sa.Column("tls_mode", sa.String(), nullable=False),
            sa.Column("pqc_mode", sa.String(), nullable=False),
            sa.Column("kms_provider", sa.String(), nullable=False),
            sa.Column("signing_alg", sa.String(), nullable=False),
            sa.Column("password_kdf", sa.String(), nullable=False),
            sa.Column("key_rotation_days", sa.Integer(), nullable=False, server_default="90"),
            sa.Column("compliant", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column(
                "details_json",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_crypto_posture_created", "crypto_posture_snapshot", ["created_at"], unique=False)
        op.create_index("ix_crypto_posture_compliant", "crypto_posture_snapshot", ["compliant"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if _has_table(insp, "crypto_posture_snapshot"):
        if _has_index(insp, "crypto_posture_snapshot", "ix_crypto_posture_compliant"):
            op.drop_index("ix_crypto_posture_compliant", table_name="crypto_posture_snapshot")
        if _has_index(insp, "crypto_posture_snapshot", "ix_crypto_posture_created"):
            op.drop_index("ix_crypto_posture_created", table_name="crypto_posture_snapshot")
        op.drop_table("crypto_posture_snapshot")

    if _has_table(insp, "containment_action"):
        if _has_index(insp, "containment_action", "ix_containment_status"):
            op.drop_index("ix_containment_status", table_name="containment_action")
        if _has_index(insp, "containment_action", "ix_containment_action_type"):
            op.drop_index("ix_containment_action_type", table_name="containment_action")
        if _has_index(insp, "containment_action", "ix_containment_section"):
            op.drop_index("ix_containment_section", table_name="containment_action")
        if _has_index(insp, "containment_action", "ix_containment_run"):
            op.drop_index("ix_containment_run", table_name="containment_action")
        op.drop_table("containment_action")

    if _has_table(insp, "incident_playbook_run"):
        if _has_index(insp, "incident_playbook_run", "ix_ir_run_status"):
            op.drop_index("ix_ir_run_status", table_name="incident_playbook_run")
        if _has_index(insp, "incident_playbook_run", "ix_ir_run_section"):
            op.drop_index("ix_ir_run_section", table_name="incident_playbook_run")
        if _has_index(insp, "incident_playbook_run", "ix_ir_run_incident"):
            op.drop_index("ix_ir_run_incident", table_name="incident_playbook_run")
        op.drop_table("incident_playbook_run")

    if _has_table(insp, "restore_drill"):
        if _has_index(insp, "restore_drill", "ix_restore_drill_created"):
            op.drop_index("ix_restore_drill_created", table_name="restore_drill")
        if _has_index(insp, "restore_drill", "ix_restore_drill_success"):
            op.drop_index("ix_restore_drill_success", table_name="restore_drill")
        if _has_index(insp, "restore_drill", "ix_restore_drill_asset"):
            op.drop_index("ix_restore_drill_asset", table_name="restore_drill")
        if _has_index(insp, "restore_drill", "ix_restore_drill_section"):
            op.drop_index("ix_restore_drill_section", table_name="restore_drill")
        op.drop_table("restore_drill")

    if _has_table(insp, "backup_attestation"):
        if _has_index(insp, "backup_attestation", "ix_backup_attestation_status"):
            op.drop_index("ix_backup_attestation_status", table_name="backup_attestation")
        if _has_index(insp, "backup_attestation", "ix_backup_attestation_asset"):
            op.drop_index("ix_backup_attestation_asset", table_name="backup_attestation")
        if _has_index(insp, "backup_attestation", "ix_backup_attestation_section"):
            op.drop_index("ix_backup_attestation_section", table_name="backup_attestation")
        op.drop_table("backup_attestation")

    if _has_table(insp, "patch_sla_decision"):
        if _has_index(insp, "patch_sla_decision", "ix_patch_sla_score"):
            op.drop_index("ix_patch_sla_score", table_name="patch_sla_decision")
        if _has_index(insp, "patch_sla_decision", "ix_patch_sla_status"):
            op.drop_index("ix_patch_sla_status", table_name="patch_sla_decision")
        if _has_index(insp, "patch_sla_decision", "ix_patch_sla_section"):
            op.drop_index("ix_patch_sla_section", table_name="patch_sla_decision")
        op.drop_table("patch_sla_decision")

    if _has_table(insp, "vulnerability_finding"):
        if _has_index(insp, "vulnerability_finding", "ix_vulnerability_cve"):
            op.drop_index("ix_vulnerability_cve", table_name="vulnerability_finding")
        if _has_index(insp, "vulnerability_finding", "ix_vulnerability_due"):
            op.drop_index("ix_vulnerability_due", table_name="vulnerability_finding")
        if _has_index(insp, "vulnerability_finding", "ix_vulnerability_status"):
            op.drop_index("ix_vulnerability_status", table_name="vulnerability_finding")
        if _has_index(insp, "vulnerability_finding", "ix_vulnerability_section"):
            op.drop_index("ix_vulnerability_section", table_name="vulnerability_finding")
        op.drop_table("vulnerability_finding")

    if _has_table(insp, "threat_alert"):
        if _has_index(insp, "threat_alert", "ix_threat_alert_section"):
            op.drop_index("ix_threat_alert_section", table_name="threat_alert")
        if _has_index(insp, "threat_alert", "ix_threat_alert_severity"):
            op.drop_index("ix_threat_alert_severity", table_name="threat_alert")
        if _has_index(insp, "threat_alert", "ix_threat_alert_type"):
            op.drop_index("ix_threat_alert_type", table_name="threat_alert")
        if _has_index(insp, "threat_alert", "ix_threat_alert_created"):
            op.drop_index("ix_threat_alert_created", table_name="threat_alert")
        op.drop_table("threat_alert")

    if _has_table(insp, "auth_user"):
        if _has_column(insp, "auth_user", "mfa_enrolled_at"):
            op.drop_column("auth_user", "mfa_enrolled_at")
        if _has_column(insp, "auth_user", "mfa_pending_secret_enc"):
            op.drop_column("auth_user", "mfa_pending_secret_enc")
        if _has_column(insp, "auth_user", "mfa_secret_enc"):
            op.drop_column("auth_user", "mfa_secret_enc")
        if _has_column(insp, "auth_user", "mfa_enabled"):
            op.drop_column("auth_user", "mfa_enabled")

    if _has_table(insp, "source") and _has_column(insp, "source", "section_code"):
        op.drop_column("source", "section_code")

    if _has_table(insp, "audit_log") and _has_column(insp, "audit_log", "section_code"):
        op.drop_column("audit_log", "section_code")

    if _has_table(insp, "event_log"):
        if _has_index(insp, "event_log", "ix_event_log_section"):
            op.drop_index("ix_event_log_section", table_name="event_log")
        if _has_column(insp, "event_log", "section_code"):
            op.drop_column("event_log", "section_code")

    if _has_table(insp, "source_registry") and _has_column(insp, "source_registry", "section_code"):
        op.drop_column("source_registry", "section_code")

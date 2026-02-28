from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class VulnerabilityFinding(Base):
    __tablename__ = "vulnerability_finding"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    section_code = Column(String, nullable=True)
    asset_id = Column(String, nullable=False)
    cve_id = Column(String, nullable=False)
    source = Column(String, nullable=False, default="kev")

    severity = Column(String, nullable=False, default="medium")
    epss = Column(Float, nullable=True)
    kev = Column(Boolean, nullable=False, default=False)

    status = Column(String, nullable=False, default="open")  # open|patched|risk_accepted|false_positive
    discovered_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    due_at = Column(DateTime(timezone=True), nullable=True)
    patched_at = Column(DateTime(timezone=True), nullable=True)

    risk_score = Column(Float, nullable=False, default=0.0)
    metadata_json = Column(JSONB, nullable=False, default=dict)

    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    __table_args__ = (
        UniqueConstraint("section_code", "asset_id", "cve_id", "source", name="uq_vulnerability_asset_cve"),
        Index("ix_vulnerability_section", "section_code"),
        Index("ix_vulnerability_status", "status"),
        Index("ix_vulnerability_due", "due_at"),
        Index("ix_vulnerability_cve", "cve_id"),
    )


class PatchSlaDecision(Base):
    __tablename__ = "patch_sla_decision"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    finding_id = Column(UUID(as_uuid=True), ForeignKey("vulnerability_finding.id", ondelete="CASCADE"), nullable=False)
    section_code = Column(String, nullable=True)

    decision_status = Column(String, nullable=False)  # on_track|warning|overdue|critical
    score = Column(Float, nullable=False, default=0.0)
    reason_codes = Column(JSONB, nullable=False, default=list)
    evidence_json = Column(JSONB, nullable=False, default=dict)

    decided_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    __table_args__ = (
        UniqueConstraint("finding_id", name="uq_patch_sla_finding"),
        Index("ix_patch_sla_section", "section_code"),
        Index("ix_patch_sla_status", "decision_status"),
        Index("ix_patch_sla_score", "score"),
    )


class BackupAttestation(Base):
    __tablename__ = "backup_attestation"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    section_code = Column(String, nullable=True)
    asset_id = Column(String, nullable=False)
    backup_id = Column(String, nullable=False)

    immutable = Column(Boolean, nullable=False, default=False)
    object_lock_until = Column(DateTime(timezone=True), nullable=True)
    backup_hash = Column(String, nullable=True)
    storage_tier = Column(String, nullable=True)
    status = Column(String, nullable=False, default="unknown")
    rpo_hours = Column(Float, nullable=True)

    attested_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    evidence_json = Column(JSONB, nullable=False, default=dict)

    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    __table_args__ = (
        UniqueConstraint("section_code", "asset_id", "backup_id", name="uq_backup_attestation_asset_backup"),
        Index("ix_backup_attestation_section", "section_code"),
        Index("ix_backup_attestation_asset", "asset_id"),
        Index("ix_backup_attestation_status", "status"),
    )


class RestoreDrill(Base):
    __tablename__ = "restore_drill"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    section_code = Column(String, nullable=True)
    asset_id = Column(String, nullable=False)
    backup_id = Column(String, nullable=False)

    started_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    success = Column(Boolean, nullable=False, default=False)

    rto_target_minutes = Column(Integer, nullable=False, default=240)
    rto_actual_minutes = Column(Float, nullable=True)

    operator_id = Column(String, nullable=False)
    notes = Column(String, nullable=True)
    evidence_json = Column(JSONB, nullable=False, default=dict)

    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    __table_args__ = (
        Index("ix_restore_drill_section", "section_code"),
        Index("ix_restore_drill_asset", "asset_id"),
        Index("ix_restore_drill_success", "success"),
        Index("ix_restore_drill_created", "created_at"),
    )


class IncidentPlaybookRun(Base):
    __tablename__ = "incident_playbook_run"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    incident_key = Column(String, nullable=False)
    section_code = Column(String, nullable=True)
    severity = Column(String, nullable=False, default="medium")
    status = Column(String, nullable=False, default="running")  # running|completed|failed

    created_by = Column(String, nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    metadata_json = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    __table_args__ = (
        Index("ix_ir_run_incident", "incident_key"),
        Index("ix_ir_run_section", "section_code"),
        Index("ix_ir_run_status", "status"),
    )


class ContainmentAction(Base):
    __tablename__ = "containment_action"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id = Column(UUID(as_uuid=True), ForeignKey("incident_playbook_run.id", ondelete="CASCADE"), nullable=False)

    section_code = Column(String, nullable=True)
    action_type = Column(String, nullable=False)  # isolate_host|block_ip|revoke_user|disable_source_key|force_password_reset
    target = Column(String, nullable=False)
    status = Column(String, nullable=False, default="queued")  # queued|executed|failed

    executed_by = Column(String, nullable=False)
    executed_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    details_json = Column(JSONB, nullable=False, default=dict)

    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    __table_args__ = (
        Index("ix_containment_run", "run_id"),
        Index("ix_containment_section", "section_code"),
        Index("ix_containment_action_type", "action_type"),
        Index("ix_containment_status", "status"),
    )


class ContainmentWebhook(Base):
    """
    Partner-registered webhook endpoint for last-mile containment execution.

    When an analyst executes a block_ip or isolate_host ContainmentAction,
    the defense service looks up the matching webhook for the action's
    section_code + action_type and POSTs a signed payload to the partner's
    firewall / EDR system.

    Columns
    -------
    section_code   Which organisation owns this webhook (e.g. "safaricom")
    action_type    "block_ip" | "isolate_host"
    webhook_url    Partner-side HTTPS endpoint
    secret_hash    SHA-256 of the shared signing secret.
                   Hub signs payloads with HMAC-SHA256 so the partner can
                   verify X-Sentinel-Signature before applying the action.
    is_active      Toggle to disable without deleting
    created_at     Registration timestamp
    """
    __tablename__ = "containment_webhook"

    id           = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    section_code = Column(String, nullable=False)
    action_type  = Column(String, nullable=False)   # block_ip | isolate_host
    webhook_url  = Column(String(512), nullable=False)
    secret_enc   = Column(String,      nullable=True)   # Fernet-encrypted raw signing secret
    is_active    = Column(Boolean, nullable=False, default=True)
    created_at   = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    __table_args__ = (
        UniqueConstraint("section_code", "action_type", name="uq_webhook_section_action"),
        Index("ix_webhook_section", "section_code"),
    )


class WebhookDelivery(Base):
    """
    Immutable delivery receipt for every last-mile containment webhook call.

    One row per ContainmentAction dispatch attempt.  Retries create new rows
    so the full attempt history is preserved for forensic audit.

    status lifecycle: pending → delivered | failed
    """
    __tablename__ = "defense_webhook_delivery"

    id              = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    action_id       = Column(UUID(as_uuid=True), nullable=True)  # ContainmentAction.id
    section_code    = Column(String, nullable=True)
    action_type     = Column(String, nullable=False)
    target          = Column(String, nullable=False)
    webhook_url     = Column(String(512), nullable=False)
    status          = Column(String, nullable=False, default="pending")  # pending|delivered|failed
    http_status_code = Column(Integer, nullable=True)
    attempt_count   = Column(Integer, nullable=False, default=0)
    last_attempted_at = Column(DateTime(timezone=True), nullable=True)
    delivered_at    = Column(DateTime(timezone=True), nullable=True)
    error_message   = Column(String, nullable=True)
    response_body   = Column(JSONB, nullable=False, default=dict)
    created_at      = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    __table_args__ = (
        Index("ix_wh_delivery_action",  "action_id"),
        Index("ix_wh_delivery_section", "section_code"),
        Index("ix_wh_delivery_status",  "status"),
    )


class CryptoPostureSnapshot(Base):
    __tablename__ = "crypto_posture_snapshot"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    section_code = Column(String, nullable=True)
    taken_by = Column(String, nullable=False)

    tls_mode = Column(String, nullable=False)
    pqc_mode = Column(String, nullable=False)
    kms_provider = Column(String, nullable=False)
    signing_alg = Column(String, nullable=False)
    password_kdf = Column(String, nullable=False)
    key_rotation_days = Column(Integer, nullable=False, default=90)

    compliant = Column(Boolean, nullable=False, default=False)
    details_json = Column(JSONB, nullable=False, default=dict)

    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    __table_args__ = (
        Index("ix_crypto_posture_created", "created_at"),
        Index("ix_crypto_posture_compliant", "compliant"),
    )

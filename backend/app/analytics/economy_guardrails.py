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
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.db.base import Base


def utcnow():
    return datetime.now(timezone.utc)


class ProcurementGuardrailDecision(Base):
    """
    Persisted allow/review/block decisions for procurement requests.
    """

    __tablename__ = "procurement_guardrail_decision"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    signal_id = Column(
        UUID(as_uuid=True),
        ForeignKey("economic_signal.id", ondelete="SET NULL"),
        nullable=True,
    )

    tender_id = Column(String, nullable=True)
    vendor_id = Column(String, nullable=True)
    project_id = Column(String, nullable=True)
    agency = Column(String, nullable=True)
    sector = Column(String, nullable=False)

    decision = Column(String, nullable=False)  # allow | review | block
    score = Column(Float, nullable=False, default=0.0)
    severity = Column(String, nullable=False, default="low")

    reason_codes = Column(JSONB, nullable=False, default=list)
    indicators = Column(JSONB, nullable=False, default=dict)
    actions = Column(JSONB, nullable=False, default=list)
    evidence = Column(JSONB, nullable=False, default=dict)

    occurred_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    __table_args__ = (
        Index("ix_guardrail_decision_created_at", "created_at"),
        Index("ix_guardrail_decision_sector", "sector"),
        Index("ix_guardrail_decision_vendor", "vendor_id"),
        Index("ix_guardrail_decision_decision", "decision"),
    )


class ExternalIntegritySnapshot(Base):
    """
    Append-only integrity snapshots from external systems.
    """

    __tablename__ = "external_integrity_snapshot"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    source_system = Column(String, nullable=False)
    record_type = Column(String, nullable=False)
    record_id = Column(String, nullable=False)

    observed_at = Column(DateTime(timezone=True), nullable=False)
    payload_hash = Column(String, nullable=False)
    is_deleted = Column(Boolean, nullable=False, default=False)

    metadata_json = Column(JSONB, nullable=False, default=dict)
    evidence_json = Column(JSONB, nullable=False, default=dict)

    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    __table_args__ = (
        Index("ix_integrity_snapshot_record", "source_system", "record_type", "record_id"),
        Index("ix_integrity_snapshot_observed", "observed_at"),
    )


class ExternalTamperAlert(Base):
    """
    Detected tamper/deletion alerts derived from integrity snapshots.
    """

    __tablename__ = "external_tamper_alert"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    source_system = Column(String, nullable=False)
    record_type = Column(String, nullable=False)
    record_id = Column(String, nullable=False)

    alert_type = Column(String, nullable=False)  # RECORD_DELETION | RECORD_MUTATION_WITHOUT_TICKET | ...
    severity = Column(String, nullable=False, default="medium")
    confidence = Column(Float, nullable=False, default=0.5)
    status = Column(String, nullable=False, default="open")

    reason_codes = Column(JSONB, nullable=False, default=list)
    details_json = Column(JSONB, nullable=False, default=dict)

    first_seen = Column(DateTime(timezone=True), nullable=False)
    last_seen = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    __table_args__ = (
        UniqueConstraint(
            "source_system",
            "record_type",
            "record_id",
            "alert_type",
            "status",
            name="uq_open_tamper_alert",
        ),
        Index("ix_tamper_alert_created_at", "created_at"),
        Index("ix_tamper_alert_status", "status"),
        Index("ix_tamper_alert_record", "source_system", "record_type", "record_id"),
    )

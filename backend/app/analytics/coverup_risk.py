from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Float, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.db.base import Base


def utcnow():
    return datetime.now(timezone.utc)


class CoverupRiskAlert(Base):
    """
    Fused cover-up risk alert derived from forensic/audit/tamper event streams.
    """

    __tablename__ = "coverup_risk_alert"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    signal_id = Column(
        UUID(as_uuid=True),
        ForeignKey("economic_signal.id", ondelete="SET NULL"),
        nullable=True,
    )

    alert_key = Column(String, nullable=False)
    target_type = Column(String, nullable=False)  # service | device | source
    target_id = Column(String, nullable=False)

    score = Column(Float, nullable=False, default=0.0)
    severity = Column(String, nullable=False, default="low")
    status = Column(String, nullable=False, default="open")

    reason_codes = Column(JSONB, nullable=False, default=list)
    indicators = Column(JSONB, nullable=False, default=dict)
    evidence_hashes = Column(JSONB, nullable=False, default=list)

    window_start = Column(DateTime(timezone=True), nullable=False)
    window_end = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    __table_args__ = (
        UniqueConstraint("alert_key", name="uq_coverup_risk_alert_key"),
        Index("ix_coverup_risk_target", "target_type", "target_id"),
        Index("ix_coverup_risk_score", "score"),
        Index("ix_coverup_risk_severity", "severity"),
        Index("ix_coverup_risk_window_end", "window_end"),
        Index("ix_coverup_risk_status", "status"),
    )

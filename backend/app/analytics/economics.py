from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.db.base import Base


def utcnow():
    return datetime.now(timezone.utc)


class EconomicSignal(Base):
    """
    Normalized economic integrity signal for national-scale analytics.
    """

    __tablename__ = "economic_signal"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    signal_type = Column(String, nullable=False)  # e.g., procurement_anomaly, leakage
    sector = Column(String, nullable=False)
    agency = Column(String, nullable=True)

    entity_type = Column(String, nullable=True)  # vendor | project | department
    entity_id = Column(String, nullable=True)

    window_start = Column(DateTime(timezone=True), nullable=False)
    window_end = Column(DateTime(timezone=True), nullable=False)

    score = Column(Float, nullable=False, default=0.0)  # 0..1
    severity = Column(String, nullable=False, default="low")
    source = Column(String, nullable=False, default="system")

    reason_codes = Column(JSONB, nullable=False, default=list)
    indicators = Column(JSONB, nullable=False, default=dict)
    evidence = Column(JSONB, nullable=False, default=dict)

    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    __table_args__ = (
        Index("ix_econ_signal_type", "signal_type"),
        Index("ix_econ_signal_sector", "sector"),
        Index("ix_econ_signal_score", "score"),
        Index("ix_econ_signal_created_at", "created_at"),
    )


class ProcurementAnomaly(Base):
    """
    Procurement anomaly detected from tender/award metadata.
    """

    __tablename__ = "procurement_anomaly"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    signal_id = Column(
        UUID(as_uuid=True),
        ForeignKey("economic_signal.id", ondelete="CASCADE"),
        nullable=True,
    )

    tender_id = Column(String, nullable=True)
    vendor_id = Column(String, nullable=True)
    project_id = Column(String, nullable=True)
    agency = Column(String, nullable=True)
    sector = Column(String, nullable=False)

    amount = Column(Float, nullable=False, default=0.0)
    baseline_amount = Column(Float, nullable=True)
    currency = Column(String, nullable=False, default="KES")

    competitive_bids = Column(Integer, nullable=True)
    vendor_award_count_90d = Column(Integer, nullable=True)
    single_source = Column(Boolean, nullable=False, default=False)
    change_order_count = Column(Integer, nullable=True)

    score = Column(Float, nullable=False, default=0.0)
    severity = Column(String, nullable=False, default="low")
    indicators = Column(JSONB, nullable=False, default=dict)
    evidence = Column(JSONB, nullable=False, default=dict)

    occurred_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    __table_args__ = (
        Index("ix_proc_anomaly_sector", "sector"),
        Index("ix_proc_anomaly_vendor", "vendor_id"),
        Index("ix_proc_anomaly_score", "score"),
        Index("ix_proc_anomaly_created_at", "created_at"),
    )

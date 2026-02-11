from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Float, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.db.base import Base


def utcnow():
    return datetime.now(timezone.utc)


class LeakageAlert(Base):
    """
    Derived economic leakage alert from procurement behavior patterns.
    """

    __tablename__ = "leakage_alert"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    signal_id = Column(
        UUID(as_uuid=True),
        ForeignKey("economic_signal.id", ondelete="SET NULL"),
        nullable=True,
    )

    alert_key = Column(String, nullable=False)
    detector_type = Column(String, nullable=False)  # split_tendering | vendor_concentration | change_order_inflation
    sector = Column(String, nullable=False)
    agency = Column(String, nullable=True)
    vendor_id = Column(String, nullable=True)
    project_id = Column(String, nullable=True)

    score = Column(Float, nullable=False, default=0.0)
    severity = Column(String, nullable=False, default="low")

    reason_codes = Column(JSONB, nullable=False, default=list)
    indicators = Column(JSONB, nullable=False, default=dict)
    evidence = Column(JSONB, nullable=False, default=dict)

    window_start = Column(DateTime(timezone=True), nullable=False)
    window_end = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    __table_args__ = (
        UniqueConstraint("alert_key", name="uq_leakage_alert_key"),
        Index("ix_leakage_alert_detector", "detector_type"),
        Index("ix_leakage_alert_sector", "sector"),
        Index("ix_leakage_alert_agency", "agency"),
        Index("ix_leakage_alert_vendor", "vendor_id"),
        Index("ix_leakage_alert_window_end", "window_end"),
        Index("ix_leakage_alert_severity", "severity"),
    )

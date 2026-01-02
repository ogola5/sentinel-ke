from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, String, Float, DateTime, Boolean, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID, JSONB

from app.db.base import Base


def utcnow():
    return datetime.now(timezone.utc)


class DDoSAlert(Base):
    """
    Persistent, explainable DDoS alert derived from structural indicators.
    One row per (service_id, endpoint, window_end) per run; idempotent by unique constraint.
    """

    __tablename__ = "ddos_alert"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    service_id = Column(String, nullable=False)
    endpoint = Column(String, nullable=True)

    window_start = Column(DateTime(timezone=True), nullable=False)
    window_end = Column(DateTime(timezone=True), nullable=False)

    spike_z = Column(Float, nullable=False, default=0.0)
    unique_ip_growth_z = Column(Float, nullable=False, default=0.0)
    convergence = Column(Float, nullable=False, default=0.0)
    risk = Column(Float, nullable=False, default=0.0)  # 0..100
    stage = Column(String, nullable=False, default="normal")  # normal/rehearsal/emerging/active
    errors_up = Column(Boolean, nullable=False, default=False)
    latency_up = Column(Boolean, nullable=False, default=False)

    reason_codes = Column(JSONB, nullable=False, default=list)   # list[str]
    indicators = Column(JSONB, nullable=False, default=dict)     # snapshot of metrics

    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    __table_args__ = (
        UniqueConstraint("service_id", "endpoint", "window_end", name="uq_ddos_alert_window"),
        Index("ix_ddos_alert_risk", "risk"),
        Index("ix_ddos_alert_created_at", "created_at"),
    )

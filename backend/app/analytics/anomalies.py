from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, String, Float, DateTime, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID, JSONB

from app.db.base import Base


def utcnow():
    return datetime.now(timezone.utc)


class AnomalyScore(Base):
    """
    Time-series anomaly score per service/endpoint/window.
    Stores reason codes and indicator snapshot for explainability.
    """

    __tablename__ = "anomaly_score"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    service_id = Column(String, nullable=False)
    endpoint = Column(String, nullable=True)

    window_start = Column(DateTime(timezone=True), nullable=False)
    window_end = Column(DateTime(timezone=True), nullable=False)

    score = Column(Float, nullable=False, default=0.0)  # 0..1
    reason_codes = Column(JSONB, nullable=False, default=list)  # list[str]
    indicators = Column(JSONB, nullable=False, default=dict)    # snapshot of metrics

    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    __table_args__ = (
        UniqueConstraint("service_id", "endpoint", "window_end", name="uq_anomaly_window"),
        Index("ix_anomaly_score", "score"),
        Index("ix_anomaly_created_at", "created_at"),
    )

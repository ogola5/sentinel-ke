from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Float, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.db.base import Base


def utcnow():
    return datetime.now(timezone.utc)


class ThreatAlert(Base):
    __tablename__ = "threat_alert"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    alert_type = Column(String, nullable=False)  # bec_risk | web_attack_surge | vuln_overdue | backup_risk
    section_code = Column(String, nullable=True)
    entity_key = Column(String, nullable=False)

    window_start = Column(DateTime(timezone=True), nullable=False)
    window_end = Column(DateTime(timezone=True), nullable=False)

    score = Column(Float, nullable=False, default=0.0)
    severity = Column(String, nullable=False, default="low")
    reason_codes = Column(JSONB, nullable=False, default=list)
    indicators = Column(JSONB, nullable=False, default=dict)
    recommended_actions = Column(JSONB, nullable=False, default=list)

    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    __table_args__ = (
        UniqueConstraint("alert_type", "section_code", "entity_key", "window_end", name="uq_threat_alert_window"),
        Index("ix_threat_alert_created", "created_at"),
        Index("ix_threat_alert_type", "alert_type"),
        Index("ix_threat_alert_severity", "severity"),
        Index("ix_threat_alert_section", "section_code"),
    )

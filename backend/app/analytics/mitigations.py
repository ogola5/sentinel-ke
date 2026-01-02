from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, String, DateTime, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID, JSONB

from app.db.base import Base


def utcnow():
    return datetime.now(timezone.utc)


class Mitigation(Base):
    """
    First-class mitigation/IOC bundle tied to an alert or reference id.
    """

    __tablename__ = "mitigation"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    kind = Column(String, nullable=False)       # e.g., DDOS, VPN
    ref_id = Column(String, nullable=False)     # e.g., service:endpoint:window_end
    stakeholders = Column(JSONB, nullable=False, default=list)  # list[str]
    payload = Column(JSONB, nullable=False, default=dict)       # actions + iocs

    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    __table_args__ = (
        UniqueConstraint("kind", "ref_id", name="uq_mitigation_ref"),
        Index("ix_mitigation_created_at", "created_at"),
    )

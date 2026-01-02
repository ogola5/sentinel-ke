from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, String, Float, DateTime, ForeignKey, UniqueConstraint, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB

from app.db.base import Base


def utcnow():
    return datetime.now(timezone.utc)


class CampaignRisk(Base):
    """
    Blast-radius style risk suggestions per campaign.
    Derived, explainable, and replayable.
    """

    __tablename__ = "campaign_risk"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    campaign_id = Column(
        UUID(as_uuid=True),
        ForeignKey("campaign.id", ondelete="CASCADE"),
        nullable=False,
    )

    entity_key = Column(String, nullable=False)
    entity_type = Column(String, nullable=False)

    score = Column(Float, nullable=False, default=0.0)  # 0..1
    reason_codes = Column(JSONB, nullable=False, default=list)  # list[str]
    details_json = Column(JSONB, nullable=False, default=dict)

    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    __table_args__ = (
        UniqueConstraint("campaign_id", "entity_key", name="uq_campaign_risk_entity"),
        Index("ix_campaign_risk_campaign", "campaign_id"),
        Index("ix_campaign_risk_score", "score"),
    )

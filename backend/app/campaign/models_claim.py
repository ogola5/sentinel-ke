# backend/app/campaign/models_claim.py
from __future__ import annotations

import uuid
from sqlalchemy import (
    Column,
    String,
    DateTime,
    Float,
    ForeignKey,
    Index,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB

from app.db.base import Base, utcnow


class CampaignClaim(Base):
    """
    Layer-3 canonical analytic claim.

    A claim is:
      - derived
      - explainable
      - replayable
      - graph-projectable
    """

    __tablename__ = "campaign_claim"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    claim_type = Column(String, nullable=False)

    subject_campaign_id = Column(
        UUID(as_uuid=True),
        ForeignKey("campaign.id", ondelete="CASCADE"),
        nullable=False,
    )

    object_campaign_id = Column(
        UUID(as_uuid=True),
        ForeignKey("campaign.id", ondelete="CASCADE"),
        nullable=False,
    )

    # semantic window (10m / 24h / 30d)
    window_key = Column(String, nullable=False)

    window_start = Column(DateTime(timezone=True), nullable=False)
    window_end = Column(DateTime(timezone=True), nullable=False)

    confidence = Column(Float, nullable=False, default=0.0)

    reason_codes = Column(JSONB, nullable=False, default=list)
    evidence_hashes = Column(JSONB, nullable=False, default=list)
    infra_cluster_ids = Column(JSONB, nullable=False, default=list)

    details_json = Column(JSONB, nullable=False, default=dict)

    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    __table_args__ = (
        Index(
            "uq_campaign_claim_identity",
            "claim_type",
            "subject_campaign_id",
            "object_campaign_id",
            "window_key",
            unique=True,
        ),
        Index(
            "ix_campaign_claim_window_end",
            "window_key",
            "window_end",
        ),
    )

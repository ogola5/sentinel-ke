# backend/app/campaign/claims.py
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, Float, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID, JSONB

from app.db.base import Base
from app.ledger.models import utcnow  # reuse your utc clock


class CampaignClaim(Base):
    """
    Canonical Layer-3 claim ledger.

    Stores *interpretations* (claims), not raw facts.
    Backed by event hashes for explainability.
    """
    __tablename__ = "campaign_claim"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    claim_type = Column(String, nullable=False)  # e.g. CAMPAIGN_INFRA_REUSE_OVERLAP

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

    # window semantics (ledger-time aligned, not projection-time)
    window = Column(String, nullable=False, default="Wmid")  # Wshort/Wmid/Wlong
    window_start = Column(DateTime(timezone=True), nullable=False)
    window_end = Column(DateTime(timezone=True), nullable=False)

    confidence = Column(Float, nullable=False, default=0.0)

    reason_codes = Column(JSONB, nullable=False, default=list)      # list[str]
    evidence_hashes = Column(JSONB, nullable=False, default=list)   # list[str]
    infra_cluster_ids = Column(JSONB, nullable=False, default=list) # list[str]

    details_json = Column(JSONB, nullable=False, default=dict)

    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    __table_args__ = (
        # idempotency for a given bucket:
        UniqueConstraint(
            "claim_type",
            "subject_campaign_id",
            "object_campaign_id",
            "window",
            "window_end",
            name="uq_campaign_claim_identity",
        ),
        Index("ix_campaign_claim_subject", "subject_campaign_id"),
        Index("ix_campaign_claim_object", "object_campaign_id"),
        Index("ix_campaign_claim_window_end", "window", "window_end"),
    )

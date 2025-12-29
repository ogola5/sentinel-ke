# # app/campaign/models.py
# from __future__ import annotations

# import uuid
# from datetime import datetime

# from sqlalchemy import (
#     Column, String, DateTime, Integer, Float, ForeignKey,
#     UniqueConstraint, Index, JSON
# )
# from sqlalchemy.dialects.postgresql import UUID
# from sqlalchemy.orm import declarative_base

# Base = declarative_base()


# class Campaign(Base):
#     __tablename__ = "campaign"

#     id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

#     # campaign "type" (rule family) and primary indicator key
#     type = Column(String, nullable=False)  # e.g. INFRA_REUSE
#     primary_key = Column(String, nullable=False)  # e.g. "ip:8.8.8.8"

#     status = Column(String, nullable=False, default="active")  # active|dormant|closed
#     rule_version = Column(String, nullable=False, default="a4.v1")

#     # time bounds
#     first_seen = Column(DateTime(timezone=True), nullable=False)
#     last_seen = Column(DateTime(timezone=True), nullable=False)

#     # counters
#     event_count = Column(Integer, nullable=False, default=0)
#     score = Column(Float, nullable=False, default=0.0)

#     # small summary for UI (avoid huge arrays here)
#     stats = Column(JSON, nullable=False, default=dict)

#     __table_args__ = (
#         Index("ix_campaign_primary_key_last_seen", "primary_key", "last_seen"),
#         Index("ix_campaign_status_last_seen", "status", "last_seen"),
#     )


# class CampaignEvent(Base):
#     __tablename__ = "campaign_event"

#     campaign_id = Column(UUID(as_uuid=True), ForeignKey("campaign.id", ondelete="CASCADE"), primary_key=True)
#     event_hash = Column(String, primary_key=True)
#     occurred_at = Column(DateTime(timezone=True), nullable=False)

#     __table_args__ = (
#         Index("ix_campaign_event_occurred_at", "occurred_at"),
#     )


# class CampaignEntity(Base):
#     """
#     Tracks distinct entities seen in a campaign with investigative role.
#     """

#     __tablename__ = "campaign_entity"

#     campaign_id = Column(
#         UUID(as_uuid=True),
#         ForeignKey("campaign.id", ondelete="CASCADE"),
#         primary_key=True,
#     )

#     entity_key = Column(String, primary_key=True)
#     entity_type = Column(String, nullable=False)  
#     # Person | Device | Endpoint | Service | IP | Domain | URL | Provider

#     role = Column(
#         String,
#         nullable=False,
#         default="unknown",
#     )
#     # attacker | target | context | unknown

#     last_seen = Column(DateTime(timezone=True), nullable=False)

#     __table_args__ = (
#         Index("ix_campaign_entity_type", "entity_type"),
#         Index("ix_campaign_entity_role", "role"),
#     )


# class CampaignEvidence(Base):
#     """
#     Immutable evidence explaining WHY an event is linked to a campaign.
#     Investigation-grade: deterministic, replayable.
#     """

#     __tablename__ = "campaign_evidence"

#     campaign_id = Column(
#         UUID(as_uuid=True),
#         ForeignKey("campaign.id", ondelete="CASCADE"),
#         primary_key=True,
#     )

#     event_hash = Column(String, primary_key=True)

#     # rule / signal metadata
#     signal_type = Column(String, nullable=False)     # e.g. DDOS_ENDPOINT_FANIN
#     primary_key = Column(String, nullable=False)     # e.g. endpoint:/api/login

#     created_at = Column(DateTime(timezone=True), nullable=False)

#     __table_args__ = (
#         Index("ix_campaign_evidence_campaign", "campaign_id"),
#         Index("ix_campaign_evidence_event", "event_hash"),
#         Index("ix_campaign_evidence_signal", "signal_type"),
#     )


from __future__ import annotations
import uuid
from datetime import datetime

from sqlalchemy import (
    Column, String, DateTime, Integer, Float, ForeignKey, Index, JSON
)
from sqlalchemy.dialects.postgresql import UUID

from app.db.base import Base


class Campaign(Base):
    __tablename__ = "campaign"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    type = Column(String, nullable=False)
    primary_key = Column(String, nullable=False)

    status = Column(String, nullable=False, default="active")
    rule_version = Column(String, nullable=False, default="a4.v1")

    first_seen = Column(DateTime(timezone=True), nullable=False)
    last_seen = Column(DateTime(timezone=True), nullable=False)

    event_count = Column(Integer, nullable=False, default=0)
    score = Column(Float, nullable=False, default=0.0)

    stats = Column(JSON, nullable=False, default=dict)

    __table_args__ = (
        Index("ix_campaign_primary_key_last_seen", "primary_key", "last_seen"),
        Index("ix_campaign_status_last_seen", "status", "last_seen"),
    )


class CampaignEvent(Base):
    __tablename__ = "campaign_event"

    campaign_id = Column(
        UUID(as_uuid=True),
        ForeignKey("campaign.id", ondelete="CASCADE"),
        primary_key=True,
    )

    event_hash = Column(String, primary_key=True)
    occurred_at = Column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_campaign_event_occurred_at", "occurred_at"),
    )


class CampaignEntity(Base):
    __tablename__ = "campaign_entity"

    campaign_id = Column(
        UUID(as_uuid=True),
        ForeignKey("campaign.id", ondelete="CASCADE"),
        primary_key=True,
    )

    entity_key = Column(String, primary_key=True)
    entity_type = Column(String, nullable=False)
    role = Column(String, nullable=False, default="unknown")
    last_seen = Column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_campaign_entity_type", "entity_type"),
        Index("ix_campaign_entity_role", "role"),
    )


class CampaignEvidence(Base):
    __tablename__ = "campaign_evidence"

    campaign_id = Column(
        UUID(as_uuid=True),
        ForeignKey("campaign.id", ondelete="CASCADE"),
        primary_key=True,
    )

    event_hash = Column(String, primary_key=True)
    signal_type = Column(String, nullable=False)
    primary_key = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_campaign_evidence_campaign", "campaign_id"),
        Index("ix_campaign_evidence_event", "event_hash"),
        Index("ix_campaign_evidence_signal", "signal_type"),
    )

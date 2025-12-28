# app/campaign/models.py
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Column, String, DateTime, Integer, Float, ForeignKey,
    UniqueConstraint, Index, JSON
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class Campaign(Base):
    __tablename__ = "campaign"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # campaign "type" (rule family) and primary indicator key
    type = Column(String, nullable=False)  # e.g. INFRA_REUSE
    primary_key = Column(String, nullable=False)  # e.g. "ip:8.8.8.8"

    status = Column(String, nullable=False, default="active")  # active|dormant|closed
    rule_version = Column(String, nullable=False, default="a4.v1")

    # time bounds
    first_seen = Column(DateTime(timezone=True), nullable=False)
    last_seen = Column(DateTime(timezone=True), nullable=False)

    # counters
    event_count = Column(Integer, nullable=False, default=0)
    score = Column(Float, nullable=False, default=0.0)

    # small summary for UI (avoid huge arrays here)
    stats = Column(JSON, nullable=False, default=dict)

    __table_args__ = (
        Index("ix_campaign_primary_key_last_seen", "primary_key", "last_seen"),
        Index("ix_campaign_status_last_seen", "status", "last_seen"),
    )


class CampaignEvent(Base):
    __tablename__ = "campaign_event"

    campaign_id = Column(UUID(as_uuid=True), ForeignKey("campaign.id", ondelete="CASCADE"), primary_key=True)
    event_hash = Column(String, primary_key=True)
    occurred_at = Column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_campaign_event_occurred_at", "occurred_at"),
    )


class CampaignEntity(Base):
    """
    Tracks distinct entities seen in a campaign (for fast cardinalities).
    entity_key examples:
      person_h:demo1
      device_id:device-001
      endpoint:/api/login
      service_id:eCitizen
      ip:8.8.8.8
    """
    __tablename__ = "campaign_entity"

    campaign_id = Column(UUID(as_uuid=True), ForeignKey("campaign.id", ondelete="CASCADE"), primary_key=True)
    entity_key = Column(String, primary_key=True)
    entity_type = Column(String, nullable=False)  # Person|Device|Endpoint|Service|IP|Domain|URL|Provider

    last_seen = Column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_campaign_entity_type", "entity_type"),
    )

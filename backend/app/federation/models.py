"""
Sentinel-KE Federation — Database models
=========================================

Stores partner registrations and GNN pattern submissions from edge agents.

Architecture
------------
Each partner (bank / telco / hospital / government) runs the Sentinel-KE
Edge Agent Docker on their own infrastructure.  Their local GNN processes
their own sensitive data and sends only HASHED risk patterns to this hub.

Tables
------
federation_partner
    One row per registered edge agent.  Tracks liveness, API key hash,
    and cumulative statistics.

federation_pattern
    One row per high-risk entity signal received from any edge agent.
    entity_key_hash is a HMAC-SHA256 of the entity key using a
    shared national correlation salt — the hub sees that "the same hashed entity
    appeared at Equity Bank AND Safaricom" without knowing the real key.

The cross-partner correlation query (see api/federation.py) joins
federation_pattern on entity_key_hash to surface entities flagged by
multiple independent organizations in the same time window.  A signal
confirmed by 2+ independent partners is near-certain evidence of a
real cross-organizational attack.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean, Column, DateTime, Float, Integer, String, Text,
    UniqueConstraint, Index,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID

from app.ledger.models import Base
from app.db.base import utcnow


class FederationPartner(Base):
    """
    Registered edge-agent partner.

    Columns
    -------
    partner_id          Short stable identifier, e.g. "equity-bank-ke"
    partner_name        Display name, e.g. "Equity Bank Kenya"
    partner_type        One of: bank, telco, hospital, government, other
    api_key_hash        SHA-256 of the partner's ingest API key
    correlation_salt    National hub salt shared with the edge agent at
                        registration.  Edge agents hash entity_key with
                        THIS salt (not their local salt) so the same entity
                        produces the same hash across all partners, enabling
                        cross-partner correlation queries.
    webhook_url         Partner-side firewall/EDR HTTP endpoint.  The hub
                        POSTs signed block_ip / isolate_host payloads here.
    webhook_secret_hash SHA-256 of the webhook signing secret.  The partner
                        verifies X-Sentinel-Signature before applying the action.
    last_seen           UTC timestamp of last successful pattern submission
    last_pattern_at     UTC timestamp of last pattern batch received
    total_patterns      Cumulative pattern rows received (informational)
    is_active           Can be toggled to suspend a partner
    metadata_json       Free-form partner metadata (contact, region, etc.)
    """
    __tablename__ = "federation_partner"

    partner_id          = Column(String(64),  primary_key=True)
    partner_name        = Column(String(255), nullable=False)
    partner_type        = Column(String(32),  nullable=False, default="other")
    api_key_hash        = Column(String(64),  nullable=False)
    correlation_salt    = Column(String(64),  nullable=False, default="")
    webhook_url         = Column(String(512), nullable=True)
    webhook_secret_hash = Column(String(64),  nullable=True)
    registered_at       = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    last_seen           = Column(DateTime(timezone=True), nullable=True)
    last_pattern_at     = Column(DateTime(timezone=True), nullable=True)
    total_patterns      = Column(Integer, nullable=False, default=0)
    is_active           = Column(Boolean, nullable=False, default=True)
    metadata_json       = Column(JSONB, nullable=False, default=dict)


class FederationPattern(Base):
    """
    Single high-risk entity signal from an edge agent's GNN run.

    One batch POST from an edge agent inserts many rows (one per
    high-risk entity).  Only entities with risk_score >= threshold
    (default 0.6) are sent by the edge agent.

    Columns
    -------
    partner_id        Which edge agent submitted this
    received_at       Hub receipt time (set server-side)
    window_start/end  The GNN inference window on the partner's data
    gnn_model_version Edge agent's artifact version string
    entity_key_hash   HMAC-SHA256(entity_key, national correlation salt) — privacy-preserving
    entity_type       ip / phone_h / account_h / domain / etc.
    risk_score        GNN probability in [0, 1]
    uncertainty       MC-Dropout std-dev in [0, 1]
    fraud_family      Detected fraud family label (CAMPAIGN, SIM_SWAP, …)
    chain_score       Multi-stage attack chain score [0, 1]
    risk_flags        List of active risk flag strings
    summary_json      Per-batch aggregate summary (total scored, mean risk, …)
    schema_version    Pattern schema version for forward compatibility
    """
    __tablename__ = "federation_pattern"
    __table_args__ = (
        Index("ix_fed_pattern_hash_time",  "entity_key_hash", "received_at"),
        Index("ix_fed_pattern_partner",    "partner_id", "received_at"),
        Index("ix_fed_pattern_risk",       "risk_score", "received_at"),
    )

    id              = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    partner_id      = Column(String(64), nullable=False, index=True)
    received_at     = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    window_start    = Column(DateTime(timezone=True), nullable=True)
    window_end      = Column(DateTime(timezone=True), nullable=True)
    gnn_model_version = Column(String(64), nullable=True)
    entity_key_hash = Column(String(64),  nullable=False)
    entity_type     = Column(String(32),  nullable=True)
    risk_score      = Column(Float,       nullable=False, default=0.0)
    uncertainty     = Column(Float,       nullable=False, default=0.0)
    fraud_family    = Column(String(64),  nullable=True)
    chain_score     = Column(Float,       nullable=False, default=0.0)
    risk_flags      = Column(ARRAY(Text), nullable=False, default=list)
    summary_json    = Column(JSONB,       nullable=False, default=dict)
    schema_version  = Column(String(8),   nullable=False, default="1.0")


class FederationWarning(Base):
    """
    Warning envelope generated by central command for one or more partners.

    The warning references a hashed entity and operational context only. Each
    partner resolves the hash locally using its own hash index.
    """

    __tablename__ = "federation_warning"
    __table_args__ = (
        Index("ix_fed_warning_created", "created_at"),
        Index("ix_fed_warning_hash", "entity_key_hash", "created_at"),
        Index("ix_fed_warning_status", "status", "created_at"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    created_by_actor = Column(String(128), nullable=True)
    source_kind = Column(String(32), nullable=False, default="correlation")
    entity_key_hash = Column(String(64), nullable=False)
    entity_type = Column(String(32), nullable=True)
    threat_family = Column(String(64), nullable=True)
    severity = Column(String(16), nullable=False, default="medium")
    urgency = Column(String(16), nullable=False, default="routine")
    title = Column(String(255), nullable=False)
    summary_text = Column(Text, nullable=False, default="")
    tlp = Column(String(16), nullable=False, default="amber")
    classification = Column(String(32), nullable=False, default="RESTRICTED")
    status = Column(String(24), nullable=False, default="open")
    source_partner_ids = Column(ARRAY(Text), nullable=False, default=list)
    target_partner_ids = Column(ARRAY(Text), nullable=False, default=list)
    first_seen = Column(DateTime(timezone=True), nullable=True)
    last_seen = Column(DateTime(timezone=True), nullable=True)
    correlation_count = Column(Integer, nullable=False, default=0)
    max_risk = Column(Float, nullable=False, default=0.0)
    avg_risk = Column(Float, nullable=False, default=0.0)
    max_chain_score = Column(Float, nullable=False, default=0.0)
    risk_flags = Column(ARRAY(Text), nullable=False, default=list)
    recommended_actions = Column(ARRAY(Text), nullable=False, default=list)
    metadata_json = Column(JSONB, nullable=False, default=dict)


class FederationWarningAck(Base):
    """
    Partner acknowledgement for a warning envelope.

    This captures whether the partner received, resolved, or explicitly
    rejected the warning, plus optional local detail.
    """

    __tablename__ = "federation_warning_ack"
    __table_args__ = (
        UniqueConstraint("warning_id", "partner_id", name="uq_fed_warning_ack_warning_partner"),
        Index("ix_fed_warning_ack_partner", "partner_id", "acknowledged_at"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    warning_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    partner_id = Column(String(64), nullable=False, index=True)
    acknowledged_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    status = Column(String(32), nullable=False, default="received")
    detail_json = Column(JSONB, nullable=False, default=dict)

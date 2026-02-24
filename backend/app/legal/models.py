from __future__ import annotations

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB

from app.db.base import Base, utcnow


class LegalOrder(Base):
    __tablename__ = "legal_order"

    order_id = Column(String, primary_key=True)
    order_number = Column(String, nullable=False, unique=True)
    court_name = Column(String, nullable=False)
    case_reference = Column(String, nullable=True)
    purpose = Column(String, nullable=False)
    authorized_by = Column(String, nullable=False)

    issued_at = Column(DateTime(timezone=True), nullable=False)
    valid_from = Column(DateTime(timezone=True), nullable=False)
    valid_until = Column(DateTime(timezone=True), nullable=False)

    status = Column(String, nullable=False, default="active")
    allowed_actions_json = Column(JSONB, nullable=False, default=list)
    allowed_targets_json = Column(JSONB, nullable=False, default=list)
    constraints_json = Column(JSONB, nullable=False, default=dict)
    metadata_json = Column(JSONB, nullable=False, default=dict)

    created_by = Column(String, nullable=False)
    revoked_by = Column(String, nullable=True)
    revoked_reason = Column(String, nullable=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    __table_args__ = (
        Index("ix_legal_order_status", "status"),
        Index("ix_legal_order_valid_until", "valid_until"),
    )


class LegalAuthorizationGrant(Base):
    __tablename__ = "legal_authorization_grant"

    grant_id = Column(String, primary_key=True)
    order_id = Column(
        String,
        ForeignKey("legal_order.order_id", ondelete="RESTRICT"),
        nullable=False,
    )
    action_type = Column(String, nullable=False)
    target = Column(String, nullable=False)
    requested_by = Column(String, nullable=False)
    approved_by_json = Column(JSONB, nullable=False, default=list)
    justification = Column(String, nullable=True)

    policy_version = Column(String, nullable=False, default="v1")
    model_action_scope_json = Column(JSONB, nullable=False, default=dict)

    status = Column(String, nullable=False)
    reason_codes_json = Column(JSONB, nullable=False, default=list)
    evidence_json = Column(JSONB, nullable=False, default=dict)

    valid_from = Column(DateTime(timezone=True), nullable=False)
    valid_until = Column(DateTime(timezone=True), nullable=False)
    used_at = Column(DateTime(timezone=True), nullable=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    execution_token = Column(String, nullable=False, unique=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    __table_args__ = (
        Index("ix_legal_grant_order_id", "order_id"),
        Index("ix_legal_grant_status", "status"),
        Index("ix_legal_grant_valid_until", "valid_until"),
    )


class LegalEvidenceBundle(Base):
    __tablename__ = "legal_evidence_bundle"

    bundle_id = Column(String, primary_key=True)
    export_type = Column(String, nullable=False, default="court_case_legal_chain_v1")
    campaign_id = Column(String, nullable=False)
    order_id = Column(
        String,
        ForeignKey("legal_order.order_id", ondelete="RESTRICT"),
        nullable=False,
    )
    root_hash = Column(String, nullable=False, unique=True)
    prev_chain_hash = Column(String, nullable=True)
    chain_hash = Column(String, nullable=False, unique=True)
    payload_json = Column(JSONB, nullable=False, default=dict)
    created_by = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    __table_args__ = (
        Index("ix_legal_bundle_campaign", "campaign_id"),
        Index("ix_legal_bundle_order", "order_id"),
        Index("ix_legal_bundle_created_at", "created_at"),
    )


class LegalEvidenceAnchor(Base):
    __tablename__ = "legal_evidence_anchor"

    anchor_id = Column(String, primary_key=True)
    bundle_id = Column(
        String,
        ForeignKey("legal_evidence_bundle.bundle_id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )

    minio_backend = Column(String, nullable=False, default="stub")
    minio_bucket = Column(String, nullable=True)
    minio_object_key = Column(String, nullable=True)
    minio_version_id = Column(String, nullable=True)
    minio_etag = Column(String, nullable=True)

    immudb_backend = Column(String, nullable=False, default="stub")
    immudb_key = Column(String, nullable=True)
    immudb_tx_id = Column(String, nullable=True)
    immudb_verified = Column(Boolean, nullable=False, default=False)

    anchor_status = Column(String, nullable=False, default="failed")
    anchor_receipt_hash = Column(String, nullable=False, unique=True)
    error_json = Column(JSONB, nullable=False, default=dict)
    metadata_json = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    __table_args__ = (
        Index("ix_legal_anchor_bundle", "bundle_id"),
        Index("ix_legal_anchor_status", "anchor_status"),
        Index("ix_legal_anchor_created_at", "created_at"),
    )


class LegalEvidenceCertificate(Base):
    __tablename__ = "legal_evidence_certificate"

    certificate_id = Column(String, primary_key=True)
    bundle_id = Column(
        String,
        ForeignKey("legal_evidence_bundle.bundle_id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    framework = Column(String, nullable=False, default="evidence_act_sec_106b")
    jurisdiction = Column(String, nullable=False, default="KE")
    statement_hash = Column(String, nullable=False, unique=True)
    signed_by = Column(String, nullable=False)
    signature_method = Column(String, nullable=False, default="sha256_attestation")
    signature = Column(String, nullable=False)
    metadata_json = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    __table_args__ = (
        Index("ix_legal_certificate_bundle", "bundle_id"),
        Index("ix_legal_certificate_created", "created_at"),
    )

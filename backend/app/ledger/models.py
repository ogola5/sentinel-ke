from datetime import datetime, timezone
from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import declarative_base
# from app.ledger.infra_clusters import InfraCluster, InfraClusterMember  # noqa: F401
# from app.ledger.infra_evidence import InfraClusterEvidence  # noqa: F401
Base = declarative_base()


def utcnow():
    return datetime.now(timezone.utc)


class SourceRegistry(Base):
    __tablename__ = "source_registry"

    source_id = Column(String, primary_key=True)  # safaricom, kcb, kra
    source_type = Column(String, nullable=False)  # telco | bank | gov | isp | osint

    classification_level = Column(String, nullable=False, default="RESTRICTED")
    api_key_hash = Column(String, nullable=False, unique=True)

    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)


class EventLog(Base):
    __tablename__ = "event_log"

    event_hash = Column(String, primary_key=True)  # SHA256 hex
    event_type = Column(String, nullable=False)

    source_id = Column(
        String,
        ForeignKey("source_registry.source_id", ondelete="RESTRICT"),
        nullable=False,
    )

    classification = Column(String, nullable=False)

    occurred_at = Column(DateTime(timezone=True), nullable=False)
    received_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    schema_version = Column(String, nullable=False, default="v1")
    signature_valid = Column(Boolean, nullable=False, default=False)

    anchors_json = Column(JSONB, nullable=False)
    payload_json = Column(JSONB, nullable=False)

    __table_args__ = (
        Index("ix_event_log_occurred_at", "occurred_at"),
        Index("ix_event_log_source", "source_id"),
        Index("ix_event_log_type_time", "event_type", "occurred_at"),
    )


class EventEntityIndex(Base):
    __tablename__ = "event_entity_index"

    event_hash = Column(
        String,
        ForeignKey("event_log.event_hash", ondelete="RESTRICT"),
        primary_key=True,
    )
    entity_key = Column(String, primary_key=True)  # ip:1.2.3.4, domain:x.tld, phone_h:...

    __table_args__ = (
        Index("ix_event_entity_entity_key", "entity_key"),
    )


class AuditLog(Base):
    __tablename__ = "audit_log"

    id = Column(String, primary_key=True)
    actor_type = Column(String, nullable=False)  # source | user | system
    actor_id = Column(String, nullable=False)

    action = Column(String, nullable=False)
    target = Column(String, nullable=True)

    at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    __table_args__ = (
        Index("ix_audit_actor_time", "actor_id", "at"),
        Index("ix_audit_action_time", "action", "at"),
    )

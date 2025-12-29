# backend/app/ledger/infra_clusters.py
from __future__ import annotations

from sqlalchemy import Column, String, DateTime, Float, Integer, ForeignKey, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from app.ledger.models import Base, utcnow


class InfraCluster(Base):
    """
    InfraCluster = persisted grouping of infrastructure entities (IPs today).
    Postgres is the canonical store of cluster metadata + "why linked" evidence pointers.
    """
    __tablename__ = "infra_cluster"

    cluster_id = Column(String, primary_key=True)  # uuid-ish string (we generate in API)
    kind = Column(String, nullable=False, default="vpn_exit")  # vpn_exit | ddos | phishing | mule | other
    confidence = Column(Float, nullable=False, default=0.5)

    window_start = Column(DateTime(timezone=True), nullable=True)
    window_end = Column(DateTime(timezone=True), nullable=True)

    first_seen = Column(DateTime(timezone=True), nullable=True)
    last_seen = Column(DateTime(timezone=True), nullable=True)

    member_count = Column(Integer, nullable=False, default=0)

    summary_json = Column(JSONB, nullable=False, default=dict)  # lightweight UI summary
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    members = relationship("InfraClusterMember", back_populates="cluster", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_infra_cluster_kind_time", "kind", "created_at"),
        Index("ix_infra_cluster_window", "window_start", "window_end"),
    )


class InfraClusterMember(Base):
    """
    Membership table for cluster -> entity_key (stable IDs)
      e.g. entity_key = "ip:41.90.1.2"
    """
    __tablename__ = "infra_cluster_member"

    cluster_id = Column(
        String,
        ForeignKey("infra_cluster.cluster_id", ondelete="CASCADE"),
        primary_key=True,
    )
    entity_key = Column(String, primary_key=True)

    first_seen = Column(DateTime(timezone=True), nullable=True)
    last_seen = Column(DateTime(timezone=True), nullable=True)
    event_count = Column(Integer, nullable=False, default=0)

    meta_json = Column(JSONB, nullable=False, default=dict)

    cluster = relationship("InfraCluster", back_populates="members")

    __table_args__ = (
        Index("ix_infra_cluster_member_entity", "entity_key"),
    )

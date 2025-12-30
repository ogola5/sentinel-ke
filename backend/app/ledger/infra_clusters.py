
from __future__ import annotations

from sqlalchemy import Column, String, DateTime, Float, Integer, ForeignKey, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from app.db.base import Base, utcnow



class InfraCluster(Base):
    __tablename__ = "infra_cluster"

    cluster_id = Column(String, primary_key=True)
    kind = Column(String, nullable=False)
    confidence = Column(Float, nullable=False, default=0.5)

    window_start = Column(DateTime(timezone=True))
    window_end = Column(DateTime(timezone=True))

    first_seen = Column(DateTime(timezone=True))
    last_seen = Column(DateTime(timezone=True))

    member_count = Column(Integer, nullable=False, default=0)
    summary_json = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    members = relationship(
        "InfraClusterMember",
        back_populates="cluster",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_infra_cluster_kind_time", "kind", "created_at"),
    )


class InfraClusterMember(Base):
    __tablename__ = "infra_cluster_member"

    cluster_id = Column(
        String,
        ForeignKey("infra_cluster.cluster_id", ondelete="CASCADE"),
        primary_key=True,
    )
    entity_key = Column(String, primary_key=True)

    first_seen = Column(DateTime(timezone=True))
    last_seen = Column(DateTime(timezone=True))
    event_count = Column(Integer, nullable=False, default=0)
    meta_json = Column(JSONB, nullable=False, default=dict)

    cluster = relationship(
        "InfraCluster",
        back_populates="members",
    )

    __table_args__ = (
        Index("ix_infra_cluster_member_entity", "entity_key"),
    )

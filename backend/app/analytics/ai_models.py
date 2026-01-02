from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, String, DateTime, Float, Integer, Index, UniqueConstraint, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB

from app.db.base import Base


def utcnow():
    return datetime.now(timezone.utc)


class GraphFeatureSnapshot(Base):
    __tablename__ = "graph_feature_snapshot"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    entity_key = Column(String, nullable=False)
    entity_type = Column(String, nullable=False)

    window_key = Column(String, nullable=False)  # Wshort/Wmid/Wlong
    window_start = Column(DateTime(timezone=True), nullable=False)
    window_end = Column(DateTime(timezone=True), nullable=False)

    degree = Column(Integer, nullable=False, default=0)
    weighted_degree = Column(Integer, nullable=False, default=0)
    event_count = Column(Integer, nullable=False, default=0)

    first_seen = Column(DateTime(timezone=True), nullable=True)
    last_seen = Column(DateTime(timezone=True), nullable=True)

    risk_flags = Column(JSONB, nullable=False, default=list)
    features = Column(JSONB, nullable=False, default=dict)

    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    __table_args__ = (
        UniqueConstraint("entity_key", "window_key", "window_end", name="uq_feature_snapshot"),
        Index("ix_feature_entity", "entity_key"),
        Index("ix_feature_window_end", "window_end"),
    )


class EntityEmbedding(Base):
    __tablename__ = "entity_embedding"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    entity_key = Column(String, nullable=False)
    entity_type = Column(String, nullable=False)

    window_key = Column(String, nullable=False)
    window_end = Column(DateTime(timezone=True), nullable=False)

    model_version = Column(String, nullable=False, default="hash-v1")
    embedding = Column(JSONB, nullable=False, default=list)  # list[float]

    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    __table_args__ = (
        UniqueConstraint(
            "entity_key", "window_key", "window_end", "model_version", name="uq_embedding"
        ),
        Index("ix_embedding_entity", "entity_key"),
        Index("ix_embedding_window_end", "window_end"),
    )


class AIPrediction(Base):
    __tablename__ = "ai_prediction"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    entity_key = Column(String, nullable=False)
    entity_type = Column(String, nullable=False)
    prediction_type = Column(String, nullable=False)  # risk | anomaly | expand

    window_key = Column(String, nullable=False)
    window_end = Column(DateTime(timezone=True), nullable=False)

    score = Column(Float, nullable=False, default=0.0)
    reason_codes = Column(JSONB, nullable=False, default=list)
    details_json = Column(JSONB, nullable=False, default=dict)

    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    __table_args__ = (
        UniqueConstraint(
            "entity_key", "prediction_type", "window_key", "window_end", name="uq_ai_prediction"
        ),
        Index("ix_ai_pred_score", "score"),
        Index("ix_ai_pred_window_end", "window_end"),
    )


class AIExplanation(Base):
    __tablename__ = "ai_explanation"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    prediction_id = Column(
        UUID(as_uuid=True),
        ForeignKey("ai_prediction.id", ondelete="CASCADE"),
        nullable=False,
    )

    reason_codes = Column(JSONB, nullable=False, default=list)
    evidence_hashes = Column(JSONB, nullable=False, default=list)
    evidence_paths = Column(JSONB, nullable=False, default=list)
    details_json = Column(JSONB, nullable=False, default=dict)

    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    __table_args__ = (
        Index("ix_ai_expl_prediction", "prediction_id"),
    )

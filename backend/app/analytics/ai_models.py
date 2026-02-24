from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID

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
    embedding_type = Column(String, nullable=False, default="gnn")
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

    model_version = Column(String, nullable=False, default="unknown")
    window_key = Column(String, nullable=False)
    window_end = Column(DateTime(timezone=True), nullable=False)

    score = Column(Float, nullable=False, default=0.0)
    confidence = Column(Float, nullable=False, default=0.0)
    uncertainty = Column(Float, nullable=False, default=1.0)
    abstained = Column(Boolean, nullable=False, default=False)
    kill_chain_stage = Column(String, nullable=True)
    decision_source = Column(String, nullable=False, default="model")

    reason_codes = Column(JSONB, nullable=False, default=list)
    details_json = Column(JSONB, nullable=False, default=dict)

    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    __table_args__ = (
        UniqueConstraint(
            "entity_key", "prediction_type", "window_key", "window_end", name="uq_ai_prediction"
        ),
        Index("ix_ai_pred_score", "score"),
        Index("ix_ai_pred_window_end", "window_end"),
        Index("ix_ai_pred_model_version", "model_version"),
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
    recommended_controls_json = Column(JSONB, nullable=False, default=list)
    counterfactual_json = Column(JSONB, nullable=False, default=dict)
    details_json = Column(JSONB, nullable=False, default=dict)

    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    __table_args__ = (
        Index("ix_ai_expl_prediction", "prediction_id"),
    )


class GNNTrainingRun(Base):
    __tablename__ = "gnn_training_run"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    model_version = Column(String, nullable=False)
    prediction_type = Column(String, nullable=False, default="risk_gnn")
    source_backend = Column(String, nullable=False, default="hybrid")

    window_key = Column(String, nullable=False)
    window_end = Column(DateTime(timezone=True), nullable=False)

    node_count = Column(Integer, nullable=False, default=0)
    edge_count = Column(Integer, nullable=False, default=0)
    feature_dim = Column(Integer, nullable=False, default=0)
    positive_count = Column(Integer, nullable=False, default=0)

    epochs = Column(Integer, nullable=False, default=0)
    train_loss = Column(Float, nullable=True)
    val_loss = Column(Float, nullable=True)
    auc = Column(Float, nullable=True)
    precision = Column(Float, nullable=True)
    recall = Column(Float, nullable=True)
    f1 = Column(Float, nullable=True)

    artifact_path = Column(String, nullable=True)
    params_json = Column(JSONB, nullable=False, default=dict)
    metrics_json = Column(JSONB, nullable=False, default=dict)

    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    __table_args__ = (
        Index("ix_gnn_run_created_at", "created_at"),
        Index("ix_gnn_run_window_end", "window_end"),
        Index("ix_gnn_run_model_version", "model_version"),
    )


class AIRiskThreshold(Base):
    __tablename__ = "ai_risk_threshold"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    model_version = Column(String, nullable=False)
    prediction_type = Column(String, nullable=False)

    entity_type = Column(String, nullable=False)
    window_key = Column(String, nullable=False)
    window_end = Column(DateTime(timezone=True), nullable=False)

    threshold_score = Column(Float, nullable=False, default=75.0)  # 0..100
    method = Column(String, nullable=False, default="f1_weak_label")
    sample_count = Column(Integer, nullable=False, default=0)
    positive_count = Column(Integer, nullable=False, default=0)
    cost_weight = Column(Float, nullable=False, default=1.0)

    metrics_json = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    __table_args__ = (
        UniqueConstraint(
            "model_version",
            "prediction_type",
            "entity_type",
            "window_key",
            "window_end",
            name="uq_ai_risk_threshold",
        ),
        Index("ix_ai_risk_threshold_entity", "entity_type"),
        Index("ix_ai_risk_threshold_window_end", "window_end"),
    )


class AICampaignRiskIndicator(Base):
    __tablename__ = "ai_campaign_risk_indicator"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    campaign_id = Column(
        UUID(as_uuid=True),
        ForeignKey("campaign.id", ondelete="CASCADE"),
        nullable=False,
    )

    prediction_type = Column(String, nullable=False, default="risk_gnn")
    model_version = Column(String, nullable=False)
    window_key = Column(String, nullable=False)
    window_end = Column(DateTime(timezone=True), nullable=False)

    score = Column(Float, nullable=False, default=0.0)  # 0..100
    severity = Column(String, nullable=False, default="low")
    flagged_entity_count = Column(Integer, nullable=False, default=0)
    total_entity_count = Column(Integer, nullable=False, default=0)

    reason_codes = Column(JSONB, nullable=False, default=list)
    details_json = Column(JSONB, nullable=False, default=dict)
    evidence_entity_keys = Column(JSONB, nullable=False, default=list)

    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    __table_args__ = (
        UniqueConstraint(
            "campaign_id",
            "prediction_type",
            "window_key",
            "window_end",
            name="uq_ai_campaign_risk_indicator",
        ),
        Index("ix_ai_campaign_risk_score", "score"),
        Index("ix_ai_campaign_risk_window_end", "window_end"),
        Index("ix_ai_campaign_risk_campaign", "campaign_id"),
    )


class AIAttackTechniqueHit(Base):
    __tablename__ = "ai_attack_technique_hit"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entity_key = Column(String, nullable=False)
    prediction_type = Column(String, nullable=False)
    window_key = Column(String, nullable=False)
    window_end = Column(DateTime(timezone=True), nullable=False)
    technique_id = Column(String, nullable=False)
    tactic = Column(String, nullable=True)
    confidence = Column(Float, nullable=False, default=0.0)
    source_json = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    __table_args__ = (
        UniqueConstraint(
            "entity_key",
            "prediction_type",
            "window_key",
            "window_end",
            "technique_id",
            name="uq_ai_attack_technique_hit",
        ),
        Index("ix_ai_attack_technique_entity", "entity_key"),
        Index("ix_ai_attack_technique_window_end", "window_end"),
    )


class AIAttackPathScore(Base):
    __tablename__ = "ai_attack_path_score"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entity_key = Column(String, nullable=False)
    prediction_type = Column(String, nullable=False)
    window_key = Column(String, nullable=False)
    window_end = Column(DateTime(timezone=True), nullable=False)
    path_score = Column(Float, nullable=False, default=0.0)
    hop_count = Column(Integer, nullable=False, default=0)
    evidence_entity_keys = Column(JSONB, nullable=False, default=list)
    details_json = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    __table_args__ = (
        UniqueConstraint(
            "entity_key",
            "prediction_type",
            "window_key",
            "window_end",
            name="uq_ai_attack_path_score",
        ),
        Index("ix_ai_path_score_window_end", "window_end"),
    )


class AILinkPrediction(Base):
    __tablename__ = "ai_link_prediction"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    src_entity_key = Column(String, nullable=False)
    dst_entity_key = Column(String, nullable=False)
    prediction_type = Column(String, nullable=False)
    model_version = Column(String, nullable=False)
    window_key = Column(String, nullable=False)
    window_end = Column(DateTime(timezone=True), nullable=False)
    score = Column(Float, nullable=False, default=0.0)
    method = Column(String, nullable=False, default="embedding_cosine")
    details_json = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    __table_args__ = (
        UniqueConstraint(
            "src_entity_key",
            "dst_entity_key",
            "prediction_type",
            "model_version",
            "window_key",
            "window_end",
            name="uq_ai_link_prediction",
        ),
        Index("ix_ai_link_prediction_window_end", "window_end"),
        Index("ix_ai_link_prediction_score", "score"),
    )


class AIDecisionFusion(Base):
    __tablename__ = "ai_decision_fusion"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entity_key = Column(String, nullable=False)
    prediction_type = Column(String, nullable=False)
    window_key = Column(String, nullable=False)
    window_end = Column(DateTime(timezone=True), nullable=False)
    fused_score = Column(Float, nullable=False, default=0.0)
    severity = Column(String, nullable=False, default="low")
    decision = Column(String, nullable=False, default="review")
    selected_model_version = Column(String, nullable=True)
    signals_json = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    __table_args__ = (
        UniqueConstraint(
            "entity_key",
            "prediction_type",
            "window_key",
            "window_end",
            name="uq_ai_decision_fusion",
        ),
        Index("ix_ai_decision_fused_score", "fused_score"),
        Index("ix_ai_decision_window_end", "window_end"),
    )


class AIDriftReport(Base):
    __tablename__ = "ai_drift_report"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    model_version = Column(String, nullable=False)
    prediction_type = Column(String, nullable=False)
    window_key = Column(String, nullable=False)
    window_end = Column(DateTime(timezone=True), nullable=False)
    drift_score = Column(Float, nullable=False, default=0.0)
    status = Column(String, nullable=False, default="ok")
    metrics_json = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    __table_args__ = (
        UniqueConstraint(
            "model_version",
            "prediction_type",
            "window_key",
            "window_end",
            name="uq_ai_drift_report",
        ),
        Index("ix_ai_drift_status", "status"),
        Index("ix_ai_drift_window_end", "window_end"),
    )


class AIInputAnomalyAlert(Base):
    __tablename__ = "ai_input_anomaly_alert"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entity_key = Column(String, nullable=False)
    window_key = Column(String, nullable=False)
    window_end = Column(DateTime(timezone=True), nullable=False)
    anomaly_type = Column(String, nullable=False)
    score = Column(Float, nullable=False, default=0.0)
    details_json = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    __table_args__ = (
        Index("ix_ai_input_anomaly_entity", "entity_key"),
        Index("ix_ai_input_anomaly_window_end", "window_end"),
    )


class AIFeedbackLabel(Base):
    __tablename__ = "ai_feedback_label"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    prediction_id = Column(
        UUID(as_uuid=True),
        ForeignKey("ai_prediction.id", ondelete="CASCADE"),
        nullable=False,
    )
    entity_key = Column(String, nullable=False)
    feedback_label = Column(Integer, nullable=False)  # 0/1/2 where 2=uncertain
    analyst_id = Column(String, nullable=False)
    notes = Column(String, nullable=True)
    status = Column(String, nullable=False, default="queued")
    used_in_training = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    __table_args__ = (
        Index("ix_ai_feedback_prediction", "prediction_id"),
        Index("ix_ai_feedback_entity", "entity_key"),
        Index("ix_ai_feedback_status", "status"),
    )


class AIModelRollout(Base):
    __tablename__ = "ai_model_rollout"

    rollout_id = Column(String, primary_key=True)
    prediction_type = Column(String, nullable=False)
    active_model_version = Column(String, nullable=False)
    shadow_model_version = Column(String, nullable=True)
    rollout_mode = Column(String, nullable=False, default="single")  # single/shadow/canary
    canary_ratio = Column(Float, nullable=False, default=0.0)
    auto_rollback = Column(Boolean, nullable=False, default=True)
    min_sample_count = Column(Integer, nullable=False, default=500)
    status = Column(String, nullable=False, default="active")
    created_by = Column(String, nullable=False)
    metadata_json = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    __table_args__ = (
        Index("ix_ai_rollout_prediction_type", "prediction_type"),
        Index("ix_ai_rollout_status", "status"),
    )


class AIModelLineage(Base):
    __tablename__ = "ai_model_lineage"

    lineage_id = Column(String, primary_key=True)
    model_version = Column(String, nullable=False)
    prediction_type = Column(String, nullable=False)
    training_run_id = Column(UUID(as_uuid=True), ForeignKey("gnn_training_run.id", ondelete="SET NULL"), nullable=True)
    dataset_hash = Column(String, nullable=False)
    params_hash = Column(String, nullable=False)
    code_hash = Column(String, nullable=False)
    lineage_signature = Column(String, nullable=False)
    metadata_json = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    __table_args__ = (
        UniqueConstraint("model_version", "prediction_type", name="uq_ai_model_lineage"),
        Index("ix_ai_model_lineage_created", "created_at"),
    )


class EntityRiskBaseline(Base):
    __tablename__ = "entity_risk_baseline"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entity_key = Column(String, nullable=False)
    entity_type = Column(String, nullable=False)
    window_key = Column(String, nullable=False)
    baseline_score = Column(Float, nullable=False, default=0.0)
    baseline_std = Column(Float, nullable=False, default=0.0)
    sample_count = Column(Integer, nullable=False, default=0)
    last_window_end = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    __table_args__ = (
        UniqueConstraint("entity_key", "window_key", name="uq_entity_risk_baseline"),
        Index("ix_entity_risk_baseline_window_key", "window_key"),
    )


class ThreatIntelIndicator(Base):
    __tablename__ = "threat_intel_indicator"

    indicator_id = Column(String, primary_key=True)
    stix_id = Column(String, nullable=True, unique=True)
    indicator_type = Column(String, nullable=False)
    value = Column(String, nullable=False)
    confidence = Column(Float, nullable=False, default=0.5)
    source = Column(String, nullable=False, default="unknown")
    valid_from = Column(DateTime(timezone=True), nullable=True)
    valid_until = Column(DateTime(timezone=True), nullable=True)
    tags_json = Column(JSONB, nullable=False, default=list)
    metadata_json = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    __table_args__ = (
        UniqueConstraint("indicator_type", "value", name="uq_threat_intel_indicator_value"),
        Index("ix_threat_intel_indicator_type", "indicator_type"),
        Index("ix_threat_intel_source", "source"),
    )


class ThreatIntelSyncLog(Base):
    __tablename__ = "threat_intel_sync_log"

    sync_id = Column(String, primary_key=True)
    direction = Column(String, nullable=False)  # import/export
    connector = Column(String, nullable=False)
    status = Column(String, nullable=False)
    detail = Column(String, nullable=True)
    item_count = Column(Integer, nullable=False, default=0)
    started_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    metadata_json = Column(JSONB, nullable=False, default=dict)

    __table_args__ = (
        Index("ix_threat_sync_connector", "connector"),
        Index("ix_threat_sync_status", "status"),
        Index("ix_threat_sync_started", "started_at"),
    )

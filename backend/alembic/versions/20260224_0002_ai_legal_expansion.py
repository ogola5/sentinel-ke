"""expand ai, legal, and threat-intel schema

Revision ID: 20260224_0002
Revises: 20260215_0001
Create Date: 2026-02-24 12:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "20260224_0002"
down_revision = "20260215_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("entity_embedding", sa.Column("embedding_type", sa.String(), nullable=False, server_default="gnn"))

    op.add_column("ai_prediction", sa.Column("model_version", sa.String(), nullable=False, server_default="unknown"))
    op.add_column("ai_prediction", sa.Column("confidence", sa.Float(), nullable=False, server_default="0"))
    op.add_column("ai_prediction", sa.Column("uncertainty", sa.Float(), nullable=False, server_default="1"))
    op.add_column("ai_prediction", sa.Column("abstained", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("ai_prediction", sa.Column("kill_chain_stage", sa.String(), nullable=True))
    op.add_column("ai_prediction", sa.Column("decision_source", sa.String(), nullable=False, server_default="model"))

    op.create_index("ix_ai_pred_model_version", "ai_prediction", ["model_version"], unique=False)

    op.add_column(
        "ai_explanation",
        sa.Column("recommended_controls_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
    )
    op.add_column(
        "ai_explanation",
        sa.Column("counterfactual_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )

    op.add_column("ai_risk_threshold", sa.Column("cost_weight", sa.Float(), nullable=False, server_default="1"))

    op.create_table(
        "ai_attack_technique_hit",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("entity_key", sa.String(), nullable=False),
        sa.Column("prediction_type", sa.String(), nullable=False),
        sa.Column("window_key", sa.String(), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("technique_id", sa.String(), nullable=False),
        sa.Column("tactic", sa.String(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("source_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "entity_key",
            "prediction_type",
            "window_key",
            "window_end",
            "technique_id",
            name="uq_ai_attack_technique_hit",
        ),
    )
    op.create_index("ix_ai_attack_technique_entity", "ai_attack_technique_hit", ["entity_key"], unique=False)
    op.create_index("ix_ai_attack_technique_window_end", "ai_attack_technique_hit", ["window_end"], unique=False)

    op.create_table(
        "ai_attack_path_score",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("entity_key", sa.String(), nullable=False),
        sa.Column("prediction_type", sa.String(), nullable=False),
        sa.Column("window_key", sa.String(), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("path_score", sa.Float(), nullable=False),
        sa.Column("hop_count", sa.Integer(), nullable=False),
        sa.Column("evidence_entity_keys", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("details_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "entity_key", "prediction_type", "window_key", "window_end", name="uq_ai_attack_path_score"
        ),
    )
    op.create_index("ix_ai_path_score_window_end", "ai_attack_path_score", ["window_end"], unique=False)

    op.create_table(
        "ai_link_prediction",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("src_entity_key", sa.String(), nullable=False),
        sa.Column("dst_entity_key", sa.String(), nullable=False),
        sa.Column("prediction_type", sa.String(), nullable=False),
        sa.Column("model_version", sa.String(), nullable=False),
        sa.Column("window_key", sa.String(), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("method", sa.String(), nullable=False),
        sa.Column("details_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "src_entity_key",
            "dst_entity_key",
            "prediction_type",
            "model_version",
            "window_key",
            "window_end",
            name="uq_ai_link_prediction",
        ),
    )
    op.create_index("ix_ai_link_prediction_window_end", "ai_link_prediction", ["window_end"], unique=False)
    op.create_index("ix_ai_link_prediction_score", "ai_link_prediction", ["score"], unique=False)

    op.create_table(
        "ai_decision_fusion",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("entity_key", sa.String(), nullable=False),
        sa.Column("prediction_type", sa.String(), nullable=False),
        sa.Column("window_key", sa.String(), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fused_score", sa.Float(), nullable=False),
        sa.Column("severity", sa.String(), nullable=False),
        sa.Column("decision", sa.String(), nullable=False),
        sa.Column("selected_model_version", sa.String(), nullable=True),
        sa.Column("signals_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "entity_key", "prediction_type", "window_key", "window_end", name="uq_ai_decision_fusion"
        ),
    )
    op.create_index("ix_ai_decision_fused_score", "ai_decision_fusion", ["fused_score"], unique=False)
    op.create_index("ix_ai_decision_window_end", "ai_decision_fusion", ["window_end"], unique=False)

    op.create_table(
        "ai_drift_report",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("model_version", sa.String(), nullable=False),
        sa.Column("prediction_type", sa.String(), nullable=False),
        sa.Column("window_key", sa.String(), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("drift_score", sa.Float(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("metrics_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "model_version", "prediction_type", "window_key", "window_end", name="uq_ai_drift_report"
        ),
    )
    op.create_index("ix_ai_drift_status", "ai_drift_report", ["status"], unique=False)
    op.create_index("ix_ai_drift_window_end", "ai_drift_report", ["window_end"], unique=False)

    op.create_table(
        "ai_input_anomaly_alert",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("entity_key", sa.String(), nullable=False),
        sa.Column("window_key", sa.String(), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("anomaly_type", sa.String(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("details_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_input_anomaly_entity", "ai_input_anomaly_alert", ["entity_key"], unique=False)
    op.create_index("ix_ai_input_anomaly_window_end", "ai_input_anomaly_alert", ["window_end"], unique=False)

    op.create_table(
        "ai_feedback_label",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("prediction_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("entity_key", sa.String(), nullable=False),
        sa.Column("feedback_label", sa.Integer(), nullable=False),
        sa.Column("analyst_id", sa.String(), nullable=False),
        sa.Column("notes", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("used_in_training", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["prediction_id"], ["ai_prediction.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_feedback_prediction", "ai_feedback_label", ["prediction_id"], unique=False)
    op.create_index("ix_ai_feedback_entity", "ai_feedback_label", ["entity_key"], unique=False)
    op.create_index("ix_ai_feedback_status", "ai_feedback_label", ["status"], unique=False)

    op.create_table(
        "ai_model_rollout",
        sa.Column("rollout_id", sa.String(), nullable=False),
        sa.Column("prediction_type", sa.String(), nullable=False),
        sa.Column("active_model_version", sa.String(), nullable=False),
        sa.Column("shadow_model_version", sa.String(), nullable=True),
        sa.Column("rollout_mode", sa.String(), nullable=False),
        sa.Column("canary_ratio", sa.Float(), nullable=False),
        sa.Column("auto_rollback", sa.Boolean(), nullable=False),
        sa.Column("min_sample_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("rollout_id"),
    )
    op.create_index("ix_ai_rollout_prediction_type", "ai_model_rollout", ["prediction_type"], unique=False)
    op.create_index("ix_ai_rollout_status", "ai_model_rollout", ["status"], unique=False)

    op.create_table(
        "ai_model_lineage",
        sa.Column("lineage_id", sa.String(), nullable=False),
        sa.Column("model_version", sa.String(), nullable=False),
        sa.Column("prediction_type", sa.String(), nullable=False),
        sa.Column("training_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("dataset_hash", sa.String(), nullable=False),
        sa.Column("params_hash", sa.String(), nullable=False),
        sa.Column("code_hash", sa.String(), nullable=False),
        sa.Column("lineage_signature", sa.String(), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["training_run_id"], ["gnn_training_run.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("lineage_id"),
        sa.UniqueConstraint("model_version", "prediction_type", name="uq_ai_model_lineage"),
    )
    op.create_index("ix_ai_model_lineage_created", "ai_model_lineage", ["created_at"], unique=False)

    op.create_table(
        "entity_risk_baseline",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("entity_key", sa.String(), nullable=False),
        sa.Column("entity_type", sa.String(), nullable=False),
        sa.Column("window_key", sa.String(), nullable=False),
        sa.Column("baseline_score", sa.Float(), nullable=False),
        sa.Column("baseline_std", sa.Float(), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("last_window_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("entity_key", "window_key", name="uq_entity_risk_baseline"),
    )
    op.create_index("ix_entity_risk_baseline_window_key", "entity_risk_baseline", ["window_key"], unique=False)

    op.create_table(
        "threat_intel_indicator",
        sa.Column("indicator_id", sa.String(), nullable=False),
        sa.Column("stix_id", sa.String(), nullable=True),
        sa.Column("indicator_type", sa.String(), nullable=False),
        sa.Column("value", sa.String(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tags_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("indicator_id"),
        sa.UniqueConstraint("indicator_type", "value", name="uq_threat_intel_indicator_value"),
        sa.UniqueConstraint("stix_id"),
    )
    op.create_index("ix_threat_intel_indicator_type", "threat_intel_indicator", ["indicator_type"], unique=False)
    op.create_index("ix_threat_intel_source", "threat_intel_indicator", ["source"], unique=False)

    op.create_table(
        "threat_intel_sync_log",
        sa.Column("sync_id", sa.String(), nullable=False),
        sa.Column("direction", sa.String(), nullable=False),
        sa.Column("connector", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("detail", sa.String(), nullable=True),
        sa.Column("item_count", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("sync_id"),
    )
    op.create_index("ix_threat_sync_connector", "threat_intel_sync_log", ["connector"], unique=False)
    op.create_index("ix_threat_sync_status", "threat_intel_sync_log", ["status"], unique=False)
    op.create_index("ix_threat_sync_started", "threat_intel_sync_log", ["started_at"], unique=False)

    op.add_column("legal_authorization_grant", sa.Column("policy_version", sa.String(), nullable=False, server_default="v1"))
    op.add_column(
        "legal_authorization_grant",
        sa.Column("model_action_scope_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )

    op.create_table(
        "legal_evidence_certificate",
        sa.Column("certificate_id", sa.String(), nullable=False),
        sa.Column("bundle_id", sa.String(), nullable=False),
        sa.Column("framework", sa.String(), nullable=False),
        sa.Column("jurisdiction", sa.String(), nullable=False),
        sa.Column("statement_hash", sa.String(), nullable=False),
        sa.Column("signed_by", sa.String(), nullable=False),
        sa.Column("signature_method", sa.String(), nullable=False),
        sa.Column("signature", sa.String(), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["bundle_id"], ["legal_evidence_bundle.bundle_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("certificate_id"),
        sa.UniqueConstraint("bundle_id"),
        sa.UniqueConstraint("statement_hash"),
    )
    op.create_index("ix_legal_certificate_bundle", "legal_evidence_certificate", ["bundle_id"], unique=False)
    op.create_index("ix_legal_certificate_created", "legal_evidence_certificate", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_legal_certificate_created", table_name="legal_evidence_certificate")
    op.drop_index("ix_legal_certificate_bundle", table_name="legal_evidence_certificate")
    op.drop_table("legal_evidence_certificate")

    op.drop_column("legal_authorization_grant", "model_action_scope_json")
    op.drop_column("legal_authorization_grant", "policy_version")

    op.drop_index("ix_threat_sync_started", table_name="threat_intel_sync_log")
    op.drop_index("ix_threat_sync_status", table_name="threat_intel_sync_log")
    op.drop_index("ix_threat_sync_connector", table_name="threat_intel_sync_log")
    op.drop_table("threat_intel_sync_log")

    op.drop_index("ix_threat_intel_source", table_name="threat_intel_indicator")
    op.drop_index("ix_threat_intel_indicator_type", table_name="threat_intel_indicator")
    op.drop_table("threat_intel_indicator")

    op.drop_index("ix_entity_risk_baseline_window_key", table_name="entity_risk_baseline")
    op.drop_table("entity_risk_baseline")

    op.drop_index("ix_ai_model_lineage_created", table_name="ai_model_lineage")
    op.drop_table("ai_model_lineage")

    op.drop_index("ix_ai_rollout_status", table_name="ai_model_rollout")
    op.drop_index("ix_ai_rollout_prediction_type", table_name="ai_model_rollout")
    op.drop_table("ai_model_rollout")

    op.drop_index("ix_ai_feedback_status", table_name="ai_feedback_label")
    op.drop_index("ix_ai_feedback_entity", table_name="ai_feedback_label")
    op.drop_index("ix_ai_feedback_prediction", table_name="ai_feedback_label")
    op.drop_table("ai_feedback_label")

    op.drop_index("ix_ai_input_anomaly_window_end", table_name="ai_input_anomaly_alert")
    op.drop_index("ix_ai_input_anomaly_entity", table_name="ai_input_anomaly_alert")
    op.drop_table("ai_input_anomaly_alert")

    op.drop_index("ix_ai_drift_window_end", table_name="ai_drift_report")
    op.drop_index("ix_ai_drift_status", table_name="ai_drift_report")
    op.drop_table("ai_drift_report")

    op.drop_index("ix_ai_decision_window_end", table_name="ai_decision_fusion")
    op.drop_index("ix_ai_decision_fused_score", table_name="ai_decision_fusion")
    op.drop_table("ai_decision_fusion")

    op.drop_index("ix_ai_link_prediction_score", table_name="ai_link_prediction")
    op.drop_index("ix_ai_link_prediction_window_end", table_name="ai_link_prediction")
    op.drop_table("ai_link_prediction")

    op.drop_index("ix_ai_path_score_window_end", table_name="ai_attack_path_score")
    op.drop_table("ai_attack_path_score")

    op.drop_index("ix_ai_attack_technique_window_end", table_name="ai_attack_technique_hit")
    op.drop_index("ix_ai_attack_technique_entity", table_name="ai_attack_technique_hit")
    op.drop_table("ai_attack_technique_hit")

    op.drop_column("ai_risk_threshold", "cost_weight")

    op.drop_column("ai_explanation", "counterfactual_json")
    op.drop_column("ai_explanation", "recommended_controls_json")

    op.drop_index("ix_ai_pred_model_version", table_name="ai_prediction")
    op.drop_column("ai_prediction", "decision_source")
    op.drop_column("ai_prediction", "kill_chain_stage")
    op.drop_column("ai_prediction", "abstained")
    op.drop_column("ai_prediction", "uncertainty")
    op.drop_column("ai_prediction", "confidence")
    op.drop_column("ai_prediction", "model_version")

    op.drop_column("entity_embedding", "embedding_type")

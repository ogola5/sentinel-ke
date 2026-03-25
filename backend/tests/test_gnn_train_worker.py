import os
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.analytics.ai_models import (
    AIPrediction,
    AIExplanation,
    AICampaignRiskIndicator,
    AIRiskThreshold,
    EntityEmbedding,
    GNNTrainingRun,
)
from app.analytics.layer3.gnn_backbone import GNNDataset
from app.analytics.layer3.gnn_model import GNNTrainResult
from app.analytics.layer3 import gnn_train_worker
from app.campaign.models import Campaign, CampaignEntity
from app.db import registry as _  # noqa: F401
from app.db.base import Base


TEST_DB_URL_ENV = "TEST_DATABASE_URL"


def _session():
    url = os.environ.get(TEST_DB_URL_ENV)
    if not url:
        pytest.skip(f"{TEST_DB_URL_ENV} not set (expected a Postgres URL for integration test)")
    engine = create_engine(url)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    return Session()


def test_gnn_train_worker_persists_outputs(monkeypatch):
    db = _session()
    try:
        db.query(AIExplanation).delete()
        db.query(AIPrediction).delete()
        db.query(AICampaignRiskIndicator).delete()
        db.query(AIRiskThreshold).delete()
        db.query(CampaignEntity).delete()
        db.query(Campaign).delete()
        db.query(EntityEmbedding).delete()
        db.query(GNNTrainingRun).delete()
        db.commit()

        now = datetime.now(timezone.utc)
        dataset = GNNDataset(
            window_key="Wmid",
            window_start=now,
            window_end=now,
            entity_keys=["account_h:a1", "account_h:a2", "service_id:s1"],
            entity_types=["account_h", "account_h", "service_id"],
            feature_matrix=[
                [2.0, 2.0, 0.7, 1, 0, 0, 0, 1, 0, 0, 0, 0],
                [1.7, 1.8, 0.6, 0, 1, 0, 0, 0, 1, 0, 0, 0],
                [2.5, 2.1, 0.8, 1, 0, 1, 0, 1, 0, 0, 0, 0],
            ],
            labels=[1, 0, 1],
            edges=[(0, 1, 2.0), (1, 2, 1.0)],
            node_meta=[
                {
                    "risk_flags": ["DDOS_ALERT_SERVICE"],
                    "event_count": 18,
                    "source_count": 3,
                    "event_types": {},
                    "is_benign_negative": False,
                },
                {
                    "risk_flags": [],
                    "event_count": 4,
                    "source_count": 1,
                    "event_types": {},
                    "is_benign_negative": True,
                },
                {
                    "risk_flags": ["CAMPAIGN_ENTITY"],
                    "event_count": 25,
                    "source_count": 4,
                    "event_types": {},
                    "is_benign_negative": False,
                },
            ],
            source_backend_used="hybrid",
            edge_source_counts={"neo4j": 2, "postgres": 1},
            positive_count=2,
            negative_count=1,
            benign_negative_count=1,
            selection_metadata={
                "selection_strategy": "latest_available_window_fallback",
                "benchmark_readiness": {
                    "benchmarkable": False,
                    "reasons": ["negative_floor_not_met"],
                    "minimum_negative_count": 5,
                    "minimum_negative_ratio": 0.1,
                },
            },
        )

        fake_train = GNNTrainResult(
            embeddings=[[0.1, 0.2], [0.2, 0.3], [0.4, 0.5]],
            probabilities=[0.9, 0.2, 0.85],
            predicted_labels=[1, 0, 1],
            metrics={"auc": 0.91, "precision": 1.0, "recall": 1.0, "f1": 1.0, "train_loss": 0.12, "val_loss": 0.2},
            model_state={},
        )

        monkeypatch.setattr(gnn_train_worker, "load_dataset", lambda *args, **kwargs: dataset)
        monkeypatch.setattr(gnn_train_worker, "train_graphsage", lambda *args, **kwargs: fake_train)
        monkeypatch.setattr(gnn_train_worker, "_persist_artifact", lambda **kwargs: "/tmp/gnn/model.pt")
        monkeypatch.setattr(gnn_train_worker, "recent_entity_event_hashes", lambda *args, **kwargs: ["e1", "e2"])
        monkeypatch.setattr(
            gnn_train_worker,
            "build_entity_graph_paths",
            lambda *args, **kwargs: [{"path": ["account_h:a1", "service_id:s1"], "hop_count": 1, "shared_events": 2}],
        )
        monkeypatch.setattr(
            gnn_train_worker,
            "run_post_prediction_pipeline",
            lambda **kwargs: {"path_scores_upserted": 3, "decision_fusions_upserted": 3},
        )

        out = gnn_train_worker.run_once(
            db=db,
            window_key="Wmid",
            model_version="gnn-sage-v1",
            prediction_type="risk_gnn",
            artifact_dir="/tmp/gnn",
            component_discovery_enabled=True,
            component_min_size=3,
            component_min_indicator_ratio=0.5,
        )

        assert out["status"] == "ok"
        assert out["predictions_created"] == 3
        assert out["embeddings_upserted"] == 3
        assert out["thresholds_upserted"] >= 1
        assert out["campaign_indicators_created"] >= 0
        assert out["component_campaigns_created"] >= 1
        assert out["component_entities_upserted"] >= 3

        runs = db.query(GNNTrainingRun).all()
        assert len(runs) == 1
        assert runs[0].auc == 0.91
        assert runs[0].metrics_json["evaluation_protocol"]["benchmarkable"] is False
        assert runs[0].metrics_json["evaluation_protocol"]["holdout_policy"] == "temporal_recency_holdout"
        assert runs[0].metrics_json["label_strategy"]["label_ladder"]["tier_counts"]["bronze"] >= 1

        preds = db.query(AIPrediction).filter(AIPrediction.prediction_type == "risk_gnn").all()
        assert len(preds) == 3
        assert all("legal_notice" in (p.details_json or {}) for p in preds)
        assert all("RISK_INDICATOR_ONLY_NOT_FINAL_PROOF" in (p.reason_codes or []) for p in preds)

        expl = db.query(AIExplanation).all()
        assert len(expl) == 3
        assert all("legal_notice" in (e.details_json or {}) for e in expl)
        assert all((e.evidence_paths or []) for e in expl)

        emb = db.query(EntityEmbedding).filter(EntityEmbedding.model_version == "gnn-sage-v1").all()
        assert len(emb) == 3

        th = db.query(AIRiskThreshold).all()
        assert len(th) >= 1

        comp = db.query(Campaign).filter(Campaign.type == "GNN_COMPONENT").all()
        assert len(comp) >= 1
        members = db.query(CampaignEntity).filter(CampaignEntity.campaign_id == comp[0].id).all()
        assert len(members) == 3
    finally:
        db.close()

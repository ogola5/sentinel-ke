import os
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.analytics.ai_models import AIPrediction, AIExplanation, EntityEmbedding, GNNTrainingRun
from app.analytics.layer3.gnn_backbone import GNNDataset
from app.analytics.layer3.gnn_model import GNNTrainResult
from app.analytics.layer3 import gnn_train_worker
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
                {"risk_flags": ["DDOS_ALERT_SERVICE"], "event_count": 18, "source_count": 3, "event_types": {}},
                {"risk_flags": [], "event_count": 4, "source_count": 1, "event_types": {}},
                {"risk_flags": ["CAMPAIGN_ENTITY"], "event_count": 25, "source_count": 4, "event_types": {}},
            ],
            source_backend_used="hybrid",
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

        out = gnn_train_worker.run_once(
            db=db,
            window_key="Wmid",
            model_version="gnn-sage-v1",
            prediction_type="risk_gnn",
            artifact_dir="/tmp/gnn",
        )

        assert out["status"] == "ok"
        assert out["predictions_created"] == 3
        assert out["embeddings_upserted"] == 3

        runs = db.query(GNNTrainingRun).all()
        assert len(runs) == 1
        assert runs[0].auc == 0.91

        preds = db.query(AIPrediction).filter(AIPrediction.prediction_type == "risk_gnn").all()
        assert len(preds) == 3

        expl = db.query(AIExplanation).all()
        assert len(expl) == 3

        emb = db.query(EntityEmbedding).filter(EntityEmbedding.model_version == "gnn-sage-v1").all()
        assert len(emb) == 3
    finally:
        db.close()

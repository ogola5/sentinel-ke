from datetime import datetime, timezone

from app.analytics.layer3.gnn_backbone import GNNDataset
from app.analytics.layer3.gnn_train_worker import _calibrate_thresholds


def test_calibrate_thresholds_per_entity_type():
    now = datetime.now(timezone.utc)
    dataset = GNNDataset(
        window_key="Wmid",
        window_start=now,
        window_end=now,
        entity_keys=["ip:a", "ip:b", "ip:c", "account_h:x", "account_h:y"],
        entity_types=["ip", "ip", "ip", "account_h", "account_h"],
        feature_matrix=[[0.0] * 12 for _ in range(5)],
        labels=[1, 1, 0, 1, 0],
        edges=[(0, 1, 1.0)],
        node_meta=[{} for _ in range(5)],
        source_backend_used="synthetic",
    )

    probs = [0.92, 0.85, 0.30, 0.72, 0.20]
    out = _calibrate_thresholds(
        dataset=dataset,
        probabilities=probs,
        min_samples=3,
        model_version="gnn-sage-v1",
        prediction_type="risk_gnn",
    )

    assert "ip" in out
    assert out["ip"]["method"] == "f1_weak_label"
    assert 30.0 <= float(out["ip"]["threshold_score"]) <= 95.0

    # account_h has only 2 samples -> default threshold method
    assert "account_h" in out
    assert out["account_h"]["method"] == "default_by_entity_type"
    assert float(out["account_h"]["threshold_score"]) == 70.0

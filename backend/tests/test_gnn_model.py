from datetime import datetime, timezone

import pytest

from app.analytics.layer3.gnn_backbone import GNNDataset
from app.analytics.layer3.gnn_model import train_graphsage


def test_train_graphsage_on_synthetic_graph():
    pytest.importorskip("torch")

    now = datetime.now(timezone.utc)
    dataset = GNNDataset(
        window_key="Wmid",
        window_start=now,
        window_end=now,
        entity_keys=[f"node:{i}" for i in range(8)],
        entity_types=["node"] * 8,
        feature_matrix=[
            [3.0, 2.0, 0.9, 1, 1, 0, 0, 1, 0, 1, 0, 0],
            [2.8, 2.1, 0.8, 1, 1, 0, 0, 1, 0, 1, 0, 0],
            [2.7, 1.8, 0.7, 1, 0, 1, 0, 0, 0, 1, 0, 0],
            [0.9, 0.7, 0.2, 0, 0, 0, 0, 0, 1, 0, 1, 0],
            [0.8, 0.6, 0.2, 0, 0, 0, 0, 0, 1, 0, 1, 0],
            [0.7, 0.5, 0.1, 0, 0, 0, 0, 0, 1, 0, 1, 0],
            [1.0, 0.8, 0.3, 0, 0, 1, 0, 0, 0, 1, 0, 0],
            [0.9, 0.9, 0.2, 0, 0, 1, 0, 0, 0, 1, 0, 0],
        ],
        labels=[1, 1, 1, 0, 0, 0, 0, 0],
        edges=[
            (0, 1, 4.0),
            (1, 2, 3.0),
            (0, 2, 2.0),
            (3, 4, 3.0),
            (4, 5, 3.0),
            (6, 7, 2.0),
            (2, 6, 1.0),
        ],
        node_meta=[{} for _ in range(8)],
        source_backend_used="synthetic",
    )

    out = train_graphsage(dataset, epochs=25, hidden_dim=16, embed_dim=8, seed=11)
    assert len(out.embeddings) == 8
    assert len(out.embeddings[0]) == 8
    assert len(out.probabilities) == 8
    assert "auc" in out.metrics
    assert 0.0 <= out.metrics["auc"] <= 1.0

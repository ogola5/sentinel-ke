from datetime import datetime, timezone

import pytest

from app.analytics.layer3.gnn_backbone import GNNDataset
from app.analytics.layer3.gnn_model import (
    build_sentinel_gnn,
    integrated_gradients_attributions,
    train_graphsage,
)


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
    assert "ece" in out.metrics
    assert "brier" in out.metrics
    assert "calibration_ece" in out.metrics
    assert "brier_score" in out.metrics
    assert out.metrics["split_policy"] in {"entity_hash_holdout", "random", "temporal_recency_holdout"}
    assert 0.0 <= out.metrics["auc"] <= 1.0
    assert 0.0 <= out.metrics["ece"] <= 1.0
    assert 0.0 <= out.metrics["brier"] <= 1.0
    assert 0.0 <= out.metrics["calibration_ece"] <= 1.0
    assert 0.0 <= out.metrics["brier_score"] <= 1.0


def test_train_graphsage_entity_holdout_is_deterministic():
    pytest.importorskip("torch")

    now = datetime.now(timezone.utc)
    dataset = GNNDataset(
        window_key="Wmid",
        window_start=now,
        window_end=now,
        entity_keys=[f"node:{i}" for i in range(20)],
        entity_types=["node"] * 20,
        feature_matrix=[[float(i % 5), float(i % 3), 0.1 * (i % 2)] for i in range(20)],
        labels=[1 if i % 4 == 0 else 0 for i in range(20)],
        edges=[(i, (i + 1) % 20, 1.0) for i in range(20)],
        node_meta=[{} for _ in range(20)],
        source_backend_used="synthetic",
    )

    a = train_graphsage(dataset, epochs=5, hidden_dim=8, embed_dim=4, seed=13, split_policy="entity_hash_holdout")
    b = train_graphsage(dataset, epochs=5, hidden_dim=8, embed_dim=4, seed=13, split_policy="entity_hash_holdout")
    assert a.metrics["val_count"] == b.metrics["val_count"]
    assert a.metrics["split_policy"] == "entity_hash_holdout"



def test_integrated_gradients_returns_feature_vectors():
    torch = pytest.importorskip("torch")

    model = build_sentinel_gnn(feat_dim=4, hidden_dim=8, embed_dim=4, dropout=0.1)
    x = torch.tensor(
        [
            [0.9, 0.1, 0.0, 0.2],
            [0.1, 0.8, 0.3, 0.1],
        ],
        dtype=torch.float32,
    )
    edge_src = torch.tensor([0, 1, 0, 1], dtype=torch.long)
    edge_dst = torch.tensor([0, 1, 1, 0], dtype=torch.long)
    edge_weight = torch.tensor([1.0, 1.0, 1.0, 1.0], dtype=torch.float32)

    attrs = integrated_gradients_attributions(
        model,
        x,
        edge_src,
        edge_dst,
        edge_weight,
        node_indices=[0, 1],
        steps=10,
        max_nodes=2,
    )

    assert set(attrs.keys()) == {0, 1}
    assert len(attrs[0]) == 4
    assert len(attrs[1]) == 4
    assert all(isinstance(v, float) for v in attrs[0])

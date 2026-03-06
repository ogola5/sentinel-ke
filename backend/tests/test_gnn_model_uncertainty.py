from datetime import datetime, timezone

import pytest

from app.analytics.layer3.gnn_backbone import GNNDataset
from app.analytics.layer3.gnn_model import (
    build_sentinel_gnn,
    gradient_x_input_attributions,
    train_graphsage,
)


def test_train_graphsage_returns_uncertainty_vector():
    pytest.importorskip("torch")

    now = datetime.now(timezone.utc)
    dataset = GNNDataset(
        window_key="Wmid",
        window_start=now,
        window_end=now,
        entity_keys=[f"node:{i}" for i in range(6)],
        entity_types=["node"] * 6,
        feature_matrix=[
            [2.0, 1.0, 0.8, 1, 0, 0, 0, 1, 0, 0, 0, 0],
            [2.1, 1.2, 0.7, 1, 0, 0, 0, 1, 0, 0, 0, 0],
            [1.9, 1.1, 0.75, 1, 0, 0, 0, 1, 0, 0, 0, 0],
            [0.8, 0.7, 0.2, 0, 0, 0, 0, 0, 1, 0, 1, 0],
            [0.7, 0.6, 0.2, 0, 0, 0, 0, 0, 1, 0, 1, 0],
            [0.9, 0.8, 0.3, 0, 0, 0, 0, 0, 1, 0, 1, 0],
        ],
        labels=[1, 1, 1, 0, 0, 0],
        edges=[(0, 1, 2.0), (1, 2, 1.5), (3, 4, 2.0), (4, 5, 1.0), (2, 3, 0.5)],
        node_meta=[{} for _ in range(6)],
        source_backend_used="synthetic",
    )

    out = train_graphsage(dataset, epochs=20, hidden_dim=12, embed_dim=6, seed=9, pretrain_epochs=2)
    assert out.uncertainties is not None
    assert len(out.uncertainties) == len(out.probabilities)
    assert all(0.0 <= float(v) <= 1.0 for v in out.uncertainties)
    assert "pretrain_loss" in out.metrics


def test_gradient_x_input_attributions_returns_feature_vector():
    torch = pytest.importorskip("torch")
    model = build_sentinel_gnn(4, hidden_dim=8, embed_dim=4, dropout=0.1)

    x = torch.tensor(
        [
            [1.0, 0.5, 0.1, 0.0],
            [0.9, 0.3, 0.0, 0.2],
            [0.1, 0.2, 0.8, 0.6],
        ],
        dtype=torch.float32,
    )
    edge_src = torch.tensor([0, 1, 1, 2, 0, 1, 2], dtype=torch.long)
    edge_dst = torch.tensor([1, 0, 2, 1, 0, 1, 2], dtype=torch.long)
    edge_w = torch.tensor([1.0] * len(edge_src), dtype=torch.float32)

    out = gradient_x_input_attributions(
        model,
        x,
        edge_src,
        edge_dst,
        edge_w,
        node_indices=[0, 2],
        max_nodes=1,
    )
    assert len(out) == 1
    idx = next(iter(out.keys()))
    assert idx in {0, 2}
    assert len(out[idx]) == 4

from __future__ import annotations

from dataclasses import dataclass
import math
import random
from typing import Any, Dict, List, Sequence, Tuple

from app.analytics.layer3.gnn_backbone import GNNDataset


@dataclass(frozen=True)
class GNNTrainResult:
    embeddings: List[List[float]]
    probabilities: List[float]
    predicted_labels: List[int]
    metrics: Dict[str, float]
    model_state: Dict[str, Any]
    uncertainties: List[float] | None = None


def _require_torch():
    try:
        import torch  # noqa: F401

        return torch
    except Exception as e:  # pragma: no cover - env dependent
        raise RuntimeError(
            "PyTorch is required for GNN training. Install dependencies from backend/requirements.txt"
        ) from e


def _auc_from_scores(labels: Sequence[int], scores: Sequence[float]) -> float:
    pairs = [(int(y), float(s)) for y, s in zip(labels, scores)]
    pos = [p for p in pairs if p[0] == 1]
    neg = [p for p in pairs if p[0] == 0]
    if not pos or not neg:
        return 0.5

    wins = 0.0
    total = float(len(pos) * len(neg))
    for py, ps in pos:
        for ny, ns in neg:
            if ps > ns:
                wins += 1.0
            elif ps == ns:
                wins += 0.5
    return wins / total if total > 0 else 0.5


def _binary_metrics(labels: Sequence[int], probs: Sequence[float], threshold: float = 0.5) -> Dict[str, float]:
    y_true = [int(v) for v in labels]
    y_pred = [1 if float(p) >= threshold else 0 for p in probs]

    tp = sum(1 for yt, yp in zip(y_true, y_pred) if yt == 1 and yp == 1)
    tn = sum(1 for yt, yp in zip(y_true, y_pred) if yt == 0 and yp == 0)
    fp = sum(1 for yt, yp in zip(y_true, y_pred) if yt == 0 and yp == 1)
    fn = sum(1 for yt, yp in zip(y_true, y_pred) if yt == 1 and yp == 0)

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
    acc = (tp + tn) / max(1, len(y_true))

    return {
        "accuracy": round(acc, 6),
        "precision": round(precision, 6),
        "recall": round(recall, 6),
        "f1": round(f1, 6),
        "auc": round(_auc_from_scores(y_true, probs), 6),
    }


def _sanitize_feature_matrix(matrix: Sequence[Sequence[float]]) -> List[List[float]]:
    cleaned: List[List[float]] = []
    for row in matrix:
        out_row: List[float] = []
        for v in row:
            fv = float(v)
            if not math.isfinite(fv):
                fv = 0.0
            out_row.append(fv)
        cleaned.append(out_row)
    return cleaned


def train_graphsage(
    dataset: GNNDataset,
    *,
    epochs: int = 60,
    hidden_dim: int = 64,
    embed_dim: int = 32,
    dropout: float = 0.2,
    learning_rate: float = 1e-3,
    weight_decay: float = 1e-4,
    seed: int = 7,
    grad_clip: float | None = 5.0,
    temporal_decay: float = 0.0,
    pretrain_epochs: int = 0,
) -> GNNTrainResult:
    torch = _require_torch()
    import torch.nn as nn

    random.seed(seed)
    torch.manual_seed(seed)
    try:
        torch.use_deterministic_algorithms(True)
    except Exception:
        pass

    if not dataset.feature_matrix:
        raise ValueError("dataset has no feature rows")

    n_nodes = len(dataset.feature_matrix)
    if len(dataset.labels) != n_nodes:
        raise ValueError("dataset labels length does not match feature rows")
    if len(dataset.entity_keys) != n_nodes:
        raise ValueError("dataset entity_keys length does not match feature rows")

    feat_dim = len(dataset.feature_matrix[0])
    if feat_dim <= 0:
        raise ValueError("dataset features have zero dimension")
    for row in dataset.feature_matrix:
        if len(row) != feat_dim:
            raise ValueError("dataset feature rows have inconsistent lengths")

    feature_matrix = _sanitize_feature_matrix(dataset.feature_matrix)
    x = torch.tensor(feature_matrix, dtype=torch.float32)
    y = torch.tensor([float(v) for v in dataset.labels], dtype=torch.float32).view(-1, 1)

    src_idx: List[int] = []
    dst_idx: List[int] = []
    edge_w: List[float] = []

    for i, j, w in dataset.edges:
        ew = max(0.0, float(w))
        ew = math.log1p(ew)
        if temporal_decay > 0:
            ew = ew * math.exp(-float(temporal_decay) * min(10.0, ew))
        src_idx.append(i)
        dst_idx.append(j)
        edge_w.append(ew)
        src_idx.append(j)
        dst_idx.append(i)
        edge_w.append(ew)

    for i in range(n_nodes):
        src_idx.append(i)
        dst_idx.append(i)
        edge_w.append(1.0)

    edge_src = torch.tensor(src_idx, dtype=torch.long)
    edge_dst = torch.tensor(dst_idx, dtype=torch.long)
    edge_weight = torch.tensor(edge_w, dtype=torch.float32)

    class GraphSAGELayer(nn.Module):
        def __init__(self, in_dim: int, out_dim: int):
            super().__init__()
            self.lin_self = nn.Linear(in_dim, out_dim)
            self.lin_neigh = nn.Linear(in_dim, out_dim)

        def forward(self, feats: torch.Tensor) -> torch.Tensor:
            neigh = torch.zeros_like(feats)
            neigh.index_add_(0, edge_dst, feats[edge_src] * edge_weight.unsqueeze(1))

            deg = torch.zeros((n_nodes, 1), dtype=feats.dtype, device=feats.device)
            deg.index_add_(0, edge_dst, edge_weight.view(-1, 1))
            neigh = neigh / deg.clamp(min=1.0)

            return self.lin_self(feats) + self.lin_neigh(neigh)

    class GraphSAGERisk(nn.Module):
        def __init__(self):
            super().__init__()
            self.s1 = GraphSAGELayer(feat_dim, hidden_dim)
            self.s2 = GraphSAGELayer(hidden_dim, embed_dim)
            self.drop = nn.Dropout(dropout)
            self.clf = nn.Linear(embed_dim, 1)
            self.recon = nn.Linear(embed_dim, feat_dim)

        def forward(self, feats: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]:
            h = torch.relu(self.s1(feats))
            h = self.drop(h)
            z = torch.relu(self.s2(h))
            z = self.drop(z)
            logits = self.clf(z)
            return logits, z

        def reconstruct(self, feats: torch.Tensor) -> torch.Tensor:
            _, z = self.forward(feats)
            return self.recon(z)

    model = GraphSAGERisk()

    indices = torch.randperm(n_nodes)
    split = int(math.floor(n_nodes * 0.8))
    if n_nodes < 8:
        split = n_nodes

    train_idx = indices[:split]
    val_idx = indices[split:] if split < n_nodes else indices[:0]

    positives = int(y.sum().item())
    negatives = int(n_nodes - positives)
    if positives > 0 and negatives > 0:
        pos_weight = torch.tensor([float(negatives / positives)], dtype=torch.float32)
        criterion = nn.BCEWithLogitsLoss(pos_weight=pos_weight)
    else:
        criterion = nn.BCEWithLogitsLoss()

    optim = torch.optim.Adam(
        model.parameters(),
        lr=float(learning_rate),
        weight_decay=float(weight_decay),
    )

    last_pretrain = 0.0
    if int(pretrain_epochs) > 0:
        recon_loss_fn = nn.MSELoss()
        for _ in range(int(pretrain_epochs)):
            model.train()
            optim.zero_grad()
            noise = torch.randn_like(x) * 0.02
            x_noisy = x + noise
            x_hat = model.reconstruct(x_noisy)
            loss = recon_loss_fn(x_hat, x)
            loss.backward()
            if grad_clip is not None and grad_clip > 0:
                torch.nn.utils.clip_grad_norm_(model.parameters(), float(grad_clip))
            optim.step()
            last_pretrain = float(loss.item())

    best_state = None
    best_val = float("inf")
    patience = 10
    stale = 0
    last_train = 0.0

    for _ in range(max(1, int(epochs))):
        model.train()
        optim.zero_grad()
        logits, _ = model(x)
        train_loss = criterion(logits[train_idx], y[train_idx])
        train_loss.backward()
        if grad_clip is not None and grad_clip > 0:
            torch.nn.utils.clip_grad_norm_(model.parameters(), float(grad_clip))
        optim.step()
        last_train = float(train_loss.item())

        if len(val_idx) > 0:
            model.eval()
            with torch.no_grad():
                val_logits, _ = model(x)
                val_loss = criterion(val_logits[val_idx], y[val_idx])
                val_loss_val = float(val_loss.item())
                if val_loss_val < best_val:
                    best_val = val_loss_val
                    best_state = {
                        "model": model.state_dict(),
                    }
                    stale = 0
                else:
                    stale += 1
                if stale >= patience:
                    break

    if best_state is not None:
        model.load_state_dict(best_state["model"])

    model.eval()
    with torch.no_grad():
        logits, embeddings = model(x)
        probs = torch.sigmoid(logits).view(-1)

    prob_list = [float(v) for v in probs.tolist()]
    pred_list = [1 if p >= 0.5 else 0 for p in prob_list]

    metrics = _binary_metrics(dataset.labels, prob_list)
    metrics["train_loss"] = round(last_train, 6)
    metrics["val_loss"] = round(best_val if best_val < float("inf") else last_train, 6)
    metrics["pretrain_loss"] = round(last_pretrain, 6)

    uncertainties = [round(1.0 - abs(float(p) - 0.5) * 2.0, 6) for p in prob_list]

    return GNNTrainResult(
        embeddings=[[float(v) for v in row] for row in embeddings.tolist()],
        probabilities=prob_list,
        predicted_labels=pred_list,
        uncertainties=uncertainties,
        metrics=metrics,
        model_state=model.state_dict(),
    )

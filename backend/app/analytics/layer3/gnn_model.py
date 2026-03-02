"""
Sentinel-KE GNN model: SentinelGNN (attention GraphSAGE) with MC Dropout
uncertainty, portable artifact save/load, and sampled AUC metric.

Design principles:
- Pure PyTorch only — no PyG / torch_scatter required
- Module classes are built inside a factory so torch stays a lazy import
- state_dict keys are architecture-independent (name-based), so artifacts
  serialised on GPU load correctly on CPU and vice-versa
"""
from __future__ import annotations

import hashlib
import math
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.analytics.layer3.gnn_backbone import GNNDataset


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class GNNTrainResult:
    """Immutable result produced by train_graphsage."""

    embeddings: List[List[float]]
    probabilities: List[float]
    predicted_labels: List[int]
    metrics: Dict[str, float]
    model_state: Dict[str, Any]
    feat_dim: int = 0
    uncertainties: Optional[List[float]] = None


# ---------------------------------------------------------------------------
# PyTorch lazy-import gate
# ---------------------------------------------------------------------------

def _require_torch():
    try:
        import torch  # noqa: PLC0415
        return torch
    except ImportError as exc:
        raise RuntimeError(
            "PyTorch is required for GNN training. "
            "Install: pip install -r backend/requirements-ml.txt"
        ) from exc


# ---------------------------------------------------------------------------
# Model factory
# ---------------------------------------------------------------------------

def build_sentinel_gnn(
    feat_dim: int,
    hidden_dim: int = 64,
    embed_dim: int = 32,
    dropout: float = 0.2,
):
    """
    Build a SentinelGNN instance (2-layer attention GraphSAGE).

    All PyTorch imports happen inside this function so the module can be
    imported without torch installed.  Returned object is a standard
    nn.Module — state_dict save/load works normally.

    Architecture
    ------------
    Input(feat_dim) -> AttnSAGE(hidden_dim) -> ReLU -> Dropout
                    -> AttnSAGE(embed_dim)  -> ReLU -> Dropout
                    -> Linear(1) = risk logit
    Also exposes reconstruct() for denoising-autoencoder pretraining.
    """
    import torch  # noqa: PLC0415
    import torch.nn as nn  # noqa: PLC0415
    import torch.nn.functional as F  # noqa: PLC0415

    class _AttnSAGELayer(nn.Module):
        """
        GraphSAGE + sigmoid attention gate (pure index_add_ — no scatter lib).

        Aggregation:
            a(e) = σ(W_a · [h_src || h_dst])          scalar per edge
            h̃_i = Σ_j a(i,j)·w(i,j)·h_j / Σ_j a(i,j)·w(i,j)
            h_i  = W_self·h_i + W_neigh·h̃_i
        """

        def __init__(self, in_d: int, out_d: int) -> None:
            super().__init__()
            self.lin_self  = nn.Linear(in_d,     out_d, bias=True)
            self.lin_neigh = nn.Linear(in_d,     out_d, bias=False)
            self.attn_gate = nn.Linear(in_d * 2, 1,     bias=False)

        def forward(
            self,
            feats: torch.Tensor,       # [N, in_d]
            edge_src: torch.Tensor,    # [E]
            edge_dst: torch.Tensor,    # [E]
            edge_weight: torch.Tensor, # [E]
        ) -> torch.Tensor:
            n_nodes = feats.shape[0]
            if edge_src.numel() == 0:
                return self.lin_self(feats)

            pair  = torch.cat([feats[edge_src], feats[edge_dst]], dim=1)
            attn  = torch.sigmoid(self.attn_gate(pair)).squeeze(1)   # [E]
            eff_w = attn * edge_weight                                # [E]

            weighted = feats[edge_src] * eff_w.unsqueeze(1)          # [E, in_d]
            neigh = torch.zeros(n_nodes, feats.shape[1],
                                dtype=feats.dtype, device=feats.device)
            neigh.index_add_(0, edge_dst, weighted)

            deg = torch.zeros(n_nodes, 1, dtype=feats.dtype, device=feats.device)
            deg.index_add_(0, edge_dst, eff_w.unsqueeze(1))
            neigh = neigh / deg.clamp(min=1e-6)

            return self.lin_self(feats) + self.lin_neigh(neigh)

    class _SentinelGNN(nn.Module):
        """2-layer attention GraphSAGE risk classifier."""

        def __init__(self) -> None:
            super().__init__()
            self.feat_dim   = feat_dim
            self.hidden_dim = hidden_dim
            self.embed_dim  = embed_dim

            self.s1   = _AttnSAGELayer(feat_dim,    hidden_dim)
            self.s2   = _AttnSAGELayer(hidden_dim,  embed_dim)
            self.drop = nn.Dropout(dropout)
            self.clf  = nn.Linear(embed_dim, 1)
            self.recon = nn.Linear(embed_dim, feat_dim)

        def encode(
            self,
            feats:       torch.Tensor,
            edge_src:    torch.Tensor,
            edge_dst:    torch.Tensor,
            edge_weight: torch.Tensor,
        ) -> torch.Tensor:
            h = F.relu(self.s1(feats, edge_src, edge_dst, edge_weight))
            h = self.drop(h)
            z = F.relu(self.s2(h,     edge_src, edge_dst, edge_weight))
            z = self.drop(z)
            return z

        def forward(
            self,
            feats:       torch.Tensor,
            edge_src:    torch.Tensor,
            edge_dst:    torch.Tensor,
            edge_weight: torch.Tensor,
        ) -> Tuple[torch.Tensor, torch.Tensor]:
            z = self.encode(feats, edge_src, edge_dst, edge_weight)
            return self.clf(z), z

        def reconstruct(
            self,
            feats:       torch.Tensor,
            edge_src:    torch.Tensor,
            edge_dst:    torch.Tensor,
            edge_weight: torch.Tensor,
        ) -> torch.Tensor:
            return self.recon(self.encode(feats, edge_src, edge_dst, edge_weight))

    return _SentinelGNN()


# ---------------------------------------------------------------------------
# Monte Carlo Dropout inference
# ---------------------------------------------------------------------------

def predict_mc(
    model,
    x,
    edge_src,
    edge_dst,
    edge_weight,
    *,
    n_samples: int = 20,
) -> Tuple[List[float], List[float]]:
    """
    Bayesian uncertainty via Monte Carlo Dropout (Gal & Ghahramani 2016).

    Setting model.train() activates dropout at inference time, sampling from
    an approximate posterior over weights.  Std across samples gives a
    calibrated uncertainty estimate — superior to the proxy |p - 0.5| heuristic.

    Returns
    -------
    mean_probs    per-node risk probability in [0, 1]
    uncertainties per-node uncertainty in [0, 1]   (0 = certain, 1 = max)
    """
    import torch  # noqa: PLC0415

    model.train()           # enable dropout for stochastic sampling
    all_probs: List = []
    with torch.no_grad():
        for _ in range(n_samples):
            logits, _ = model(x, edge_src, edge_dst, edge_weight)
            all_probs.append(torch.sigmoid(logits).view(-1))
    model.eval()

    stacked   = torch.stack(all_probs, dim=0)               # [S, N]
    mean_prob = stacked.mean(dim=0)                         # [N]
    std_prob  = stacked.std(dim=0, unbiased=True)           # [N]

    # Max Bernoulli std = 0.5 (at p = 0.5); normalise to [0, 1]
    uncertainty = torch.clamp(std_prob / 0.5, 0.0, 1.0)

    return mean_prob.tolist(), uncertainty.tolist()


def gradient_x_input_attributions(
    model,
    x,
    edge_src,
    edge_dst,
    edge_weight,
    *,
    node_indices: Sequence[int],
    max_nodes: int = 64,
) -> Dict[int, List[float]]:
    """
    Compute per-node Gradient x Input attribution vectors.

    Notes:
    - Runs in eval mode (dropout disabled) for deterministic attributions.
    - Computes node-local attribution: grad(prob[node]) * x[node].
    - This is a practical, dependency-free alternative to SHAP/LIME.
    """
    import torch  # noqa: PLC0415

    picked: List[int] = []
    seen = set()
    for idx in node_indices:
        i = int(idx)
        if i in seen:
            continue
        seen.add(i)
        picked.append(i)
        if len(picked) >= max(1, int(max_nodes)):
            break

    out: Dict[int, List[float]] = {}
    if not picked:
        return out

    model.eval()
    for node_idx in picked:
        x_var = x.detach().clone().requires_grad_(True)
        model.zero_grad(set_to_none=True)
        logits, _ = model(x_var, edge_src, edge_dst, edge_weight)
        prob = torch.sigmoid(logits[node_idx, 0])
        prob.backward()

        grad = x_var.grad[node_idx].detach()
        contrib = (grad * x_var[node_idx].detach()).cpu().tolist()
        out[int(node_idx)] = [float(v) for v in contrib]

    return out


def integrated_gradients_attributions(
    model,
    x,
    edge_src,
    edge_dst,
    edge_weight,
    *,
    node_indices: Sequence[int],
    max_nodes: int = 64,
    steps: int = 24,
) -> Dict[int, List[float]]:
    """
    Integrated Gradients attributions (Sundararajan et al., 2017).

    We use a zero baseline and approximate the path integral with `steps`
    interpolation points. Output is per-node attribution vectors aligned to
    input features.
    """
    import torch  # noqa: PLC0415

    picked: List[int] = []
    seen = set()
    for idx in node_indices:
        i = int(idx)
        if i in seen:
            continue
        seen.add(i)
        picked.append(i)
        if len(picked) >= max(1, int(max_nodes)):
            break

    out: Dict[int, List[float]] = {}
    if not picked:
        return out

    k_steps = max(8, int(steps))
    baseline = torch.zeros_like(x)
    delta = (x - baseline).detach()

    model.eval()
    for node_idx in picked:
        total_grad = torch.zeros_like(x[node_idx])
        for s in range(1, k_steps + 1):
            alpha = float(s) / float(k_steps)
            x_step = (baseline + alpha * delta).detach().clone().requires_grad_(True)
            model.zero_grad(set_to_none=True)
            logits, _ = model(x_step, edge_src, edge_dst, edge_weight)
            prob = torch.sigmoid(logits[node_idx, 0])
            prob.backward()
            grad = x_step.grad[node_idx].detach()
            total_grad = total_grad + grad

        avg_grad = total_grad / float(k_steps)
        attr = (delta[node_idx] * avg_grad).cpu().tolist()
        out[int(node_idx)] = [float(v) for v in attr]

    return out


# ---------------------------------------------------------------------------
# Artifact I/O
# ---------------------------------------------------------------------------

def load_model(artifact_path: str) -> Tuple[Any, Dict[str, Any]]:
    """
    Reconstruct a SentinelGNN from a .pt artifact produced by gnn_train_worker.

    Artifact schema
    ---------------
    {
        "model_state": <state_dict>,
        "metadata": {
            "feature_dim": int,
            "hidden_dim":  int,
            "embed_dim":   int,
            "dropout":     float,   # optional, defaults to 0.2
            ...
        }
    }

    Returns
    -------
    model   nn.Module in eval mode, ready for inference
    meta    raw metadata dict
    """
    torch = _require_torch()

    path = Path(artifact_path)
    if not path.exists():
        raise FileNotFoundError(f"GNN artifact not found: {artifact_path}")

    payload = torch.load(str(path), map_location="cpu", weights_only=False)
    meta    = payload.get("metadata", {})

    feat_dim   = int(meta.get("feature_dim") or meta.get("feat_dim") or 12)
    hidden_dim = int(meta.get("hidden_dim") or 64)
    embed_dim  = int(meta.get("embed_dim")  or 32)
    dropout    = float(meta.get("dropout")  or 0.2)

    model = build_sentinel_gnn(feat_dim, hidden_dim, embed_dim, dropout)
    model.load_state_dict(payload["model_state"])
    model.eval()
    return model, meta


# ---------------------------------------------------------------------------
# Metrics helpers
# ---------------------------------------------------------------------------

def _auc_sampled(
    labels: Sequence[int],
    scores: Sequence[float],
    *,
    n_pairs: int = 10_000,
    seed: int = 42,
) -> float:
    """
    O(n_pairs) AUC via random pair sampling.
    Replaces the original O(n²) exhaustive comparator for scalability.
    """
    pos = [float(s) for lbl, s in zip(labels, scores) if int(lbl) == 1]
    neg = [float(s) for lbl, s in zip(labels, scores) if int(lbl) == 0]
    if not pos or not neg:
        return 0.5

    rng          = random.Random(seed)
    actual_pairs = min(n_pairs, len(pos) * len(neg))
    wins         = 0.0
    for _ in range(actual_pairs):
        ps = rng.choice(pos)
        ns = rng.choice(neg)
        if ps > ns:
            wins += 1.0
        elif ps == ns:
            wins += 0.5
    return wins / actual_pairs


def _binary_metrics(
    labels: Sequence[int],
    probs: Sequence[float],
    threshold: float = 0.5,
) -> Dict[str, float]:
    y_true = [int(v) for v in labels]
    y_pred = [1 if float(p) >= threshold else 0 for p in probs]

    tp = sum(1 for yt, yp in zip(y_true, y_pred) if yt == 1 and yp == 1)
    tn = sum(1 for yt, yp in zip(y_true, y_pred) if yt == 0 and yp == 0)
    fp = sum(1 for yt, yp in zip(y_true, y_pred) if yt == 0 and yp == 1)
    fn = sum(1 for yt, yp in zip(y_true, y_pred) if yt == 1 and yp == 0)

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall    = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
    acc = (tp + tn) / max(1, len(y_true))

    return {
        "accuracy":  round(acc, 6),
        "precision": round(precision, 6),
        "recall":    round(recall, 6),
        "f1":        round(f1, 6),
        "auc":       round(_auc_sampled(y_true, probs), 6),
    }


def _sanitize(matrix: Sequence[Sequence[float]]) -> List[List[float]]:
    return [
        [0.0 if not math.isfinite(float(v)) else float(v) for v in row]
        for row in matrix
    ]


# ---------------------------------------------------------------------------
# Training entry point
# ---------------------------------------------------------------------------

def _build_edge_tensors(
    dataset: GNNDataset,
    temporal_decay: float,
    torch,
) -> Tuple:
    """Convert dataset edges to bidirectional torch tensors with self-loops."""
    n_nodes = len(dataset.feature_matrix)
    src_idx: List[int]   = []
    dst_idx: List[int]   = []
    edge_w:  List[float] = []

    for i, j, w in dataset.edges:
        ew = math.log1p(max(0.0, float(w)))
        if temporal_decay > 0:
            ew *= math.exp(-temporal_decay * min(10.0, ew))
        src_idx += [i, j]
        dst_idx += [j, i]
        edge_w  += [ew, ew]

    for i in range(n_nodes):       # self-loops for numerical stability
        src_idx.append(i)
        dst_idx.append(i)
        edge_w.append(1.0)

    return (
        torch.tensor(src_idx, dtype=torch.long),
        torch.tensor(dst_idx, dtype=torch.long),
        torch.tensor(edge_w,  dtype=torch.float32),
    )


def _calibration_metrics(labels: Sequence[int], probabilities: Sequence[float], *, bins: int = 10) -> Dict[str, float]:
    n = min(len(labels), len(probabilities))
    if n <= 0:
        return {"calibration_ece": 0.0, "calibration_mce": 0.0, "brier_score": 0.0}

    brier = 0.0
    for i in range(n):
        y = 1.0 if int(labels[i]) > 0 else 0.0
        p = max(0.0, min(1.0, float(probabilities[i])))
        brier += (p - y) ** 2
    brier /= float(n)

    bin_count = max(2, int(bins))
    bucket_total = [0] * bin_count
    bucket_prob = [0.0] * bin_count
    bucket_label = [0.0] * bin_count
    for i in range(n):
        y = 1.0 if int(labels[i]) > 0 else 0.0
        p = max(0.0, min(1.0, float(probabilities[i])))
        b = min(bin_count - 1, int(p * bin_count))
        bucket_total[b] += 1
        bucket_prob[b] += p
        bucket_label[b] += y

    ece = 0.0
    mce = 0.0
    for b in range(bin_count):
        cnt = bucket_total[b]
        if cnt <= 0:
            continue
        avg_prob = bucket_prob[b] / float(cnt)
        avg_label = bucket_label[b] / float(cnt)
        gap = abs(avg_prob - avg_label)
        ece += (float(cnt) / float(n)) * gap
        mce = max(mce, gap)

    return {
        "calibration_ece": round(float(ece), 6),
        "calibration_mce": round(float(mce), 6),
        "brier_score": round(float(brier), 6),
    }


def _select_train_val_indices(
    dataset: GNNDataset,
    *,
    split_policy: str,
    val_ratio: float,
    seed: int,
    torch,
):
    n_nodes = len(dataset.feature_matrix)
    if n_nodes <= 1:
        idx = torch.arange(n_nodes, dtype=torch.long)
        return idx, idx[:0], {
            "split_policy": split_policy,
            "train_count": int(len(idx)),
            "val_count": 0,
            "val_ratio_target": float(val_ratio),
            "val_ratio_actual": 0.0,
        }

    target_val = max(1, int(math.floor(n_nodes * max(0.05, min(0.45, float(val_ratio))))))
    target_val = min(target_val, n_nodes - 1)
    policy = str(split_policy or "entity_hash_holdout").strip().lower()

    if policy == "random":
        random.seed(seed)
        perm = torch.randperm(n_nodes)
        val_idx = perm[:target_val]
        train_idx = perm[target_val:]
    elif policy == "temporal_recency_holdout":
        # Recency feature index follows current cyber feature backbone:
        # index 15 = recency. If absent, fallback to 0.0.
        scored = []
        for i in range(n_nodes):
            row = dataset.feature_matrix[i]
            recency = float(row[15]) if len(row) > 15 else 0.0
            scored.append((recency, i))
        scored.sort(key=lambda x: x[0], reverse=True)
        val_ids = {i for _, i in scored[:target_val]}
        train_ids = [i for i in range(n_nodes) if i not in val_ids]
        if not train_ids:
            train_ids = [scored[-1][1]]
            val_ids.discard(scored[-1][1])
        train_idx = torch.tensor(train_ids, dtype=torch.long)
        val_idx = torch.tensor(sorted(val_ids), dtype=torch.long)
    else:
        # Deterministic entity holdout: stable across runs and machines.
        val_ids: List[int] = []
        train_ids: List[int] = []
        ratio = max(0.05, min(0.45, float(val_ratio)))
        for i, key in enumerate(dataset.entity_keys):
            digest = hashlib.sha256(str(key).encode("utf-8")).digest()
            bucket = int.from_bytes(digest[:2], byteorder="big") / 65535.0
            if bucket < ratio:
                val_ids.append(i)
            else:
                train_ids.append(i)
        if len(val_ids) < target_val:
            # Backfill deterministically by key order for stable cardinality.
            needed = target_val - len(val_ids)
            for i in range(n_nodes):
                if i in val_ids:
                    continue
                val_ids.append(i)
                if i in train_ids:
                    train_ids.remove(i)
                needed -= 1
                if needed <= 0:
                    break
        if not train_ids:
            moved = val_ids.pop()  # keep at least one train sample
            train_ids.append(moved)
        train_idx = torch.tensor(sorted(train_ids), dtype=torch.long)
        val_idx = torch.tensor(sorted(val_ids), dtype=torch.long)
        policy = "entity_hash_holdout"

    return train_idx, val_idx, {
        "split_policy": policy,
        "train_count": int(len(train_idx)),
        "val_count": int(len(val_idx)),
        "val_ratio_target": float(val_ratio),
        "val_ratio_actual": round(float(len(val_idx) / max(1, n_nodes)), 6),
    }


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
    grad_clip: Optional[float] = 5.0,
    temporal_decay: float = 0.0,
    pretrain_epochs: int = 0,
    mc_samples: int = 20,
    split_policy: str = "entity_hash_holdout",
    val_ratio: float = 0.2,
) -> GNNTrainResult:
    """
    Train SentinelGNN on a GNNDataset.

    Key improvements over v1
    ------------------------
    * Model defined via factory (portable artifact, loadable for inference)
    * Attention gating replaces plain mean aggregation
    * Monte Carlo Dropout uncertainty (Bayesian, not proxy)
    * O(n_pairs) AUC sampler replaces O(n²) exhaustive loop
    * feat_dim recorded in result so artifact reconstruction is self-contained
    """
    torch = _require_torch()
    import torch.nn as nn  # noqa: PLC0415

    random.seed(seed)
    torch.manual_seed(seed)
    try:
        torch.use_deterministic_algorithms(True)
    except Exception:  # noqa: BLE001
        pass

    if not dataset.feature_matrix:
        raise ValueError("dataset has no feature rows")

    n_nodes  = len(dataset.feature_matrix)
    feat_dim = len(dataset.feature_matrix[0])

    if len(dataset.labels) != n_nodes:
        raise ValueError("labels / feature_matrix length mismatch")
    if len(dataset.entity_keys) != n_nodes:
        raise ValueError("entity_keys / feature_matrix length mismatch")
    if feat_dim <= 0:
        raise ValueError("feature dimension is zero")
    for row in dataset.feature_matrix:
        if len(row) != feat_dim:
            raise ValueError("inconsistent feature row widths")

    x = torch.tensor(_sanitize(dataset.feature_matrix), dtype=torch.float32)
    y = torch.tensor([float(v) for v in dataset.labels],
                     dtype=torch.float32).view(-1, 1)

    edge_src, edge_dst, edge_weight = _build_edge_tensors(
        dataset, temporal_decay, torch
    )

    model = build_sentinel_gnn(feat_dim, hidden_dim, embed_dim, dropout)

    train_idx, val_idx, split_manifest = _select_train_val_indices(
        dataset,
        split_policy=split_policy,
        val_ratio=val_ratio,
        seed=seed,
        torch=torch,
    )

    # Class-balanced loss
    n_pos = int(y.sum().item())
    n_neg = n_nodes - n_pos
    if n_pos > 0 and n_neg > 0:
        criterion = nn.BCEWithLogitsLoss(
            pos_weight=torch.tensor([float(n_neg / n_pos)])
        )
    else:
        criterion = nn.BCEWithLogitsLoss()

    optim = torch.optim.Adam(
        model.parameters(), lr=learning_rate, weight_decay=weight_decay
    )

    # Optional denoising-autoencoder pretraining
    last_pretrain = 0.0
    if pretrain_epochs > 0:
        recon_loss_fn = nn.MSELoss()
        for _ in range(pretrain_epochs):
            model.train()
            optim.zero_grad()
            x_noisy = x + torch.randn_like(x) * 0.02
            x_hat   = model.reconstruct(x_noisy, edge_src, edge_dst, edge_weight)
            loss    = recon_loss_fn(x_hat, x)
            loss.backward()
            if grad_clip:
                nn.utils.clip_grad_norm_(model.parameters(), grad_clip)
            optim.step()
            last_pretrain = float(loss.item())

    # Supervised training with early stopping
    best_state: Optional[Dict] = None
    best_val   = float("inf")
    patience   = 10
    stale      = 0
    last_train = 0.0

    for _ in range(max(1, epochs)):
        model.train()
        optim.zero_grad()
        logits, _ = model(x, edge_src, edge_dst, edge_weight)
        loss      = criterion(logits[train_idx], y[train_idx])
        loss.backward()
        if grad_clip:
            nn.utils.clip_grad_norm_(model.parameters(), grad_clip)
        optim.step()
        last_train = float(loss.item())

        if len(val_idx) > 0:
            model.eval()
            with torch.no_grad():
                v_logits, _ = model(x, edge_src, edge_dst, edge_weight)
                v_loss      = float(criterion(v_logits[val_idx], y[val_idx]).item())
            if v_loss < best_val:
                best_val   = v_loss
                best_state = {k: v.clone() for k, v in model.state_dict().items()}
                stale      = 0
            else:
                stale += 1
            if stale >= patience:
                break

    if best_state is not None:
        model.load_state_dict(best_state)

    # Final MC-Dropout inference
    mean_probs, uncertainties = predict_mc(
        model, x, edge_src, edge_dst, edge_weight, n_samples=mc_samples
    )

    # Deterministic embeddings for storage
    model.eval()
    with torch.no_grad():
        _, embeddings = model(x, edge_src, edge_dst, edge_weight)

    metrics = _binary_metrics(dataset.labels, mean_probs)
    if len(val_idx) > 0:
        eval_idx = [int(i) for i in val_idx.tolist()]
    else:
        eval_idx = list(range(n_nodes))
    eval_labels = [int(dataset.labels[i]) for i in eval_idx]
    eval_probs = [float(mean_probs[i]) for i in eval_idx]
    metrics.update(_calibration_metrics(eval_labels, eval_probs, bins=10))
    metrics["train_loss"]    = round(last_train, 6)
    metrics["val_loss"]      = round(best_val if math.isfinite(best_val) else last_train, 6)
    metrics["pretrain_loss"] = round(last_pretrain, 6)
    metrics["eval_samples"] = int(len(eval_idx))
    metrics.update(split_manifest)

    return GNNTrainResult(
        embeddings      = [[float(v) for v in row] for row in embeddings.tolist()],
        probabilities   = mean_probs,
        predicted_labels= [1 if p >= 0.5 else 0 for p in mean_probs],
        uncertainties   = uncertainties,
        metrics         = metrics,
        model_state     = model.state_dict(),
        feat_dim        = feat_dim,
    )

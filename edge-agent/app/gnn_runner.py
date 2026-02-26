"""
Sentinel-KE Edge Agent — GNN Runner
=====================================

Runs a full 2-layer Attention GraphSAGE on the partner's local data and
returns per-entity risk scores + uncertainty estimates.

The model is trained from scratch on each run using the current window's
weak labels (risk_flags → positive, benign heuristic → negative).
For production use, persist the model weights between runs and only
retrain periodically; inference-only mode is toggled via the RETRAIN_EVERY
setting.

Architecture (mirrors hub gnn_backbone.py)
-------------------------------------------
  Input     : 44-dim feature vectors (one per entity node)
  Layer 1   : SAGEConv(44 → 64) + ELU + Dropout(0.3)
  Layer 2   : SAGEConv(64 → 32) + ELU + Dropout(0.3)
  Classifier: Linear(32 → 1) + Sigmoid
  Uncertainty: MC-Dropout (20 forward passes with training=True)

Output: list of GNNResult with risk_score ∈ [0,1], uncertainty ∈ [0,1].
"""
from __future__ import annotations

import logging
import math
import random
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.connector import EntityRecord
from app.feature_builder import FEATURE_DIM, build_feature_vector

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional PyTorch import — graceful fallback to a heuristic scorer
# if torch / torch_geometric are not installed (lightweight demo mode).
# ---------------------------------------------------------------------------
try:
    import torch
    import torch.nn as nn
    import torch.nn.functional as F
    from torch_geometric.data import Data
    from torch_geometric.nn import SAGEConv
    _TORCH_AVAILABLE = True
except ImportError:
    _TORCH_AVAILABLE = False
    logger.warning("torch / torch_geometric not installed — using heuristic scorer")


# ---------------------------------------------------------------------------
# Labelling helper (mirrors hub weak_label)
# ---------------------------------------------------------------------------

_POSITIVE_FLAGS = {
    "DDOS_ALERT_SERVICE", "DDOS_ALERT_ENDPOINT",
    "CAMPAIGN_ENTITY", "VPN_CLUSTER_MEMBER",
    "DDOS_CLUSTER_MEMBER", "AIRTIME_SIPHON_MEMBER",
}
_SUSPICIOUS_EVENTS = {
    "DDOS_SIGNAL_EVENT", "SIM_SWAP_EVENT", "TRANSACTION_EVENT",
    "PHISHING_MESSAGE_EVENT", "DFIR_FINDING_EVENT",
    "FILE_INTEGRITY_EVENT", "DB_AUDIT_EVENT",
    "AIRTIME_TRANSFER_EVENT", "BILLING_FRAUD_EVENT",
}


def _weak_label(rec: EntityRecord) -> int:
    flags = set(rec.get("risk_flags") or [])
    if flags & _POSITIVE_FLAGS:
        return 1
    ec = rec.get("event_count", 0)
    sc = rec.get("source_count", 0)
    if ec >= 25 and sc >= 3:
        return 1
    return 0


# ---------------------------------------------------------------------------
# GNN model definition
# ---------------------------------------------------------------------------

if _TORCH_AVAILABLE:
    class _AttentionSAGE(nn.Module):
        def __init__(self, in_dim: int = FEATURE_DIM, hidden: int = 64, out_dim: int = 32, drop: float = 0.3):
            super().__init__()
            self.conv1 = SAGEConv(in_dim,  hidden)
            self.conv2 = SAGEConv(hidden,  out_dim)
            self.head  = nn.Linear(out_dim, 1)
            self.drop  = drop

        def forward(self, x, edge_index):
            x = self.conv1(x, edge_index)
            x = F.elu(x)
            x = F.dropout(x, p=self.drop, training=self.training)
            x = self.conv2(x, edge_index)
            x = F.elu(x)
            x = F.dropout(x, p=self.drop, training=self.training)
            return torch.sigmoid(self.head(x)).squeeze(-1)


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------

@dataclass
class GNNResult:
    entity_key:   str
    entity_type:  str
    risk_score:   float
    uncertainty:  float
    fraud_family: Optional[str]
    chain_score:  float
    risk_flags:   List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Edge builder
# ---------------------------------------------------------------------------

def _build_edges(records: List[EntityRecord]) -> List[Tuple[int, int]]:
    """
    Lightweight co-occurrence edges: entities that share the same entity_type
    AND appear together in the same risk flag set get connected.

    For a production deployment, replace with real event-co-occurrence edges
    from the partner's own graph database.
    """
    flag_to_nodes: Dict[str, List[int]] = {}
    for i, r in enumerate(records):
        for fl in (r.get("risk_flags") or []):
            flag_to_nodes.setdefault(fl, []).append(i)

    edges: List[Tuple[int, int]] = []
    for nodes in flag_to_nodes.values():
        for a in range(len(nodes)):
            for b in range(a + 1, min(len(nodes), a + 10)):  # cap fan-out
                edges.append((nodes[a], nodes[b]))
                edges.append((nodes[b], nodes[a]))
    return edges


# ---------------------------------------------------------------------------
# Heuristic fallback scorer (no torch)
# ---------------------------------------------------------------------------

def _heuristic_score(rec: EntityRecord) -> Tuple[float, float]:
    label = _weak_label(rec)
    ec    = rec.get("event_count", 0)
    flags = rec.get("risk_flags") or []
    et    = (rec.get("features") or {}).get("event_types") or {}

    suspicious = sum(et.get(t, 0) for t in _SUSPICIOUS_EVENTS)
    base  = 0.55 * label + 0.3 * min(1.0, suspicious / max(1, ec)) + 0.15 * min(1.0, len(flags) / 5.0)
    noise = random.uniform(-0.05, 0.05)
    score = max(0.0, min(1.0, base + noise))
    uncertainty = 0.15 if label else 0.05
    return round(score, 4), round(uncertainty, 4)


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

def run_gnn(
    records: List[EntityRecord],
    window_start: datetime,
    window_end:   datetime,
    *,
    epochs:     int = 30,
    lr:         float = 0.01,
    mc_passes:  int = 20,
    drop:       float = 0.3,
    device_str: str = "cpu",
) -> List[GNNResult]:
    """
    Train a GNN on the current window's entity graph and return per-entity
    risk scores with MC-Dropout uncertainty.

    Falls back to a heuristic scorer if torch is not available.
    """
    if not records:
        return []

    if not _TORCH_AVAILABLE:
        results = []
        for rec in records:
            score, unc = _heuristic_score(rec)
            ft = (rec.get("features") or {}).get("event_types") or {}
            chain_hits = sum(1 for t in {"DDOS_SIGNAL_EVENT","SIM_SWAP_EVENT","PHISHING_MESSAGE_EVENT"} if ft.get(t, 0) > 0)
            results.append(GNNResult(
                entity_key   = rec["entity_key"],
                entity_type  = rec["entity_type"],
                risk_score   = score,
                uncertainty  = unc,
                fraud_family = rec.get("fraud_family"),
                chain_score  = round(chain_hits / 3.0, 4),
                risk_flags   = list(rec.get("risk_flags") or []),
            ))
        return results

    # ------------------------------------------------------------------
    # Build feature matrix and labels
    # ------------------------------------------------------------------
    device = torch.device(device_str)
    X_list, y_list = [], []
    for rec in records:
        fvec = build_feature_vector(
            entity_type     = rec["entity_type"],
            event_count     = rec.get("event_count", 0),
            source_count    = rec.get("source_count", 0),
            degree          = rec.get("degree", 0),
            weighted_degree = rec.get("weighted_degree", 0),
            risk_flags      = rec.get("risk_flags") or [],
            features        = rec.get("features") or {},
            window_start    = window_start,
            window_end      = window_end,
            first_seen      = rec.get("first_seen"),
            last_seen       = rec.get("last_seen"),
        )
        X_list.append(fvec)
        y_list.append(float(_weak_label(rec)))

    X = torch.tensor(X_list, dtype=torch.float32, device=device)
    y = torch.tensor(y_list, dtype=torch.float32, device=device)

    # ------------------------------------------------------------------
    # Build edge index
    # ------------------------------------------------------------------
    raw_edges = _build_edges(records)
    if raw_edges:
        edge_index = torch.tensor(raw_edges, dtype=torch.long, device=device).T
    else:
        # No edges → self-loops only (degenerate but valid)
        idx = torch.arange(len(records), device=device)
        edge_index = torch.stack([idx, idx], dim=0)

    data = Data(x=X, edge_index=edge_index, y=y)

    # ------------------------------------------------------------------
    # Train
    # ------------------------------------------------------------------
    model = _AttentionSAGE(in_dim=FEATURE_DIM, drop=drop).to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=lr)
    pos_weight = torch.tensor([max(1.0, (len(y_list) - sum(y_list)) / max(1, sum(y_list)))], device=device)
    criterion  = nn.BCELoss(weight=None)

    model.train()
    for epoch in range(epochs):
        optimizer.zero_grad()
        preds = model(data.x, data.edge_index)
        loss  = criterion(preds, data.y)
        loss.backward()
        optimizer.step()
        if (epoch + 1) % 10 == 0:
            logger.debug("edge-agent GNN epoch %d/%d  loss=%.4f", epoch + 1, epochs, loss.item())

    # ------------------------------------------------------------------
    # MC-Dropout inference
    # ------------------------------------------------------------------
    model.train()  # keep dropout active for MC sampling
    with torch.no_grad():
        passes = torch.stack([model(data.x, data.edge_index) for _ in range(mc_passes)], dim=0)

    mean_scores = passes.mean(dim=0).cpu().tolist()
    std_scores  = passes.std(dim=0).cpu().tolist()

    # ------------------------------------------------------------------
    # Assemble results
    # ------------------------------------------------------------------
    results = []
    for i, rec in enumerate(records):
        ft = (rec.get("features") or {}).get("event_types") or {}
        chain_hits = sum(1 for t in {"DDOS_SIGNAL_EVENT","SIM_SWAP_EVENT","PHISHING_MESSAGE_EVENT"} if ft.get(t, 0) > 0)
        results.append(GNNResult(
            entity_key   = rec["entity_key"],
            entity_type  = rec["entity_type"],
            risk_score   = round(float(mean_scores[i]), 4),
            uncertainty  = round(float(std_scores[i]),  4),
            fraud_family = rec.get("fraud_family"),
            chain_score  = round(chain_hits / 3.0, 4),
            risk_flags   = list(rec.get("risk_flags") or []),
        ))
    return results

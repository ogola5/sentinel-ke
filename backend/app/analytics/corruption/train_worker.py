"""
Sentinel-KE Corruption Intelligence — GNN Training Worker
==========================================================

Trains a SentinelGNN on the corruption entity graph and writes risk
predictions to the same AI tables used by the cyber pipeline.

Data flow
---------
    GraphFeatureSnapshot (window_key="Wcorruption")
        │  snapshot_to_corruption_vector()   ← 42-dim feature builder
        ▼
    GNNDataset  ──► train_graphsage()  ──► .pt artifact
        │                                       │
        ▼                                       ▼
    AIPrediction (prediction_type="corruption_risk")
    GNNTrainingRun (prediction_type="corruption_risk")

Reuse strategy
--------------
* SentinelGNN model architecture  — identical to cyber pipeline
* GraphFeatureSnapshot table       — same table, different window_key
* GNNTrainingRun / AIPrediction   — same tables, different prediction_type
* _edges_from_postgres()           — same co-occurrence edge query
* train_graphsage()                — same training loop

The corruption pipeline is DOMAIN-SPECIFIC only in its feature vector
(Block 3 is audit/procurement flags, Block 4 is procurement event types).
The GNN itself is domain-agnostic.

Usage
-----
    python -m app.analytics.corruption.train_worker
    python -m app.analytics.corruption.train_worker \\
        --window-key Wcorruption --epochs 80 --edge-backend postgres
"""
from __future__ import annotations

import json
import logging
import math
from datetime import datetime, timezone
from typing import Dict, List, Optional, Sequence, Tuple

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.analytics.ai_models import (
    AIExplanation,
    AIPrediction,
    GNNTrainingRun,
    GraphFeatureSnapshot,
)
from app.analytics.corruption.feature_builder import (
    CORRUPTION_PREDICTION_TYPE,
    CORRUPTION_WINDOW_KEY,
    corruption_weak_label,
    snapshot_to_corruption_vector,
)
from app.analytics.layer3.gnn_backbone import (
    GNNDataset,
    _edges_from_postgres,
    collapse_edges,
)
from app.analytics.layer3.gnn_model import build_sentinel_gnn, predict_mc, train_graphsage
from app.core.config import settings
from app.ledger.db import SessionLocal, engine

log = logging.getLogger("sentinel.corruption_train_worker")

LEGAL_RISK_NOTICE = (
    "AI output is a corruption risk indicator for investigative prioritisation only; "
    "it is not final proof and requires forensic / legal corroboration."
)


# ---------------------------------------------------------------------------
# Dataset loader
# ---------------------------------------------------------------------------

def _load_corruption_dataset(
    db: Session,
    *,
    window_key: str = CORRUPTION_WINDOW_KEY,
    window_end: Optional[datetime] = None,
    max_entities: int = 5000,
    max_edges: int = 30_000,
    min_edge_weight: int = 1,
    negative_multiplier: float = 1.5,
) -> Optional[GNNDataset]:
    """
    Load GraphFeatureSnapshot rows for the corruption window and build a
    GNNDataset ready for train_graphsage().
    """
    if window_end is None:
        window_end = (
            db.query(func.max(GraphFeatureSnapshot.window_end))
            .filter(GraphFeatureSnapshot.window_key == window_key)
            .scalar()
        )
    if window_end is None:
        log.warning("corruption_dataset_empty: no snapshots for window_key=%s", window_key)
        return None

    snapshots: List[GraphFeatureSnapshot] = (
        db.query(GraphFeatureSnapshot)
        .filter(GraphFeatureSnapshot.window_key == window_key)
        .filter(GraphFeatureSnapshot.window_end == window_end)
        .limit(max_entities)
        .all()
    )
    if not snapshots:
        log.warning("corruption_dataset_empty: zero snapshots window_key=%s window_end=%s",
                    window_key, window_end)
        return None

    # ── Feature matrix ────────────────────────────────────────────────
    entity_keys:    List[str]           = []
    entity_types:   List[str]           = []
    feature_matrix: List[List[float]]   = []
    labels:         List[int]           = []
    node_meta:      List[Dict]          = []

    positive_count = 0
    negative_count = 0

    for snap in snapshots:
        vec   = snapshot_to_corruption_vector(snap)
        flags = list(snap.risk_flags or [])
        f     = snap.features or {}

        label = corruption_weak_label(
            risk_flags       = flags,
            event_count      = int(snap.event_count or 0),
            single_source    = bool(f.get("single_source")),
            director_conflict = "DIRECTOR_CONFLICT" in flags,
        )

        entity_keys.append(str(snap.entity_key))
        entity_types.append(str(snap.entity_type))
        feature_matrix.append(vec)
        labels.append(label)
        node_meta.append({
            "entity_type":  str(snap.entity_type),
            "risk_flags":   flags,
            "event_count":  int(snap.event_count or 0),
            "features":     f,
            "corruption_events": f.get("corruption_events") or f.get("event_types") or {},
        })

        if label == 1:
            positive_count += 1
        else:
            negative_count += 1

    if positive_count == 0:
        log.warning("corruption_no_positives: all labels are 0 — check risk_flags seeding")

    # ── Edge extraction ───────────────────────────────────────────────
    window_start = (
        db.query(func.min(GraphFeatureSnapshot.window_start))
        .filter(GraphFeatureSnapshot.window_key == window_key)
        .filter(GraphFeatureSnapshot.window_end == window_end)
        .scalar()
    ) or (window_end)

    raw_edges = _edges_from_postgres(
        db,
        entity_keys=entity_keys,
        window_start=window_start,
        window_end=window_end,
        min_edge_weight=min_edge_weight,
        max_edges=max_edges,
    )
    raw_edges = collapse_edges(raw_edges)

    key_to_idx = {k: i for i, k in enumerate(entity_keys)}
    edges: List[Tuple[int, int, float]] = []
    for src_k, dst_k, w in raw_edges:
        i = key_to_idx.get(src_k)
        j = key_to_idx.get(dst_k)
        if i is None or j is None or i == j:
            continue
        edges.append((i, j, math.log1p(max(0.0, float(w)))))

    log.info(
        "corruption_dataset_loaded nodes=%d positive=%d edges=%d window_key=%s",
        len(entity_keys), positive_count, len(edges), window_key,
    )

    return GNNDataset(
        window_key          = window_key,
        window_start        = window_start,
        window_end          = window_end,
        entity_keys         = entity_keys,
        entity_types        = entity_types,
        feature_matrix      = feature_matrix,
        labels              = labels,
        edges               = edges,
        node_meta           = node_meta,
        source_backend_used = "postgres",
        edge_source_counts  = {"postgres": len(edges)},
        positive_count      = positive_count,
        negative_count      = negative_count,
        benign_negative_count = negative_count,
    )


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------

def _severity(score: float) -> str:
    if score >= 90:
        return "critical"
    if score >= 75:
        return "high"
    if score >= 55:
        return "medium"
    return "low"


def _reason_codes(prob: float, flags: List[str], entity_type: str) -> List[str]:
    reasons: List[str] = []
    if prob >= 0.9:
        reasons.append("CORRUPTION_RISK_CRITICAL")
    elif prob >= 0.75:
        reasons.append("CORRUPTION_RISK_HIGH")
    elif prob >= 0.55:
        reasons.append("CORRUPTION_RISK_ELEVATED")
    else:
        reasons.append("CORRUPTION_RISK_LOW")
    for flag in flags:
        reasons.append(f"FLAG_{flag}")
    reasons.append("RISK_INDICATOR_ONLY_NOT_FINAL_PROOF")
    return sorted(set(reasons))


def _write_prediction(
    db: Session,
    *,
    entity_key: str,
    entity_type: str,
    window_key: str,
    window_end: datetime,
    model_version: str,
    score: float,
    prob: float,
    uncertainty: float,
    reasons: List[str],
    meta: Dict,
) -> None:
    confidence = max(0.0, min(1.0, 1.0 - uncertainty))
    abstained  = uncertainty >= float(getattr(settings, "ai_uncertainty_abstain_threshold", 0.45))
    if abstained:
        reasons = sorted(set(reasons + ["UNCERTAIN_REQUIRES_ANALYST_REVIEW"]))

    details = {
        "risk_flags":    meta.get("risk_flags", []),
        "event_count":   meta.get("event_count", 0),
        "confidence":    round(confidence, 6),
        "uncertainty":   round(uncertainty, 6),
        "abstained":     bool(abstained),
        "decision_source": "gnn",
        "domain":        "corruption",
        "legal_notice":  LEGAL_RISK_NOTICE,
    }

    pred = (
        db.query(AIPrediction)
        .filter(AIPrediction.entity_key      == entity_key)
        .filter(AIPrediction.prediction_type == CORRUPTION_PREDICTION_TYPE)
        .filter(AIPrediction.window_key      == window_key)
        .filter(AIPrediction.window_end      == window_end)
        .first()
    )

    if pred:
        pred.score           = score
        pred.model_version   = model_version
        pred.confidence      = confidence
        pred.uncertainty     = uncertainty
        pred.abstained       = bool(abstained)
        pred.decision_source = "gnn"
        pred.reason_codes    = reasons
        pred.details_json    = details
    else:
        pred = AIPrediction(
            entity_key       = entity_key,
            entity_type      = entity_type,
            prediction_type  = CORRUPTION_PREDICTION_TYPE,
            window_key       = window_key,
            window_end       = window_end,
            model_version    = model_version,
            score            = score,
            confidence       = confidence,
            uncertainty      = uncertainty,
            abstained        = bool(abstained),
            kill_chain_stage = "corruption-network",
            decision_source  = "gnn",
            reason_codes     = reasons,
            details_json     = details,
        )
        db.add(pred)
        db.flush()

    # Minimal explanation record
    expl = db.query(AIExplanation).filter(AIExplanation.prediction_id == pred.id).first()
    payload = {
        "domain":       "corruption",
        "decision_source": "gnn",
        "window_end":   window_end.isoformat(),
        "legal_notice": LEGAL_RISK_NOTICE,
    }
    if expl:
        expl.reason_codes = reasons
        expl.details_json = payload
    else:
        db.add(AIExplanation(
            prediction_id             = pred.id,
            reason_codes              = reasons,
            evidence_hashes           = [],
            evidence_paths            = [],
            recommended_controls_json = [],
            counterfactual_json       = {},
            details_json              = payload,
        ))


# ---------------------------------------------------------------------------
# Main training entry point
# ---------------------------------------------------------------------------

def run_once(
    *,
    db: Session,
    window_key:    str   = CORRUPTION_WINDOW_KEY,
    window_end:    Optional[datetime] = None,
    max_entities:  int   = 5000,
    max_edges:     int   = 30_000,
    min_edge_weight: int = 1,
    epochs:        int   = 60,
    hidden_dim:    int   = 64,
    embed_dim:     int   = 32,
    dropout:       float = 0.2,
    learning_rate: float = 0.001,
    weight_decay:  float = 0.0001,
    seed:          int   = 42,
    model_version: str   = "corruption-gnn-v1",
    artifact_dir:  str   = "/app/artifacts/gnn",
) -> Dict:
    """
    Load corruption snapshot data, train SentinelGNN, write predictions.
    Returns a summary dict.
    """
    # ── Load dataset ─────────────────────────────────────────────────
    dataset = _load_corruption_dataset(
        db,
        window_key      = window_key,
        window_end      = window_end,
        max_entities    = max_entities,
        max_edges       = max_edges,
        min_edge_weight = min_edge_weight,
    )
    if dataset is None:
        return {"status": "no_data", "message": "Run synthetic_corruption_data first"}
    if not dataset.feature_matrix:
        return {"status": "no_features"}

    # ── Train ─────────────────────────────────────────────────────────
    try:
        train_result = train_graphsage(
            dataset,
            epochs        = epochs,
            hidden_dim    = hidden_dim,
            embed_dim     = embed_dim,
            dropout       = dropout,
            learning_rate = learning_rate,
            weight_decay  = weight_decay,
            seed          = seed,
        )
    except Exception as exc:
        db.rollback()
        return {"status": "error", "stage": "train", "detail": str(exc)}

    # ── Save artifact ─────────────────────────────────────────────────
    import torch  # noqa: PLC0415
    from pathlib import Path  # noqa: PLC0415

    feat_dim = len(dataset.feature_matrix[0])
    artifact_payload = {
        "model_state": train_result.model_state,
        "metadata": {
            "model_version":    model_version,
            "prediction_type":  CORRUPTION_PREDICTION_TYPE,
            "domain":           "corruption",
            "window_key":       dataset.window_key,
            "window_end":       dataset.window_end.isoformat(),
            "feature_dim":      feat_dim,
            "hidden_dim":       hidden_dim,
            "embed_dim":        embed_dim,
            "dropout":          dropout,
        },
    }
    artifact_path: Optional[str] = None
    try:
        out_dir  = Path(artifact_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        out_file = out_dir / f"corruption_{model_version}.pt"
        torch.save(artifact_payload, str(out_file))
        artifact_path = str(out_file)
        log.info("corruption_artifact_saved path=%s", artifact_path)
    except Exception as exc:  # noqa: BLE001
        log.warning("corruption_artifact_save_failed error=%s", exc)

    # ── Persist training run ──────────────────────────────────────────
    try:
        run = GNNTrainingRun(
            model_version    = model_version,
            prediction_type  = CORRUPTION_PREDICTION_TYPE,
            source_backend   = dataset.source_backend_used,
            window_key       = dataset.window_key,
            window_end       = dataset.window_end,
            node_count       = len(dataset.entity_keys),
            edge_count       = len(dataset.edges),
            feature_dim      = feat_dim,
            positive_count   = dataset.positive_count,
            epochs           = epochs,
            train_loss       = float(train_result.metrics.get("train_loss") or 0.0),
            val_loss         = float(train_result.metrics.get("val_loss")   or 0.0),
            auc              = float(train_result.metrics.get("auc")        or 0.0),
            precision        = float(train_result.metrics.get("precision")  or 0.0),
            recall           = float(train_result.metrics.get("recall")     or 0.0),
            f1               = float(train_result.metrics.get("f1")         or 0.0),
            artifact_path    = artifact_path,
            params_json      = {
                "epochs": epochs, "hidden_dim": hidden_dim, "embed_dim": embed_dim,
                "dropout": dropout, "learning_rate": learning_rate,
                "weight_decay": weight_decay, "seed": seed, "domain": "corruption",
            },
            metrics_json     = {
                **train_result.metrics,
                "positive_count": dataset.positive_count,
                "negative_count": dataset.negative_count,
                "node_count":     len(dataset.entity_keys),
                "edge_count":     len(dataset.edges),
            },
        )
        db.add(run)
        db.flush()

        # ── Write per-entity predictions using MC-Dropout ─────────────
        model = build_sentinel_gnn(feat_dim, hidden_dim, embed_dim, dropout)
        model.load_state_dict(train_result.model_state)

        import torch as _torch  # noqa: PLC0415
        x = _torch.tensor(dataset.feature_matrix, dtype=_torch.float32)

        src_idx, dst_idx, edge_w = [], [], []
        n = len(dataset.entity_keys)
        for si, di, w in dataset.edges:
            src_idx += [si, di]
            dst_idx += [di, si]
            edge_w  += [w, w]
        for i in range(n):   # self-loops
            src_idx.append(i); dst_idx.append(i); edge_w.append(1.0)

        edge_src_t    = _torch.tensor(src_idx, dtype=_torch.long)
        edge_dst_t    = _torch.tensor(dst_idx, dtype=_torch.long)
        edge_weight_t = _torch.tensor(edge_w,  dtype=_torch.float32)

        mean_probs, uncertainties = predict_mc(
            model, x, edge_src_t, edge_dst_t, edge_weight_t, n_samples=20
        )

        created = updated = 0
        for i in range(n):
            prob        = float(mean_probs[i])
            uncertainty = float(uncertainties[i])
            score       = round(prob * 100.0, 4)
            flags       = list(dataset.node_meta[i].get("risk_flags") or [])
            reasons     = _reason_codes(prob, flags, dataset.entity_types[i])

            _write_prediction(
                db,
                entity_key    = dataset.entity_keys[i],
                entity_type   = dataset.entity_types[i],
                window_key    = dataset.window_key,
                window_end    = dataset.window_end,
                model_version = model_version,
                score         = score,
                prob          = prob,
                uncertainty   = uncertainty,
                reasons       = reasons,
                meta          = dataset.node_meta[i],
            )
            created += 1

        db.commit()
        log.info(
            "corruption_train_complete nodes=%d auc=%.4f predictions=%d artifact=%s",
            n, float(train_result.metrics.get("auc") or 0), created, artifact_path,
        )

    except Exception as exc:  # noqa: BLE001
        db.rollback()
        return {"status": "error", "stage": "persist", "detail": str(exc)}

    return {
        "status":          "ok",
        "domain":          "corruption",
        "window_key":      dataset.window_key,
        "window_end":      dataset.window_end.isoformat(),
        "nodes":           len(dataset.entity_keys),
        "edges":           len(dataset.edges),
        "positive_count":  dataset.positive_count,
        "negative_count":  dataset.negative_count,
        "predictions":     created,
        "artifact_path":   artifact_path,
        "metrics":         train_result.metrics,
        "legal_notice":    LEGAL_RISK_NOTICE,
    }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    import argparse  # noqa: PLC0415

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    p = argparse.ArgumentParser(description="Sentinel-KE Corruption GNN Training Worker")
    p.add_argument("--window-key",    default=CORRUPTION_WINDOW_KEY)
    p.add_argument("--window-end",    default=None, help="ISO timestamp override")
    p.add_argument("--max-entities",  type=int,   default=5000)
    p.add_argument("--max-edges",     type=int,   default=30_000)
    p.add_argument("--epochs",        type=int,   default=60)
    p.add_argument("--hidden-dim",    type=int,   default=64)
    p.add_argument("--embed-dim",     type=int,   default=32)
    p.add_argument("--dropout",       type=float, default=0.2)
    p.add_argument("--learning-rate", type=float, default=0.001)
    p.add_argument("--seed",          type=int,   default=42)
    p.add_argument("--model-version", default="corruption-gnn-v1")
    p.add_argument("--artifact-dir",  default="/app/artifacts/gnn")
    args = p.parse_args()

    window_end = None
    if args.window_end:
        window_end = datetime.fromisoformat(args.window_end.replace("Z", "+00:00"))

    db = SessionLocal()
    try:
        result = run_once(
            db             = db,
            window_key     = args.window_key,
            window_end     = window_end,
            max_entities   = args.max_entities,
            max_edges      = args.max_edges,
            epochs         = args.epochs,
            hidden_dim     = args.hidden_dim,
            embed_dim      = args.embed_dim,
            dropout        = args.dropout,
            learning_rate  = args.learning_rate,
            seed           = args.seed,
            model_version  = args.model_version,
            artifact_dir   = args.artifact_dir,
        )
        print(json.dumps(result, indent=2, default=str))
    finally:
        db.close()


if __name__ == "__main__":
    main()

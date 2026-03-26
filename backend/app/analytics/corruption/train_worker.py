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
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import and_, func, text
from sqlalchemy.orm import Session

from app.analytics.ai_models import (
    AIExplanation,
    AIPrediction,
    GNNTrainingRun,
    GraphFeatureSnapshot,
)
from app.analytics.layer3.evidence_graph import (
    build_entity_graph_paths,
    recent_entity_event_hashes,
)
from app.analytics.layer3.gnn_train_worker import (
    _apply_feedback_overrides,
    _calibrate_thresholds,
    _compute_feature_attribution_map,
    _compute_fairness_metrics,
    _compute_provenance_metrics,
    _label_ladder_counts,
    _label_source_counts,
    _latest_feedback_overrides,
    _mark_feedback_consumed,
    _operating_metrics_from_thresholds,
)
from app.analytics.layer3.post_prediction_pipeline import run_post_prediction_pipeline
from app.analytics.layer3.worker_heartbeat import mark_worker_finished, mark_worker_started
from app.analytics.explainability import (
    heuristic_signal_attributions,
    summarize_feature_attributions,
    summarize_group_scores,
    top_feature_hint,
)
from app.analytics.corruption.feature_builder import (
    CORRUPTION_PREDICTION_TYPE,
    CORRUPTION_WINDOW_KEY,
    corruption_training_label,
    snapshot_to_corruption_vector,
)
from app.analytics.corruption.relations import typed_edges_from_postgres
from app.analytics.layer3.gnn_backbone import (
    GNNDataset,
    _edges_from_postgres,
    assess_benchmark_readiness,
    collapse_edges,
)
from app.analytics.layer3.gnn_model import (
    train_graphsage,
)
from app.core.config import settings
from app.ledger.db import SessionLocal, engine

log = logging.getLogger("sentinel.corruption_train_worker")

LEGAL_RISK_NOTICE = (
    "AI output is a corruption risk indicator for investigative prioritisation only; "
    "it is not final proof and requires forensic / legal corroboration."
)
CORRUPTION_SNAPSHOT_LOOKBACK_DAYS = 90


# ---------------------------------------------------------------------------
# Dataset loader
# ---------------------------------------------------------------------------


def _corruption_provenance_by_entity(
    db: Session,
    *,
    entity_keys: Sequence[str],
    window_start: datetime,
    window_end: datetime,
) -> Dict[str, Dict[str, object]]:
    rows = db.execute(
        text(
            """
            SELECT
                ee.entity_key,
                COALESCE(sr.source_type, 'unknown') AS source_type,
                COUNT(*)::int AS n
            FROM event_entity_index ee
            JOIN event_log el ON el.event_hash = ee.event_hash
            LEFT JOIN source_registry sr ON sr.source_id = el.source_id
            WHERE ee.entity_key = ANY(:entity_keys)
              AND el.occurred_at >= :window_start
              AND el.occurred_at <= :window_end
            GROUP BY ee.entity_key, COALESCE(sr.source_type, 'unknown')
            """
        ),
        {
            "entity_keys": list(entity_keys),
            "window_start": window_start,
            "window_end": window_end,
        },
    ).fetchall()

    grouped: Dict[str, Dict[str, int]] = {}
    for entity_key, source_type, n in rows:
        grouped.setdefault(str(entity_key), {})
        grouped[str(entity_key)][str(source_type or "unknown").lower()] = int(n or 0)

    out: Dict[str, Dict[str, object]] = {}
    for entity_key in entity_keys:
        counts = grouped.get(str(entity_key), {})
        total = max(1, sum(int(v) for v in counts.values()))
        synthetic_count = int(counts.get("synthetic", 0))
        real_count = max(0, total - synthetic_count)
        if synthetic_count and real_count:
            provenance_tag = "mixed"
        elif real_count > 0:
            provenance_tag = "real"
        elif synthetic_count > 0:
            provenance_tag = "synthetic"
        else:
            provenance_tag = "unknown"
        out[str(entity_key)] = {
            "provenance_tag": provenance_tag,
            "real_signal_ratio": round(real_count / float(total), 6),
            "source_type_counts": counts,
        }
    return out

def _load_corruption_dataset(
    db: Session,
    *,
    window_key: str = CORRUPTION_WINDOW_KEY,
    window_end: Optional[datetime] = None,
    max_entities: int = 5000,
    max_edges: int = 30_000,
    min_edge_weight: int = 1,
    negative_multiplier: float = 1.5,
    minimum_negative_count: int = 5,
    minimum_negative_ratio: float = 0.1,
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

    snapshot_selection_start = window_end - timedelta(days=CORRUPTION_SNAPSHOT_LOOKBACK_DAYS)
    latest_snapshot_by_entity = (
        db.query(
            GraphFeatureSnapshot.entity_key.label("entity_key"),
            func.max(GraphFeatureSnapshot.window_end).label("latest_window_end"),
        )
        .filter(GraphFeatureSnapshot.window_key == window_key)
        .filter(GraphFeatureSnapshot.window_end >= snapshot_selection_start)
        .filter(GraphFeatureSnapshot.window_end <= window_end)
        .group_by(GraphFeatureSnapshot.entity_key)
        .subquery()
    )

    snapshots: List[GraphFeatureSnapshot] = (
        db.query(GraphFeatureSnapshot)
        .join(
            latest_snapshot_by_entity,
            and_(
                GraphFeatureSnapshot.entity_key == latest_snapshot_by_entity.c.entity_key,
                GraphFeatureSnapshot.window_end == latest_snapshot_by_entity.c.latest_window_end,
            ),
        )
        .filter(GraphFeatureSnapshot.window_key == window_key)
        .order_by(GraphFeatureSnapshot.event_count.desc(), GraphFeatureSnapshot.window_end.desc())
        .limit(max_entities)
        .all()
    )
    if not snapshots:
        log.warning(
            "corruption_dataset_empty: zero snapshots window_key=%s window_end=%s selection_start=%s",
            window_key,
            window_end,
            snapshot_selection_start,
        )
        return None

    window_start = min((snap.window_start for snap in snapshots if snap.window_start), default=window_end)
    provenance_by_entity = _corruption_provenance_by_entity(
        db,
        entity_keys=[str(s.entity_key) for s in snapshots],
        window_start=window_start,
        window_end=window_end,
    )

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

        outcome_label = f.get("outcome_label")
        if outcome_label is not None:
            try:
                outcome_label = int(outcome_label)
            except Exception:
                outcome_label = None

        label = corruption_training_label(
            risk_flags=flags,
            event_count=int(snap.event_count or 0),
            single_source=bool(f.get("single_source")),
            director_conflict="DIRECTOR_CONFLICT" in flags,
            outcome_label=outcome_label,
            entity_type=str(snap.entity_type),
            features=f,
        )

        entity_keys.append(str(snap.entity_key))
        entity_types.append(str(snap.entity_type))
        feature_matrix.append(vec)
        labels.append(label)
        provenance = dict(provenance_by_entity.get(str(snap.entity_key)) or {})
        node_meta.append({
            "entity_type":  str(snap.entity_type),
            "risk_flags":   flags,
            "event_count":  int(snap.event_count or 0),
            "features":     f,
            "corruption_events": f.get("corruption_events") or f.get("event_types") or {},
            "outcome_label": outcome_label,
            "label_source": "confirmed_outcome_label" if outcome_label in {0, 1} else "weak_label",
            "provenance_tag": provenance.get("provenance_tag", "unknown"),
            "real_signal_ratio": float(provenance.get("real_signal_ratio") or 0.0),
            "source_type_counts": dict(provenance.get("source_type_counts") or {}),
        })

        if label == 1:
            positive_count += 1
        else:
            negative_count += 1

    if positive_count == 0:
        log.warning("corruption_no_positives: all labels are 0 — check risk_flags seeding")

    # ── Edge extraction ───────────────────────────────────────────────
    cooccurrence_edges = _edges_from_postgres(
        db,
        entity_keys=entity_keys,
        window_start=window_start,
        window_end=window_end,
        min_edge_weight=min_edge_weight,
        max_edges=max_edges,
    )
    typed_edges = typed_edges_from_postgres(
        db,
        entity_keys=entity_keys,
        window_start=window_start,
        window_end=window_end,
        max_events=max(500, int(max_edges) * 6),
    )
    raw_edges = collapse_edges([*cooccurrence_edges, *typed_edges])

    key_to_idx = {k: i for i, k in enumerate(entity_keys)}
    edges: List[Tuple[int, int, float]] = []
    for src_k, dst_k, w in raw_edges:
        i = key_to_idx.get(src_k)
        j = key_to_idx.get(dst_k)
        if i is None or j is None or i == j:
            continue
        edges.append((i, j, math.log1p(max(0.0, float(w)))))

    log.info(
        "corruption_dataset_loaded nodes=%d positive=%d edges=%d cooccurrence_edges=%d typed_edges=%d window_key=%s",
        len(entity_keys), positive_count, len(edges), len(cooccurrence_edges), len(typed_edges), window_key,
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
        edge_source_counts  = {
            "postgres_cooccurrence": len(cooccurrence_edges),
            "postgres_typed": len(typed_edges),
            "postgres_total": len(edges),
        },
        positive_count      = positive_count,
        negative_count      = negative_count,
        benign_negative_count = negative_count,
        selection_metadata  = {
            "selection_strategy": "latest_entity_snapshot_lookback",
            "benchmark_readiness": assess_benchmark_readiness(
                total_count=len(labels),
                positive_count=positive_count,
                negative_count=negative_count,
                min_negative_count=minimum_negative_count,
                min_negative_ratio=minimum_negative_ratio,
            ),
        },
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


def _pattern_evidence(meta: Dict[str, Any]) -> List[str]:
    features = dict(meta.get("features") or {})
    flags = set(str(flag) for flag in (meta.get("risk_flags") or []))
    patterns: List[str] = []

    try:
        outcome_label = features.get("outcome_label")
        if outcome_label in {0, 1} and int(outcome_label) == 1:
            patterns.append("OUTCOME_BACKED_CORRUPTION")
    except Exception:  # noqa: BLE001
        pass

    if int(features.get("adverse_outcome_count") or 0) > 0 or int(features.get("sanction_event_count") or 0) > 0:
        patterns.append("ADVERSE_OUTCOME_PATTERN")
    if bool(features.get("single_source")):
        patterns.append("SINGLE_SOURCE_AWARD_PATTERN")
    if int(features.get("supplier_family_size") or 0) > 1:
        patterns.append("SUPPLIER_NETWORK_PATTERN")
    if float(features.get("related_party_ratio") or 0.0) >= 0.25:
        patterns.append("RELATED_PARTY_PATTERN")
    if float(features.get("payment_to_delivery_ratio_max") or 0.0) >= 0.8:
        patterns.append("PAYMENT_DELIVERY_MISMATCH_PATTERN")
    if float(features.get("threshold_splitting") or 0.0) >= 0.25:
        patterns.append("THRESHOLD_SPLITTING_PATTERN")
    if float(features.get("execution_rate") if features.get("execution_rate") is not None else 1.0) < 0.5:
        patterns.append("LOW_EXECUTION_PATTERN")
    if int(features.get("complaint_count") or 0) > 0:
        patterns.append("COMPLAINT_PATTERN")
    if int(features.get("quality_failure_count") or 0) > 0:
        patterns.append("QUALITY_FAILURE_PATTERN")
    if "DIRECTOR_CONFLICT" in flags:
        patterns.append("DIRECTOR_CONFLICT_PATTERN")
    if "DEBARRED_SUPPLIER" in flags:
        patterns.append("DEBARRED_SUPPLIER_PATTERN")
    if "SHELL_COMPANY" in flags:
        patterns.append("SHELL_COMPANY_PATTERN")
    if "PAYMENT_APPROVAL_BYPASS" in flags:
        patterns.append("PAYMENT_CONTROL_BYPASS_PATTERN")
    if "ADVANCE_PAYMENT_RISK" in flags:
        patterns.append("ADVANCE_PAYMENT_PATTERN")
    if "PROJECT_DELAY_RISK" in flags or int(features.get("delay_days_max") or 0) >= 30:
        patterns.append("PROJECT_DELAY_PATTERN")
    if "COMPLAINT_PRESSURE" in flags:
        patterns.append("COMPLAINT_PRESSURE_PATTERN")

    return sorted(set(patterns))


def _reason_codes(prob: float, flags: List[str], entity_type: str, meta: Dict[str, Any], *, is_indicator: bool) -> List[str]:
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
    reasons.extend(_pattern_evidence(meta))
    reasons.append("THRESHOLD_EXCEEDED" if is_indicator else "THRESHOLD_NOT_EXCEEDED")
    reasons.append("RISK_INDICATOR_ONLY_NOT_FINAL_PROOF")
    return sorted(set(reasons))


def _write_prediction(
    db: Session,
    *,
    entity_key: str,
    entity_type: str,
    window_key: str,
    window_start: datetime,
    window_end: datetime,
    model_version: str,
    score: float,
    prob: float,
    uncertainty: float,
    threshold_score: float,
    reasons: List[str],
    meta: Dict,
    feature_vector: Optional[List[float]],
    feature_contributions: Optional[List[float]],
) -> None:
    confidence = max(0.0, min(1.0, 1.0 - uncertainty))
    abstained  = uncertainty >= float(getattr(settings, "ai_uncertainty_abstain_threshold", 0.45))
    is_indicator = float(score) >= float(threshold_score)
    if abstained:
        reasons = sorted(set(reasons + ["UNCERTAIN_REQUIRES_ANALYST_REVIEW"]))

    if feature_vector and feature_contributions:
        explanation_method = "gradient_x_input"
        feature_attributions = summarize_feature_attributions(
            feature_values=feature_vector,
            feature_contributions=feature_contributions,
            top_k=max(1, int(settings.ai_explainability_top_k)),
        )
    else:
        explanation_method = "heuristic_signals"
        feature_attributions = heuristic_signal_attributions(
            event_count=int(meta.get("event_count") or 0),
            source_count=int((meta.get("features") or {}).get("source_count") or 0),
            event_types=dict(meta.get("corruption_events") or {}),
            risk_flags=list(meta.get("risk_flags") or []),
            top_k=max(1, int(settings.ai_explainability_top_k)),
        )
    group_scores = summarize_group_scores(feature_attributions)

    details = {
        "risk_flags":    meta.get("risk_flags", []),
        "pattern_evidence": _pattern_evidence(meta),
        "event_count":   meta.get("event_count", 0),
        "entity_threshold_score": round(float(threshold_score), 4),
        "risk_indicator": bool(is_indicator),
        "predicted_label": int(is_indicator),
        "confidence":    round(confidence, 6),
        "uncertainty":   round(uncertainty, 6),
        "abstained":     bool(abstained),
        "decision_source": "gnn",
        "domain":        "corruption",
        "label_source":  str(meta.get("label_source") or "weak_label"),
        "provenance_tag": str(meta.get("provenance_tag") or "unknown"),
        "outcome_label": meta.get("outcome_label"),
        "explanation_method": explanation_method,
        "feature_attributions": feature_attributions,
        "attribution_group_scores": group_scores,
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
    evidence_hashes = recent_entity_event_hashes(
        db,
        entity_key=entity_key,
        window_start=window_start,
        window_end=window_end,
        limit=20,
    )
    evidence_paths = build_entity_graph_paths(
        db,
        entity_key=entity_key,
        window_start=window_start,
        window_end=window_end,
    )
    payload = {
        "domain":       "corruption",
        "decision_source": "gnn",
        "window_end":   window_end.isoformat(),
        "explanation_method": explanation_method,
        "pattern_evidence": _pattern_evidence(meta),
        "feature_attributions": feature_attributions,
        "attribution_group_scores": group_scores,
        "top_feature_hint": top_feature_hint(feature_attributions, fallback="log_event_count"),
        "legal_notice": LEGAL_RISK_NOTICE,
    }
    if expl:
        expl.reason_codes = reasons
        expl.evidence_hashes = evidence_hashes
        expl.evidence_paths = evidence_paths
        expl.details_json = payload
    else:
        db.add(AIExplanation(
            prediction_id             = pred.id,
            reason_codes              = reasons,
            evidence_hashes           = evidence_hashes,
            evidence_paths            = evidence_paths,
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
    split_policy:  str   = "temporal_recency_holdout",
    val_ratio:     float = 0.2,
    minimum_negative_count: int = 5,
    minimum_negative_ratio: float = 0.1,
    seed:          int   = 42,
    model_version: str   = "corruption-gnn-v1",
    artifact_dir:  str   = "/app/artifacts/gnn",
    threshold_min_samples: int = 10,
    allow_demo_real_data_override: bool = False,
    allow_demo_fairness_override: bool = False,
) -> Dict:
    """
    Load corruption snapshot data, train SentinelGNN, write predictions.
    Returns a summary dict.
    """
    heartbeat_meta = {"prediction_type": CORRUPTION_PREDICTION_TYPE, "window_key": window_key}
    mark_worker_started(db, worker_name="corruption_train_worker", metadata=heartbeat_meta)
    # ── Load dataset ─────────────────────────────────────────────────
    dataset = _load_corruption_dataset(
        db,
        window_key      = window_key,
        window_end      = window_end,
        max_entities    = max_entities,
        max_edges       = max_edges,
        min_edge_weight = min_edge_weight,
        minimum_negative_count = minimum_negative_count,
        minimum_negative_ratio = minimum_negative_ratio,
    )
    if dataset is None:
        mark_worker_finished(db, worker_name="corruption_train_worker", status="no_data", detail="no_dataset", metadata=heartbeat_meta)
        return {"status": "no_data", "message": "Run synthetic_corruption_data first"}
    if not dataset.feature_matrix:
        mark_worker_finished(db, worker_name="corruption_train_worker", status="no_data", detail="no_features", metadata=heartbeat_meta)
        return {"status": "no_features"}

    feedback_overrides = _latest_feedback_overrides(
        db,
        entity_keys=dataset.entity_keys,
        prediction_type=CORRUPTION_PREDICTION_TYPE,
    )
    dataset, feedback_metrics, feedback_ids = _apply_feedback_overrides(
        dataset,
        feedback_overrides=feedback_overrides,
    )
    if feedback_metrics["override_count"] > 0:
        log.info(
            "corruption_feedback_overrides_applied total=%d positive=%d negative=%d new=%d",
            feedback_metrics["override_count"],
            feedback_metrics["positive_override_count"],
            feedback_metrics["negative_override_count"],
            feedback_metrics["new_feedback_count"],
        )

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
            split_policy  = split_policy,
            val_ratio     = val_ratio,
            seed          = seed,
            label_smoothing=0.05,
            pseudo_label_threshold=0.0,
        )
    except Exception as exc:
        db.rollback()
        mark_worker_finished(db, worker_name="corruption_train_worker", status="failed", detail=str(exc), metadata=heartbeat_meta)
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
        thresholds = _calibrate_thresholds(
            dataset=dataset,
            probabilities=train_result.probabilities,
            min_samples=threshold_min_samples,
            model_version=model_version,
            prediction_type=CORRUPTION_PREDICTION_TYPE,
        )
        base_metrics_fixed_threshold = {
            "accuracy": float(train_result.metrics.get("accuracy") or 0.0),
            "precision": float(train_result.metrics.get("precision") or 0.0),
            "recall": float(train_result.metrics.get("recall") or 0.0),
            "f1": float(train_result.metrics.get("f1") or 0.0),
            "threshold_probability": 0.5,
            "threshold_mode": "fixed_probability",
        }
        operating_metrics = _operating_metrics_from_thresholds(
            dataset=dataset,
            probabilities=train_result.probabilities,
            thresholds=thresholds,
        )
        fairness = _compute_fairness_metrics(
            entity_types=dataset.entity_types,
            labels=dataset.labels,
            probabilities=train_result.probabilities,
            thresholds_by_type=thresholds,
        )
        label_source_counts = _label_source_counts(dataset.node_meta)
        label_ladder = _label_ladder_counts(label_source_counts)
        benchmark_readiness = dict((dataset.selection_metadata or {}).get("benchmark_readiness") or {})
        effective_split_policy = str(train_result.metrics.get("split_policy") or split_policy)
        attribution_method, feature_contrib_by_idx = _compute_feature_attribution_map(
            dataset=dataset,
            model_state=dict(train_result.model_state or {}),
            hidden_dim=hidden_dim,
            embed_dim=embed_dim,
            dropout=dropout,
            temporal_decay=0.0,
            max_nodes=int(settings.ai_explainability_max_nodes),
        )
        fairness_gate_override_applied = False
        if fairness.get("fairness_flag") == "FAIL":
            disparity = float(fairness.get("max_positive_rate_disparity") or 0.0)
            threshold = float(settings.fairness_disparity_threshold)
            if allow_demo_fairness_override:
                fairness_gate_override_applied = True
                log.warning(
                    "corruption_fairness_gate_OVERRIDE_APPLIED model_version=%s max_positive_rate_disparity=%.3f threshold=%.3f",
                    model_version,
                    disparity,
                    threshold,
                )
            else:
                log.error(
                    "corruption_fairness_gate_BLOCKED model_version=%s max_positive_rate_disparity=%.3f threshold=%.3f",
                    model_version,
                    disparity,
                    threshold,
                )
                db.rollback()
                mark_worker_finished(db, worker_name="corruption_train_worker", status="blocked", detail="fairness_gate", metadata=heartbeat_meta)
                return {
                    "status": "blocked",
                    "gate": "fairness",
                    "model_version": model_version,
                    "max_positive_rate_disparity": disparity,
                    "threshold": threshold,
                    "detail": "Training run blocked by fairness governance gate.",
                }

        provenance = _compute_provenance_metrics(
            node_meta=dataset.node_meta,
            probabilities=train_result.probabilities,
            threshold_score=70.0,
        )
        min_real_ratio = max(0.0, min(1.0, float(settings.gnn_min_real_ratio)))
        real_ratio = float(provenance.get("real_ratio") or 0.0)
        real_data_gate_passed = real_ratio >= min_real_ratio
        real_data_gate_override_applied = False
        if not real_data_gate_passed:
            if allow_demo_real_data_override:
                real_data_gate_override_applied = True
                log.warning(
                    "corruption_real_data_gate_OVERRIDE_APPLIED model_version=%s real_ratio=%.3f min_required=%.3f",
                    model_version,
                    real_ratio,
                    min_real_ratio,
                )
            else:
                log.error(
                    "corruption_real_data_gate_BLOCKED model_version=%s real_ratio=%.3f min_required=%.3f",
                    model_version,
                    real_ratio,
                    min_real_ratio,
                )
                db.rollback()
                mark_worker_finished(db, worker_name="corruption_train_worker", status="blocked", detail="real_data_gate", metadata=heartbeat_meta)
                return {
                    "status": "blocked",
                    "gate": "real_data",
                    "model_version": model_version,
                    "real_ratio": real_ratio,
                    "min_real_ratio": min_real_ratio,
                    "detail": "Training run blocked by real-data governance gate.",
                }

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
            precision        = float(operating_metrics.get("precision")  or 0.0),
            recall           = float(operating_metrics.get("recall")     or 0.0),
            f1               = float(operating_metrics.get("f1")         or 0.0),
            artifact_path    = artifact_path,
            params_json      = {
                "epochs": epochs, "hidden_dim": hidden_dim, "embed_dim": embed_dim,
                "dropout": dropout, "learning_rate": learning_rate,
                "weight_decay": weight_decay, "seed": seed, "domain": "corruption",
                "split_policy": split_policy, "val_ratio": val_ratio,
                "minimum_negative_count": minimum_negative_count,
                "minimum_negative_ratio": minimum_negative_ratio,
                "threshold_min_samples": threshold_min_samples,
                "allow_demo_real_data_override": bool(allow_demo_real_data_override),
                "allow_demo_fairness_override": bool(allow_demo_fairness_override),
            },
            metrics_json     = {
                **train_result.metrics,
                "base_metrics_fixed_threshold": base_metrics_fixed_threshold,
                "operating_metrics": operating_metrics,
                "positive_count": dataset.positive_count,
                "negative_count": dataset.negative_count,
                "node_count":     len(dataset.entity_keys),
                "edge_count":     len(dataset.edges),
                "fairness":       fairness,
                "fairness_gate": {
                    "passed": fairness.get("fairness_flag") != "FAIL",
                    "override_applied": bool(fairness_gate_override_applied),
                    "mode": "demo_override" if fairness_gate_override_applied else "strict",
                },
                "provenance":     provenance,
                "real_data_gate": {
                    "min_real_ratio": min_real_ratio,
                    "passed": bool(real_data_gate_passed),
                    "effective_passed": bool(real_data_gate_passed or real_data_gate_override_applied),
                    "override_applied": bool(real_data_gate_override_applied),
                    "mode": "demo_override" if real_data_gate_override_applied else "strict",
                },
                "feedback": feedback_metrics,
                "evaluation_protocol": {
                    "temporal_policy": (
                        "last_seen_recency_holdout"
                        if effective_split_policy == "temporal_recency_holdout"
                        else "non_temporal_holdout"
                    ),
                    "holdout_policy": effective_split_policy,
                    "benchmarkable": bool(benchmark_readiness.get("benchmarkable")),
                    "benchmark_reasons": list(benchmark_readiness.get("reasons") or []),
                    "minimum_negative_count": int(benchmark_readiness.get("minimum_negative_count") or minimum_negative_count),
                    "minimum_negative_ratio": float(benchmark_readiness.get("minimum_negative_ratio") or minimum_negative_ratio),
                    "selected_window_end": dataset.window_end.isoformat(),
                    "selected_window_strategy": str((dataset.selection_metadata or {}).get("selection_strategy") or "latest_window"),
                    "calibration": {
                        "ece": float(train_result.metrics.get("calibration_ece") or 0.0),
                        "mce": float(train_result.metrics.get("calibration_mce") or 0.0),
                        "brier_score": float(train_result.metrics.get("brier_score") or 0.0),
                        "eval_samples": int(train_result.metrics.get("eval_samples") or 0),
                    },
                },
                "label_strategy": {
                    "label_source": (
                        "confirmed_outcomes_plus_feedback"
                        if any(key in label_source_counts for key in ("confirmed_outcome_label", "analyst_feedback"))
                        else "heuristic_procurement_flags"
                    ),
                    "label_quality": (
                        "mixed_supervision"
                        if any(key in label_source_counts for key in ("confirmed_outcome_label", "analyst_feedback"))
                        else "weak"
                    ),
                    "feedback_override_count": feedback_metrics["override_count"],
                    "new_feedback_count": feedback_metrics["new_feedback_count"],
                    "label_source_counts": label_source_counts,
                    "label_ladder": label_ladder,
                    "positive_definition": (
                        "Labels prefer confirmed audit, tribunal, sanction, or recovery outcomes first. "
                        "Analyst feedback overrides the remaining labels when present. Otherwise the model "
                        "falls back to entity-specific procurement weak-label patterns, for example "
                        "single-source-plus-conflict on tenders, related-party or payment-control anomalies "
                        "on accounts and payments, and supplier-network or shell-company evidence on suppliers."
                    ),
                    "eval_caveat": (
                        "AUC/F1/Precision/Recall are computed on a holdout split of the current supervision mix. "
                        "Where outcome-backed labels are sparse, the metrics still reflect a partially weakly "
                        "supervised corruption dataset rather than fully adjudicated national ground truth."
                    ),
                    "recommended_upgrade": (
                        "Increase confirmed audit, tribunal, and court outcomes to keep shifting supervision "
                        "up the label ladder before using these metrics as external performance claims."
                    ),
                },
                "dataset_selection": dict(dataset.selection_metadata or {}),
                "explainability": {
                    "method": attribution_method,
                    "top_k": int(settings.ai_explainability_top_k),
                    "ig_steps": int(settings.ai_explainability_ig_steps),
                    "model_based_rows": int(len(feature_contrib_by_idx)),
                },
            },
        )
        db.add(run)
        db.flush()

        created = updated = 0
        for i in range(len(dataset.entity_keys)):
            prob        = float(train_result.probabilities[i])
            uncertainty = float((train_result.uncertainties or [])[i] if train_result.uncertainties else (1.0 - abs(prob - 0.5) * 2.0))
            score       = round(prob * 100.0, 4)
            flags       = list(dataset.node_meta[i].get("risk_flags") or [])
            threshold_score = float((thresholds.get(str(dataset.entity_types[i])) or {}).get("threshold_score") or 75.0)
            is_indicator = score >= threshold_score
            reasons     = _reason_codes(prob, flags, dataset.entity_types[i], dataset.node_meta[i], is_indicator=is_indicator)

            _write_prediction(
                db,
                entity_key    = dataset.entity_keys[i],
                entity_type   = dataset.entity_types[i],
                window_key    = dataset.window_key,
                window_start  = dataset.window_start,
                window_end    = dataset.window_end,
                model_version = model_version,
                score         = score,
                prob          = prob,
                uncertainty   = uncertainty,
                threshold_score = threshold_score,
                reasons       = reasons,
                meta          = dataset.node_meta[i],
                feature_vector= dataset.feature_matrix[i],
                feature_contributions= feature_contrib_by_idx.get(i),
            )
            created += 1

        consumed_feedback = _mark_feedback_consumed(db, feedback_ids=feedback_ids)
        run.metrics_json = {
            **dict(run.metrics_json or {}),
            "feedback": {
                **feedback_metrics,
                "consumed_count": consumed_feedback,
            },
            "label_strategy": {
                **dict((run.metrics_json or {}).get("label_strategy") or {}),
                "consumed_feedback_count": consumed_feedback,
            },
        }
        db.commit()
        log.info(
            "corruption_train_complete nodes=%d auc=%.4f predictions=%d artifact=%s",
            len(dataset.entity_keys), float(train_result.metrics.get("auc") or 0), created, artifact_path,
        )

    except Exception as exc:  # noqa: BLE001
        db.rollback()
        mark_worker_finished(db, worker_name="corruption_train_worker", status="failed", detail=str(exc), metadata=heartbeat_meta)
        return {"status": "error", "stage": "persist", "detail": str(exc)}

    try:
        post_pipeline = run_post_prediction_pipeline(
            db=db,
            prediction_type=CORRUPTION_PREDICTION_TYPE,
            window_key=dataset.window_key,
            window_end=dataset.window_end,
            model_version=model_version,
            seed_legal_bundles=False,
        )
    except Exception as exc:  # noqa: BLE001
        mark_worker_finished(db, worker_name="corruption_train_worker", status="failed", detail=f"post_pipeline:{exc}", metadata=heartbeat_meta)
        raise
    mark_worker_finished(
        db,
        worker_name="corruption_train_worker",
        status="ok",
        detail="trained",
        metadata={**heartbeat_meta, "window_end": dataset.window_end.isoformat(), "predictions": int(created)},
    )

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
        "feedback_overrides_applied": feedback_metrics["override_count"],
        "feedback_consumed": consumed_feedback,
        "benchmarkable": bool(benchmark_readiness.get("benchmarkable")),
        "benchmark_reasons": list(benchmark_readiness.get("reasons") or []),
        "selected_window_strategy": str((dataset.selection_metadata or {}).get("selection_strategy") or "latest_window"),
        "fairness_gate_override_applied": bool(fairness_gate_override_applied),
        "real_data_gate_passed": bool(real_data_gate_passed),
        "real_data_gate_override_applied": bool(real_data_gate_override_applied),
        "model_based_explanations": int(len(feature_contrib_by_idx)),
        "artifact_path":   artifact_path,
        "post_pipeline":   post_pipeline,
        "metrics":         {
            **train_result.metrics,
            "base_metrics_fixed_threshold": base_metrics_fixed_threshold,
            "operating_metrics": operating_metrics,
        },
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
    p.add_argument(
        "--split-policy",
        default="temporal_recency_holdout",
        choices=["entity_hash_holdout", "temporal_recency_holdout", "random"],
    )
    p.add_argument("--val-ratio", type=float, default=0.2)
    p.add_argument("--minimum-negative-count", type=int, default=5)
    p.add_argument("--minimum-negative-ratio", type=float, default=0.1)
    p.add_argument("--threshold-min-samples", type=int, default=settings.gnn_threshold_min_samples)
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
            split_policy   = args.split_policy,
            val_ratio      = args.val_ratio,
            minimum_negative_count = args.minimum_negative_count,
            minimum_negative_ratio = args.minimum_negative_ratio,
            threshold_min_samples = args.threshold_min_samples,
            seed           = args.seed,
            model_version  = args.model_version,
            artifact_dir   = args.artifact_dir,
        )
        print(json.dumps(result, indent=2, default=str))
    finally:
        db.close()


if __name__ == "__main__":
    main()

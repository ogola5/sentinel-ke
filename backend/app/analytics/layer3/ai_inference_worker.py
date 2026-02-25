"""
Sentinel-KE AI Inference Worker

Execution path
--------------
1. GNN path  (preferred)
   Load the latest trained SentinelGNN artifact from GNNTrainingRun.artifact_path,
   build the full entity graph for the requested window, run a batched forward
   pass with MC-Dropout uncertainty, and write AIPrediction rows with
   decision_source = "gnn".

2. Heuristic fallback
   If no valid artifact exists (cold-start, torch missing, or corrupt file),
   fall back to the deterministic rule-based scorer.  decision_source = "heuristic".
   This preserves full system operability before the first training run.

All explanations, MITRE ATT&CK mappings, and D3FEND controls are generated
for both paths.
"""
from __future__ import annotations

import json
import logging
import math
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.analytics.ai_models import (
    AIExplanation,
    AIModelRollout,
    AIPrediction,
    GNNTrainingRun,
    GraphFeatureSnapshot,
)
from app.analytics.layer3.ai_intel import (
    build_counterfactual,
    event_types_to_attack_techniques,
    event_types_to_kill_chain_stage,
    reason_codes_to_d3fend_controls,
)
from app.analytics.layer3.gnn_backbone import (
    FEATURE_DIM,
    _edges_from_postgres,
    build_feature_vector,
)
from app.core.config import settings
from app.ledger.db import SessionLocal

log = logging.getLogger("sentinel.ai_inference_worker")


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _latest_window_end(db: Session, window_key: str) -> Optional[datetime]:
    return (
        db.query(func.max(GraphFeatureSnapshot.window_end))
        .filter(GraphFeatureSnapshot.window_key == window_key)
        .scalar()
    )


def _event_hashes(
    db: Session,
    *,
    entity_key: str,
    window_start: datetime,
    window_end: datetime,
    limit: int = 20,
) -> List[str]:
    rows = db.execute(
        text(
            """
            SELECT ee.event_hash
            FROM event_entity_index ee
            JOIN event_log el ON el.event_hash = ee.event_hash
            WHERE ee.entity_key = :entity_key
              AND el.occurred_at >= :start
              AND el.occurred_at <= :end
            ORDER BY el.occurred_at DESC
            LIMIT :limit
            """
        ),
        {"entity_key": entity_key, "start": window_start,
         "end": window_end, "limit": limit},
    ).fetchall()
    return [str(r[0]) for r in rows]


def _active_rollout(db: Session, prediction_type: str) -> Dict[str, object]:
    row = (
        db.query(AIModelRollout)
        .filter(AIModelRollout.prediction_type == prediction_type)
        .filter(AIModelRollout.status == "active")
        .order_by(AIModelRollout.updated_at.desc())
        .first()
    )
    if not row:
        return {
            "rollout_mode":          settings.ai_rollout_mode_default,
            "active_model_version":  "heuristic-v1",
            "shadow_model_version":  None,
            "canary_ratio":          float(settings.ai_canary_ratio_default),
        }
    return {
        "rollout_mode":          row.rollout_mode,
        "active_model_version":  row.active_model_version,
        "shadow_model_version":  row.shadow_model_version,
        "canary_ratio":          float(row.canary_ratio or 0.0),
    }


def _select_model_version(*, rollout: Dict[str, object], entity_key: str) -> str:
    mode   = str(rollout.get("rollout_mode") or "single").lower()
    active = str(rollout.get("active_model_version") or "heuristic-v1")
    shadow = str(rollout.get("shadow_model_version") or "") or None
    if mode not in {"shadow", "canary"} or not shadow:
        return active
    ratio  = max(0.0, min(1.0, float(rollout.get("canary_ratio") or 0.0)))
    bucket = (sum(ord(c) for c in str(entity_key)) % 1000) / 1000.0
    return shadow if bucket < ratio else active


def _write_prediction(
    db: Session,
    *,
    snap: GraphFeatureSnapshot,
    score: float,
    prob: float,
    uncertainty: float,
    reasons: List[str],
    decision_source: str,
    model_version: str,
    rollout: Dict[str, object],
    evidence_limit: int,
    prediction_type: str,
) -> None:
    """Upsert one AIPrediction + AIExplanation row."""
    confidence   = max(0.0, min(1.0, 1.0 - uncertainty))
    abstained    = uncertainty >= float(settings.ai_uncertainty_abstain_threshold)
    if abstained:
        reasons = sorted(set(reasons + ["UNCERTAIN_REQUIRES_ANALYST_REVIEW"]))

    event_types      = dict((snap.features or {}).get("event_types") or {})
    kill_chain_stage = event_types_to_kill_chain_stage(event_types)
    attack_techniques = event_types_to_attack_techniques(event_types)
    controls         = reason_codes_to_d3fend_controls(reasons)
    counterfactual   = build_counterfactual(
        probability=prob,
        threshold_score=75.0,
        top_feature_hint="event_count",
    )

    details_json = {
        "event_count":       int(snap.event_count or 0),
        "source_count":      int((snap.features or {}).get("source_count") or 0),
        "risk_flags":        list(snap.risk_flags or []),
        "event_types":       event_types,
        "confidence":        round(confidence, 6),
        "uncertainty":       round(uncertainty, 6),
        "abstained":         bool(abstained),
        "kill_chain_stage":  kill_chain_stage,
        "attack_techniques": attack_techniques,
        "rollout":           rollout,
        "decision_source":   decision_source,
    }

    pred = (
        db.query(AIPrediction)
        .filter(AIPrediction.entity_key    == snap.entity_key)
        .filter(AIPrediction.prediction_type == prediction_type)
        .filter(AIPrediction.window_key    == snap.window_key)
        .filter(AIPrediction.window_end    == snap.window_end)
        .first()
    )

    if pred:
        pred.score           = score
        pred.model_version   = model_version
        pred.confidence      = confidence
        pred.uncertainty     = uncertainty
        pred.abstained       = bool(abstained)
        pred.kill_chain_stage = kill_chain_stage
        pred.decision_source = decision_source
        pred.reason_codes    = reasons
        pred.details_json    = details_json
    else:
        pred = AIPrediction(
            entity_key      = snap.entity_key,
            entity_type     = snap.entity_type,
            prediction_type = prediction_type,
            window_key      = snap.window_key,
            window_end      = snap.window_end,
            model_version   = model_version,
            score           = score,
            confidence      = confidence,
            uncertainty     = uncertainty,
            abstained       = bool(abstained),
            kill_chain_stage = kill_chain_stage,
            decision_source = decision_source,
            reason_codes    = reasons,
            details_json    = details_json,
        )
        db.add(pred)
        db.flush()

    evidence = _event_hashes(
        db,
        entity_key   = snap.entity_key,
        window_start = snap.window_start,
        window_end   = snap.window_end,
        limit        = evidence_limit,
    )
    expl_payload = {
        "window_start":        snap.window_start.isoformat(),
        "window_end":          snap.window_end.isoformat(),
        "recommended_controls": controls,
        "counterfactual":      counterfactual,
        "kill_chain_stage":    kill_chain_stage,
        "decision_source":     decision_source,
    }
    expl = (
        db.query(AIExplanation)
        .filter(AIExplanation.prediction_id == pred.id)
        .first()
    )
    if expl:
        expl.reason_codes            = reasons
        expl.evidence_hashes         = evidence
        expl.evidence_paths          = []
        expl.recommended_controls_json = controls
        expl.counterfactual_json     = counterfactual
        expl.details_json            = expl_payload
    else:
        db.add(AIExplanation(
            prediction_id          = pred.id,
            reason_codes           = reasons,
            evidence_hashes        = evidence,
            evidence_paths         = [],
            recommended_controls_json = controls,
            counterfactual_json    = counterfactual,
            details_json           = expl_payload,
        ))


# ---------------------------------------------------------------------------
# GNN inference path
# ---------------------------------------------------------------------------

def _load_gnn_artifact(
    db: Session,
    prediction_type: str,
    window_key: str,
) -> Optional[Tuple[Dict, str, str]]:
    """
    Locate and load the latest trained GNN artifact.

    Returns (payload_dict, artifact_path, model_version) or None.
    """
    from sqlalchemy import desc  # noqa: PLC0415

    run = (
        db.query(GNNTrainingRun)
        .filter(GNNTrainingRun.prediction_type == prediction_type)
        .filter(GNNTrainingRun.window_key      == window_key)
        .filter(GNNTrainingRun.artifact_path.isnot(None))
        .order_by(desc(GNNTrainingRun.created_at))
        .first()
    )
    if not run or not run.artifact_path:
        log.info("gnn_artifact_not_found prediction_type=%s window_key=%s — using heuristic",
                 prediction_type, window_key)
        return None

    artifact_path = str(run.artifact_path)
    if not Path(artifact_path).exists():
        log.warning("gnn_artifact_missing path=%s", artifact_path)
        return None

    try:
        import torch  # noqa: PLC0415
        payload = torch.load(artifact_path, map_location="cpu", weights_only=False)
        return payload, artifact_path, str(run.model_version)
    except Exception as exc:  # noqa: BLE001
        log.warning("gnn_artifact_load_failed path=%s error=%s", artifact_path, exc)
        return None


def _gnn_reason_codes(
    prob: float,
    snap: GraphFeatureSnapshot,
) -> List[str]:
    """Generate reason codes for a GNN-scored entity."""
    reasons: List[str] = []
    flags       = set(snap.risk_flags or [])
    features    = snap.features or {}
    event_count = int(snap.event_count or 0)
    source_count = int(features.get("source_count") or 0)
    event_types  = dict(features.get("event_types") or {})

    if prob >= 0.9:
        reasons.append("GNN_RISK_CRITICAL")
    elif prob >= 0.75:
        reasons.append("GNN_RISK_HIGH")
    elif prob >= 0.55:
        reasons.append("GNN_RISK_ELEVATED")
    else:
        reasons.append("GNN_RISK_LOW")

    if source_count >= 3:
        reasons.append("MULTI_SOURCE")
    if event_count >= 20:
        reasons.append("EVENT_VOLUME_HIGH")
    elif event_count >= 8:
        reasons.append("EVENT_VOLUME_MED")
    if "CAMPAIGN_ENTITY" in flags:
        reasons.append("CAMPAIGN_LINKED")
    if "VPN_CLUSTER_MEMBER" in flags:
        reasons.append("VPN_INFRA_REUSE")
    if "DDOS_CLUSTER_MEMBER" in flags:
        reasons.append("DDOS_INFRA_REUSE")
    if "DDOS_ALERT_SERVICE" in flags or "DDOS_ALERT_ENDPOINT" in flags:
        reasons.append("DDOS_ALERT_ACTIVE")
    if event_types.get("SIM_SWAP_EVENT", 0) > 0:
        reasons.append("SIM_SWAP_SIGNAL")
    if event_types.get("PHISHING_MESSAGE_EVENT", 0) > 0:
        reasons.append("PHISHING_SIGNAL")
    reasons.append("RISK_INDICATOR_ONLY_NOT_FINAL_PROOF")
    return sorted(set(reasons))


def _run_gnn_path(
    db: Session,
    *,
    snapshots: List[GraphFeatureSnapshot],
    artifact_payload: Dict,
    model_version: str,
    prediction_type: str,
    rollout: Dict,
    evidence_limit: int,
) -> int:
    """
    Run the full GNN forward pass and write predictions.

    Steps:
        1. Reconstruct SentinelGNN from artifact metadata
        2. Build 42-dim feature matrix from GraphFeatureSnapshot rows
        3. Extract co-occurrence edges from Postgres for this window
        4. Run MC-Dropout inference → mean probabilities + uncertainties
        5. Upsert AIPrediction + AIExplanation for each entity
    """
    try:
        import torch  # noqa: PLC0415
    except ImportError:
        log.warning("gnn_inference_torch_missing — falling back to heuristic")
        return -1   # caller interprets -1 as "retry with heuristic"

    from app.analytics.layer3.gnn_model import build_sentinel_gnn, predict_mc  # noqa: PLC0415

    meta       = artifact_payload.get("metadata", {})
    feat_dim   = int(meta.get("feature_dim") or meta.get("feat_dim") or FEATURE_DIM)
    hidden_dim = int(meta.get("hidden_dim") or 64)
    embed_dim  = int(meta.get("embed_dim")  or 32)
    dropout    = float(meta.get("dropout")  or 0.2)

    model = build_sentinel_gnn(feat_dim, hidden_dim, embed_dim, dropout)
    model.load_state_dict(artifact_payload["model_state"])
    model.eval()

    # --- feature matrix -------------------------------------------------
    feature_rows: List[List[float]] = []
    for snap in snapshots:
        features_raw = snap.features or {}
        vec = build_feature_vector(
            entity_type     = str(snap.entity_type),
            event_count     = int(snap.event_count or 0),
            source_count    = int(features_raw.get("source_count") or 0),
            degree          = int(snap.degree or 0),
            weighted_degree = int(snap.weighted_degree or 0),
            risk_flags      = list(snap.risk_flags or []),
            features        = features_raw,
            window_start    = snap.window_start,
            window_end      = snap.window_end,
            first_seen      = snap.first_seen,
            last_seen       = snap.last_seen,
        )
        # Pad or truncate to match artifact's feat_dim (handles version skew)
        if len(vec) < feat_dim:
            vec = vec + [0.0] * (feat_dim - len(vec))
        elif len(vec) > feat_dim:
            vec = vec[:feat_dim]
        # Sanitise non-finite values
        feature_rows.append([0.0 if not math.isfinite(v) else v for v in vec])

    # --- edge list from Postgres ----------------------------------------
    entity_keys   = [str(s.entity_key) for s in snapshots]
    key_to_idx    = {k: i for i, k in enumerate(entity_keys)}
    window_start  = min(s.window_start for s in snapshots)
    window_end_ts = max(s.window_end   for s in snapshots)

    raw_edges = _edges_from_postgres(
        db,
        entity_keys=entity_keys,
        window_start=window_start,
        window_end=window_end_ts,
        min_edge_weight=1,
        max_edges=30_000,
    )

    src_idx: List[int]   = []
    dst_idx: List[int]   = []
    edge_w:  List[float] = []
    for src_k, dst_k, w in raw_edges:
        i = key_to_idx.get(src_k)
        j = key_to_idx.get(dst_k)
        if i is None or j is None or i == j:
            continue
        ew = math.log1p(max(0.0, float(w)))
        src_idx += [i, j]
        dst_idx += [j, i]
        edge_w  += [ew, ew]

    n_nodes = len(snapshots)
    for i in range(n_nodes):         # self-loops
        src_idx.append(i)
        dst_idx.append(i)
        edge_w.append(1.0)

    x            = torch.tensor(feature_rows,          dtype=torch.float32)
    edge_src_t   = torch.tensor(src_idx,               dtype=torch.long)
    edge_dst_t   = torch.tensor(dst_idx,               dtype=torch.long)
    edge_weight_t = torch.tensor(edge_w,               dtype=torch.float32)

    # --- MC-Dropout inference -------------------------------------------
    mean_probs, uncertainties = predict_mc(
        model, x, edge_src_t, edge_dst_t, edge_weight_t, n_samples=20
    )

    # --- write predictions ----------------------------------------------
    created = 0
    for i, snap in enumerate(snapshots):
        prob        = float(mean_probs[i])
        uncertainty = float(uncertainties[i])
        score       = round(prob * 100.0, 4)
        reasons     = _gnn_reason_codes(prob, snap)

        _write_prediction(
            db,
            snap            = snap,
            score           = score,
            prob            = prob,
            uncertainty     = uncertainty,
            reasons         = reasons,
            decision_source = "gnn",
            model_version   = model_version,
            rollout         = rollout,
            evidence_limit  = evidence_limit,
            prediction_type = prediction_type,
        )
        created += 1

    db.commit()
    log.info("gnn_inference_complete entities=%d model_version=%s", created, model_version)
    return created


# ---------------------------------------------------------------------------
# Heuristic fallback path (original deterministic scorer)
# ---------------------------------------------------------------------------

def _score_heuristic(
    snapshot: GraphFeatureSnapshot,
) -> Tuple[float, List[str], Dict[str, object]]:
    """
    Deterministic rule-based scorer.  Used when no trained artifact exists.
    decision_source = 'heuristic'.
    """
    flags        = set(snapshot.risk_flags or [])
    features     = snapshot.features or {}
    event_count  = int(snapshot.event_count or 0)
    source_count = int(features.get("source_count") or 0)
    last_seen_age = features.get("last_seen_age_sec")

    score = min(100.0, (
        min(40.0, event_count * 2.0)
        + (30.0 if ("DDOS_ALERT_SERVICE" in flags or "DDOS_ALERT_ENDPOINT" in flags) else 0.0)
        + (20.0 if "VPN_CLUSTER_MEMBER"  in flags else 0.0)
        + (15.0 if "CAMPAIGN_ENTITY"      in flags else 0.0)
        + (10.0 if "DDOS_CLUSTER_MEMBER"  in flags else 0.0)
        + (10.0 if source_count >= 3      else 0.0)
        + (5.0  if isinstance(last_seen_age, (int, float)) and last_seen_age <= 300 else 0.0)
    ))

    reasons: List[str] = []
    event_types = features.get("event_types") or {}
    if event_count >= 20:
        reasons.append("EVENT_VOLUME_HIGH")
    elif event_count >= 5:
        reasons.append("EVENT_VOLUME_MED")
    if source_count >= 3:
        reasons.append("MULTI_SOURCE")
    if isinstance(last_seen_age, (int, float)) and last_seen_age <= 300:
        reasons.append("RECENT_ACTIVITY")
    if "DDOS_ALERT_SERVICE" in flags or "DDOS_ALERT_ENDPOINT" in flags:
        reasons.append("DDOS_ALERT_ACTIVE")
    if "VPN_CLUSTER_MEMBER" in flags:
        reasons.append("VPN_INFRA_REUSE")
    if "CAMPAIGN_ENTITY" in flags:
        reasons.append("CAMPAIGN_LINKED")
    if "DDOS_CLUSTER_MEMBER" in flags:
        reasons.append("DDOS_INFRA_REUSE")
    if event_types.get("DDOS_SIGNAL_EVENT"):
        reasons.append("DDOS_SIGNAL_SEEN")
    if event_types.get("SIM_SWAP_EVENT"):
        reasons.append("SIM_SWAP_SIGNAL")
    if event_types.get("TRANSACTION_EVENT"):
        reasons.append("TXN_ACTIVITY")
    if event_types.get("PHISHING_MESSAGE_EVENT"):
        reasons.append("PHISHING_SIGNAL")
    if not reasons:
        reasons.append("LOW_SIGNAL")

    details = {
        "event_count":  event_count,
        "source_count": source_count,
        "risk_flags":   list(flags),
        "event_types":  dict(event_types),
    }
    return score, reasons, details


def _run_heuristic_path(
    db: Session,
    *,
    snapshots: List[GraphFeatureSnapshot],
    prediction_type: str,
    rollout: Dict,
    evidence_limit: int,
) -> int:
    created = 0
    for snap in snapshots:
        score, reasons, _ = _score_heuristic(snap)
        prob        = max(0.0, min(1.0, score / 100.0))
        uncertainty = max(0.0, min(1.0, 1.0 - abs(prob - 0.5) * 2.0))
        model_version = _select_model_version(rollout=rollout, entity_key=str(snap.entity_key))

        _write_prediction(
            db,
            snap            = snap,
            score           = score,
            prob            = prob,
            uncertainty     = uncertainty,
            reasons         = reasons,
            decision_source = "heuristic",
            model_version   = model_version,
            rollout         = rollout,
            evidence_limit  = evidence_limit,
            prediction_type = prediction_type,
        )
        created += 1

    db.commit()
    return created


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_once(
    *,
    db: Session,
    window_key:      str = "Wshort",
    window_end:      Optional[datetime] = None,
    prediction_type: str = "risk",
    max_entities:    int = 5000,
    evidence_limit:  int = 20,
) -> int:
    """
    Score all entities for the given window.

    Tries the GNN path first; falls back to heuristic if:
    - No trained artifact found
    - PyTorch not installed
    - Artifact file missing or corrupt
    """
    if window_end is None:
        window_end = _latest_window_end(db, window_key)
    if window_end is None:
        return 0

    rollout = _active_rollout(db, prediction_type)

    snapshots = (
        db.query(GraphFeatureSnapshot)
        .filter(GraphFeatureSnapshot.window_key == window_key)
        .filter(GraphFeatureSnapshot.window_end == window_end)
        .limit(max_entities)
        .all()
    )
    if not snapshots:
        return 0

    # Attempt GNN path
    artifact_info = _load_gnn_artifact(db, prediction_type, window_key)
    if artifact_info is not None:
        payload, _, model_version = artifact_info
        result = _run_gnn_path(
            db,
            snapshots       = snapshots,
            artifact_payload = payload,
            model_version   = model_version,
            prediction_type = prediction_type,
            rollout         = rollout,
            evidence_limit  = evidence_limit,
        )
        if result >= 0:
            return result
        # result == -1 means torch missing mid-run → fall through

    # Heuristic fallback
    log.info("inference_using_heuristic window_key=%s entities=%d",
             window_key, len(snapshots))
    return _run_heuristic_path(
        db,
        snapshots       = snapshots,
        prediction_type = prediction_type,
        rollout         = rollout,
        evidence_limit  = evidence_limit,
    )


def main() -> None:
    """CLI entry point: python -m app.analytics.layer3.ai_inference_worker"""
    import argparse  # noqa: PLC0415

    p = argparse.ArgumentParser(description="Sentinel-KE AI inference worker")
    p.add_argument("--window-key",      default="Wshort")
    p.add_argument("--window-end",      default=None, help="ISO timestamp override")
    p.add_argument("--prediction-type", default="risk")
    p.add_argument("--max-entities",    type=int, default=5000)
    p.add_argument("--evidence-limit",  type=int, default=20)
    args = p.parse_args()

    window_end = None
    if args.window_end:
        window_end = datetime.fromisoformat(args.window_end.replace("Z", "+00:00"))

    db_session = SessionLocal()
    try:
        n = run_once(
            db             = db_session,
            window_key     = args.window_key,
            window_end     = window_end,
            prediction_type = args.prediction_type,
            max_entities   = args.max_entities,
            evidence_limit = args.evidence_limit,
        )
        print(json.dumps({"predictions_written": n}))
    finally:
        db_session.close()


if __name__ == "__main__":
    main()

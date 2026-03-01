from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_db, pagination_params, require_central_access
from app.core.config import settings
from app.core.rate_limit import limiter
from app.analytics.ai_models import (
    AIExplanation,
    AIAttackPathScore,
    AIAttackTechniqueHit,
    AICampaignRiskIndicator,
    AIDecisionFusion,
    AIDriftReport,
    AIFeedbackLabel,
    AIInputAnomalyAlert,
    AILinkPrediction,
    AIModelRollout,
    AIPrediction,
    AIRiskThreshold,
    EntityRiskBaseline,
    GNNTrainingRun,
    ThreatIntelIndicator,
)
from app.analytics.layer3.threat_intel_worker import export_stix_bundle, import_stix_bundle

log = logging.getLogger("sentinel.api.ai")
router = APIRouter(prefix="/v1/ai", tags=["ai"])


def _severity_from_score(score: float) -> str:
    s = float(score)
    if s >= 90:
        return "critical"
    if s >= 75:
        return "high"
    if s >= 55:
        return "medium"
    return "low"


@router.get("/predictions")
def list_predictions(
    pagination: dict = Depends(pagination_params),
    prediction_type: str | None = Query(default=None),
    window_key: str | None = Query(default=None),
    entity_key: str | None = Query(default=None),
    model_version: str | None = Query(default=None),
    abstained: bool | None = Query(default=None),
    db: Session = Depends(get_db),
):
    q = db.query(AIPrediction)
    if prediction_type:
        q = q.filter(AIPrediction.prediction_type == prediction_type)
    if window_key:
        q = q.filter(AIPrediction.window_key == window_key)
    if entity_key:
        q = q.filter(AIPrediction.entity_key == entity_key)
    if model_version:
        q = q.filter(AIPrediction.model_version == model_version)
    if abstained is not None:
        q = q.filter(AIPrediction.abstained == bool(abstained))

    rows = (
        q.order_by(AIPrediction.window_end.desc(), AIPrediction.score.desc())
        .offset(pagination["offset"])
        .limit(pagination["limit"])
        .all()
    )
    return {
        "limit": pagination["limit"],
        "offset": pagination["offset"],
        "items": [
            {
                "id": str(r.id),
                "entity_key": r.entity_key,
                "entity_type": r.entity_type,
                "prediction_type": r.prediction_type,
                "model_version": r.model_version,
                "window_key": r.window_key,
                "window_end": r.window_end.isoformat(),
                "score": r.score,
                "confidence": r.confidence,
                "uncertainty": r.uncertainty,
                "abstained": r.abstained,
                "kill_chain_stage": r.kill_chain_stage,
                "decision_source": r.decision_source,
                "reason_codes": r.reason_codes,
                "details": r.details_json,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ],
    }


@router.get("/predictions/{prediction_id}")
def get_prediction(prediction_id: str, db: Session = Depends(get_db)):
    r = db.query(AIPrediction).filter(AIPrediction.id == prediction_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="prediction_not_found")
    return {
        "id": str(r.id),
        "entity_key": r.entity_key,
        "entity_type": r.entity_type,
        "prediction_type": r.prediction_type,
        "model_version": r.model_version,
        "window_key": r.window_key,
        "window_end": r.window_end.isoformat(),
        "score": r.score,
        "confidence": r.confidence,
        "uncertainty": r.uncertainty,
        "abstained": r.abstained,
        "kill_chain_stage": r.kill_chain_stage,
        "decision_source": r.decision_source,
        "reason_codes": r.reason_codes,
        "details": r.details_json,
        "created_at": r.created_at.isoformat(),
    }


@router.get("/explanations/{prediction_id}")
def get_explanation(prediction_id: str, db: Session = Depends(get_db)):
    r = db.query(AIPrediction).filter(AIPrediction.id == prediction_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="prediction_not_found")
    expl = db.query(AIExplanation).filter(AIExplanation.prediction_id == r.id).first()
    if not expl:
        raise HTTPException(status_code=404, detail="explanation_not_found")
    return {
        "prediction_id": str(r.id),
        "entity_key": r.entity_key,
        "prediction_type": r.prediction_type,
        "window_key": r.window_key,
        "window_end": r.window_end.isoformat(),
        "score": r.score,
        "reason_codes": expl.reason_codes,
        "evidence_hashes": expl.evidence_hashes,
        "evidence_paths": expl.evidence_paths,
        "recommended_controls": expl.recommended_controls_json,
        "counterfactual": expl.counterfactual_json,
        "details": expl.details_json,
        "created_at": expl.created_at.isoformat(),
    }


@router.get("/gnn/runs")
def list_gnn_runs(
    pagination: dict = Depends(pagination_params),
    model_version: str | None = Query(default=None),
    prediction_type: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    q = db.query(GNNTrainingRun)
    if model_version:
        q = q.filter(GNNTrainingRun.model_version == model_version)
    if prediction_type:
        q = q.filter(GNNTrainingRun.prediction_type == prediction_type)

    rows = (
        q.order_by(GNNTrainingRun.created_at.desc())
        .offset(pagination["offset"])
        .limit(pagination["limit"])
        .all()
    )
    return {
        "limit": pagination["limit"],
        "offset": pagination["offset"],
        "items": [
            {
                "id": str(r.id),
                "model_version": r.model_version,
                "prediction_type": r.prediction_type,
                "source_backend": r.source_backend,
                "window_key": r.window_key,
                "window_end": r.window_end.isoformat(),
                "node_count": r.node_count,
                "edge_count": r.edge_count,
                "feature_dim": r.feature_dim,
                "positive_count": r.positive_count,
                "epochs": r.epochs,
                "train_loss": r.train_loss,
                "val_loss": r.val_loss,
                "auc": r.auc,
                "precision": r.precision,
                "recall": r.recall,
                "f1": r.f1,
                "artifact_path": r.artifact_path,
                "params": r.params_json,
                "metrics": r.metrics_json,
                "fairness": (r.metrics_json or {}).get("fairness", {}),
                "fairness_blocked": (
                    (r.metrics_json or {}).get("fairness", {}).get(
                        "max_positive_rate_disparity", 0
                    ) > settings.fairness_disparity_threshold
                ),
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ],
    }


class GNNTrainRequest(BaseModel):
    domain: Literal["cyber", "corruption"] = "cyber"
    epochs: int = 60
    model_version: str | None = None


def _run_cyber_train(epochs: int, model_version: str) -> None:
    from app.analytics.layer3.gnn_train_worker import run_once
    from app.ledger.db import SessionLocal
    db = SessionLocal()
    try:
        result = run_once(
            db=db,
            window_key="Wmid",
            epochs=epochs,
            model_version=model_version,
        )
        log.info("gnn_train_cyber_done: %s", result)
    except Exception as exc:
        log.error("gnn_train_cyber_failed: %s", exc)
    finally:
        db.close()


def _run_corruption_train(epochs: int, model_version: str) -> None:
    from app.analytics.corruption.train_worker import run_once
    from app.ledger.db import SessionLocal
    db = SessionLocal()
    try:
        result = run_once(
            db=db,
            window_key="Wcorruption",
            epochs=epochs,
            model_version=model_version,
        )
        log.info("gnn_train_corruption_done: %s", result)
    except Exception as exc:
        log.error("gnn_train_corruption_failed: %s", exc)
    finally:
        db.close()


@router.post("/gnn/train", status_code=202)
@limiter.limit("5/minute")
def trigger_gnn_train(
    request: Request,
    body: GNNTrainRequest,
    background_tasks: BackgroundTasks,
    _principal=Depends(require_central_access),
):
    """
    Trigger a GNN retraining run in the background.

    domain = "cyber"       → cyber threat GNN (window_key Wmid, feat_dim 44)
    domain = "corruption"  → corruption risk GNN (window_key Wcorruption, feat_dim 42)

    Returns immediately; poll GET /v1/ai/gnn/runs to see the new run when complete.
    """
    default_versions = {"cyber": "gnn-sage-v1", "corruption": "corruption-gnn-v1"}
    mv = body.model_version or default_versions[body.domain]

    if body.domain == "cyber":
        background_tasks.add_task(_run_cyber_train, body.epochs, mv)
    else:
        background_tasks.add_task(_run_corruption_train, body.epochs, mv)

    return {
        "accepted": True,
        "domain": body.domain,
        "model_version": mv,
        "epochs": body.epochs,
        "message": "Training started in background. Poll GET /v1/ai/gnn/runs for results.",
    }


@router.get("/gnn/runs/{run_id}")
def get_gnn_run(run_id: str, db: Session = Depends(get_db)):
    r = db.query(GNNTrainingRun).filter(GNNTrainingRun.id == run_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="gnn_run_not_found")
    return {
        "id": str(r.id),
        "model_version": r.model_version,
        "prediction_type": r.prediction_type,
        "source_backend": r.source_backend,
        "window_key": r.window_key,
        "window_end": r.window_end.isoformat(),
        "node_count": r.node_count,
        "edge_count": r.edge_count,
        "feature_dim": r.feature_dim,
        "positive_count": r.positive_count,
        "epochs": r.epochs,
        "train_loss": r.train_loss,
        "val_loss": r.val_loss,
        "auc": r.auc,
        "precision": r.precision,
        "recall": r.recall,
        "f1": r.f1,
        "artifact_path": r.artifact_path,
        "params": r.params_json,
        "metrics": r.metrics_json,
        "created_at": r.created_at.isoformat(),
    }


@router.get("/thresholds")
def list_thresholds(
    pagination: dict = Depends(pagination_params),
    model_version: str | None = Query(default=None),
    prediction_type: str | None = Query(default=None),
    entity_type: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    q = db.query(AIRiskThreshold)
    if model_version:
        q = q.filter(AIRiskThreshold.model_version == model_version)
    if prediction_type:
        q = q.filter(AIRiskThreshold.prediction_type == prediction_type)
    if entity_type:
        q = q.filter(AIRiskThreshold.entity_type == entity_type)

    rows = (
        q.order_by(AIRiskThreshold.window_end.desc(), AIRiskThreshold.entity_type.asc())
        .offset(pagination["offset"])
        .limit(pagination["limit"])
        .all()
    )
    return {
        "limit": pagination["limit"],
        "offset": pagination["offset"],
        "items": [
            {
                "id": str(r.id),
                "model_version": r.model_version,
                "prediction_type": r.prediction_type,
                "entity_type": r.entity_type,
                "window_key": r.window_key,
                "window_end": r.window_end.isoformat(),
                "threshold_score": r.threshold_score,
                "method": r.method,
                "sample_count": r.sample_count,
                "positive_count": r.positive_count,
                "cost_weight": r.cost_weight,
                "metrics": r.metrics_json,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ],
    }


@router.get("/campaign-indicators")
def list_campaign_indicators(
    pagination: dict = Depends(pagination_params),
    prediction_type: str | None = Query(default=None),
    min_score: float | None = Query(default=None, ge=0.0, le=100.0),
    severity: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    q = db.query(AICampaignRiskIndicator)
    if prediction_type:
        q = q.filter(AICampaignRiskIndicator.prediction_type == prediction_type)
    if min_score is not None:
        q = q.filter(AICampaignRiskIndicator.score >= min_score)
    if severity:
        q = q.filter(AICampaignRiskIndicator.severity == severity)

    rows = (
        q.order_by(AICampaignRiskIndicator.window_end.desc(), AICampaignRiskIndicator.score.desc())
        .offset(pagination["offset"])
        .limit(pagination["limit"])
        .all()
    )
    return {
        "limit": pagination["limit"],
        "offset": pagination["offset"],
        "items": [
            {
                "id": str(r.id),
                "campaign_id": str(r.campaign_id),
                "prediction_type": r.prediction_type,
                "model_version": r.model_version,
                "window_key": r.window_key,
                "window_end": r.window_end.isoformat(),
                "score": r.score,
                "severity": r.severity,
                "flagged_entity_count": r.flagged_entity_count,
                "total_entity_count": r.total_entity_count,
                "reason_codes": r.reason_codes,
                "details": r.details_json,
                "evidence_entity_keys": r.evidence_entity_keys,
                "created_at": r.created_at.isoformat(),
                "updated_at": r.updated_at.isoformat(),
            }
            for r in rows
        ],
    }


@router.get("/techniques")
def list_techniques(
    pagination: dict = Depends(pagination_params),
    prediction_type: str | None = Query(default=None),
    entity_key: str | None = Query(default=None),
    technique_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    q = db.query(AIAttackTechniqueHit)
    if prediction_type:
        q = q.filter(AIAttackTechniqueHit.prediction_type == prediction_type)
    if entity_key:
        q = q.filter(AIAttackTechniqueHit.entity_key == entity_key)
    if technique_id:
        q = q.filter(AIAttackTechniqueHit.technique_id == technique_id)

    rows = (
        q.order_by(AIAttackTechniqueHit.window_end.desc(), AIAttackTechniqueHit.confidence.desc())
        .offset(pagination["offset"])
        .limit(pagination["limit"])
        .all()
    )
    return {
        "limit": pagination["limit"],
        "offset": pagination["offset"],
        "items": [
            {
                "id": str(r.id),
                "entity_key": r.entity_key,
                "prediction_type": r.prediction_type,
                "window_key": r.window_key,
                "window_end": r.window_end.isoformat(),
                "technique_id": r.technique_id,
                "tactic": r.tactic,
                "confidence": r.confidence,
                "source": r.source_json,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ],
    }


@router.get("/path-scores")
def list_path_scores(
    pagination: dict = Depends(pagination_params),
    prediction_type: str | None = Query(default=None),
    entity_key: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    q = db.query(AIAttackPathScore)
    if prediction_type:
        q = q.filter(AIAttackPathScore.prediction_type == prediction_type)
    if entity_key:
        q = q.filter(AIAttackPathScore.entity_key == entity_key)

    rows = (
        q.order_by(AIAttackPathScore.window_end.desc(), AIAttackPathScore.path_score.desc())
        .offset(pagination["offset"])
        .limit(pagination["limit"])
        .all()
    )
    return {
        "limit": pagination["limit"],
        "offset": pagination["offset"],
        "items": [
            {
                "id": str(r.id),
                "entity_key": r.entity_key,
                "prediction_type": r.prediction_type,
                "window_key": r.window_key,
                "window_end": r.window_end.isoformat(),
                "path_score": r.path_score,
                "hop_count": r.hop_count,
                "evidence_entity_keys": r.evidence_entity_keys,
                "details": r.details_json,
            }
            for r in rows
        ],
    }


@router.get("/link-predictions")
def list_link_predictions(
    pagination: dict = Depends(pagination_params),
    model_version: str | None = Query(default=None),
    prediction_type: str | None = Query(default=None),
    min_score: float | None = Query(default=None),
    db: Session = Depends(get_db),
):
    q = db.query(AILinkPrediction)
    if model_version:
        q = q.filter(AILinkPrediction.model_version == model_version)
    if prediction_type:
        q = q.filter(AILinkPrediction.prediction_type == prediction_type)
    if min_score is not None:
        q = q.filter(AILinkPrediction.score >= min_score)

    rows = (
        q.order_by(AILinkPrediction.window_end.desc(), AILinkPrediction.score.desc())
        .offset(pagination["offset"])
        .limit(pagination["limit"])
        .all()
    )
    return {
        "limit": pagination["limit"],
        "offset": pagination["offset"],
        "items": [
            {
                "id": str(r.id),
                "src_entity_key": r.src_entity_key,
                "dst_entity_key": r.dst_entity_key,
                "prediction_type": r.prediction_type,
                "model_version": r.model_version,
                "window_key": r.window_key,
                "window_end": r.window_end.isoformat(),
                "score": r.score,
                "method": r.method,
                "details": r.details_json,
            }
            for r in rows
        ],
    }


@router.get("/decision-fusions")
def list_decision_fusions(
    pagination: dict = Depends(pagination_params),
    prediction_type: str | None = Query(default=None),
    decision: str | None = Query(default=None),
    min_score: float | None = Query(default=None),
    db: Session = Depends(get_db),
):
    q = db.query(AIDecisionFusion)
    if prediction_type:
        q = q.filter(AIDecisionFusion.prediction_type == prediction_type)
    if decision:
        q = q.filter(AIDecisionFusion.decision == decision)
    if min_score is not None:
        q = q.filter(AIDecisionFusion.fused_score >= min_score)

    rows = (
        q.order_by(AIDecisionFusion.window_end.desc(), AIDecisionFusion.fused_score.desc())
        .offset(pagination["offset"])
        .limit(pagination["limit"])
        .all()
    )
    return {
        "limit": pagination["limit"],
        "offset": pagination["offset"],
        "items": [
            {
                "id": str(r.id),
                "entity_key": r.entity_key,
                "prediction_type": r.prediction_type,
                "window_key": r.window_key,
                "window_end": r.window_end.isoformat(),
                "fused_score": r.fused_score,
                "severity": r.severity,
                "decision": r.decision,
                "selected_model_version": r.selected_model_version,
                "signals": r.signals_json,
            }
            for r in rows
        ],
    }


@router.get("/drift-reports")
def list_drift_reports(
    pagination: dict = Depends(pagination_params),
    prediction_type: str | None = Query(default=None),
    model_version: str | None = Query(default=None),
    status: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    q = db.query(AIDriftReport)
    if prediction_type:
        q = q.filter(AIDriftReport.prediction_type == prediction_type)
    if model_version:
        q = q.filter(AIDriftReport.model_version == model_version)
    if status:
        q = q.filter(AIDriftReport.status == status)

    rows = (
        q.order_by(AIDriftReport.window_end.desc(), AIDriftReport.created_at.desc())
        .offset(pagination["offset"])
        .limit(pagination["limit"])
        .all()
    )
    return {
        "limit": pagination["limit"],
        "offset": pagination["offset"],
        "items": [
            {
                "id": str(r.id),
                "prediction_type": r.prediction_type,
                "model_version": r.model_version,
                "window_key": r.window_key,
                "window_end": r.window_end.isoformat(),
                "drift_score": r.drift_score,
                "status": r.status,
                "metrics": r.metrics_json,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ],
    }


@router.get("/input-anomalies")
def list_input_anomalies(
    pagination: dict = Depends(pagination_params),
    entity_key: str | None = Query(default=None),
    anomaly_type: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    q = db.query(AIInputAnomalyAlert)
    if entity_key:
        q = q.filter(AIInputAnomalyAlert.entity_key == entity_key)
    if anomaly_type:
        q = q.filter(AIInputAnomalyAlert.anomaly_type == anomaly_type)
    rows = (
        q.order_by(AIInputAnomalyAlert.window_end.desc(), AIInputAnomalyAlert.score.desc())
        .offset(pagination["offset"])
        .limit(pagination["limit"])
        .all()
    )
    return {
        "limit": pagination["limit"],
        "offset": pagination["offset"],
        "items": [
            {
                "id": str(r.id),
                "entity_key": r.entity_key,
                "window_key": r.window_key,
                "window_end": r.window_end.isoformat(),
                "anomaly_type": r.anomaly_type,
                "score": r.score,
                "details": r.details_json,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ],
    }


@router.get("/baselines")
def list_baselines(
    pagination: dict = Depends(pagination_params),
    window_key: str | None = Query(default=None),
    entity_key: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    q = db.query(EntityRiskBaseline)
    if window_key:
        q = q.filter(EntityRiskBaseline.window_key == window_key)
    if entity_key:
        q = q.filter(EntityRiskBaseline.entity_key == entity_key)
    rows = (
        q.order_by(EntityRiskBaseline.updated_at.desc())
        .offset(pagination["offset"])
        .limit(pagination["limit"])
        .all()
    )
    return {
        "limit": pagination["limit"],
        "offset": pagination["offset"],
        "items": [
            {
                "id": str(r.id),
                "entity_key": r.entity_key,
                "entity_type": r.entity_type,
                "window_key": r.window_key,
                "baseline_score": r.baseline_score,
                "baseline_std": r.baseline_std,
                "sample_count": r.sample_count,
                "last_window_end": r.last_window_end.isoformat() if r.last_window_end else None,
                "updated_at": r.updated_at.isoformat(),
            }
            for r in rows
        ],
    }


@router.post("/feedback")
def create_feedback(
    prediction_id: str,
    feedback_label: int = Query(..., ge=0, le=2),
    analyst_id: str = Query(...),
    notes: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    pred = db.query(AIPrediction).filter(AIPrediction.id == prediction_id).first()
    if not pred:
        raise HTTPException(status_code=404, detail="prediction_not_found")

    row = AIFeedbackLabel(
        id=uuid.uuid4(),
        prediction_id=pred.id,
        entity_key=pred.entity_key,
        feedback_label=int(feedback_label),
        analyst_id=analyst_id,
        notes=notes,
        status="queued",
        used_in_training=False,
    )
    db.add(row)
    db.commit()
    return {
        "id": str(row.id),
        "prediction_id": prediction_id,
        "entity_key": row.entity_key,
        "feedback_label": row.feedback_label,
        "analyst_id": row.analyst_id,
        "status": row.status,
        "created_at": row.created_at.isoformat(),
    }


@router.get("/feedback")
def list_feedback(
    pagination: dict = Depends(pagination_params),
    status: str | None = Query(default=None),
    analyst_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    q = db.query(AIFeedbackLabel)
    if status:
        q = q.filter(AIFeedbackLabel.status == status)
    if analyst_id:
        q = q.filter(AIFeedbackLabel.analyst_id == analyst_id)
    rows = (
        q.order_by(AIFeedbackLabel.created_at.desc())
        .offset(pagination["offset"])
        .limit(pagination["limit"])
        .all()
    )
    return {
        "limit": pagination["limit"],
        "offset": pagination["offset"],
        "items": [
            {
                "id": str(r.id),
                "prediction_id": str(r.prediction_id),
                "entity_key": r.entity_key,
                "feedback_label": r.feedback_label,
                "analyst_id": r.analyst_id,
                "notes": r.notes,
                "status": r.status,
                "used_in_training": r.used_in_training,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ],
    }


@router.get("/rollouts")
def list_rollouts(
    pagination: dict = Depends(pagination_params),
    prediction_type: str | None = Query(default=None),
    status: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    q = db.query(AIModelRollout)
    if prediction_type:
        q = q.filter(AIModelRollout.prediction_type == prediction_type)
    if status:
        q = q.filter(AIModelRollout.status == status)
    rows = (
        q.order_by(AIModelRollout.updated_at.desc())
        .offset(pagination["offset"])
        .limit(pagination["limit"])
        .all()
    )
    return {
        "limit": pagination["limit"],
        "offset": pagination["offset"],
        "items": [
            {
                "rollout_id": r.rollout_id,
                "prediction_type": r.prediction_type,
                "active_model_version": r.active_model_version,
                "shadow_model_version": r.shadow_model_version,
                "rollout_mode": r.rollout_mode,
                "canary_ratio": r.canary_ratio,
                "auto_rollback": r.auto_rollback,
                "min_sample_count": r.min_sample_count,
                "status": r.status,
                "created_by": r.created_by,
                "metadata": r.metadata_json,
                "created_at": r.created_at.isoformat(),
                "updated_at": r.updated_at.isoformat(),
            }
            for r in rows
        ],
    }


@router.post("/rollouts")
def upsert_rollout(
    prediction_type: str,
    active_model_version: str,
    shadow_model_version: str | None = None,
    rollout_mode: str = Query(default="single"),
    canary_ratio: float = Query(default=0.0, ge=0.0, le=1.0),
    auto_rollback: bool = Query(default=True),
    min_sample_count: int = Query(default=500, ge=1),
    created_by: str = Query(default="api"),
    db: Session = Depends(get_db),
):
    row = (
        db.query(AIModelRollout)
        .filter(AIModelRollout.prediction_type == prediction_type)
        .filter(AIModelRollout.status == "active")
        .first()
    )
    now = datetime.utcnow()
    if row:
        row.active_model_version = active_model_version
        row.shadow_model_version = shadow_model_version
        row.rollout_mode = rollout_mode
        row.canary_ratio = canary_ratio
        row.auto_rollback = auto_rollback
        row.min_sample_count = min_sample_count
        row.updated_at = now
    else:
        row = AIModelRollout(
            rollout_id=str(uuid.uuid4()),
            prediction_type=prediction_type,
            active_model_version=active_model_version,
            shadow_model_version=shadow_model_version,
            rollout_mode=rollout_mode,
            canary_ratio=canary_ratio,
            auto_rollback=auto_rollback,
            min_sample_count=min_sample_count,
            status="active",
            created_by=created_by,
            metadata_json={},
            created_at=now,
            updated_at=now,
        )
        db.add(row)
    db.commit()
    return {
        "rollout_id": row.rollout_id,
        "prediction_type": row.prediction_type,
        "active_model_version": row.active_model_version,
        "shadow_model_version": row.shadow_model_version,
        "rollout_mode": row.rollout_mode,
        "canary_ratio": row.canary_ratio,
        "auto_rollback": row.auto_rollback,
        "status": row.status,
    }


@router.get("/threat-intel")
def list_threat_intel(
    pagination: dict = Depends(pagination_params),
    indicator_type: str | None = Query(default=None),
    source: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    q = db.query(ThreatIntelIndicator)
    if indicator_type:
        q = q.filter(ThreatIntelIndicator.indicator_type == indicator_type)
    if source:
        q = q.filter(ThreatIntelIndicator.source == source)

    rows = (
        q.order_by(ThreatIntelIndicator.updated_at.desc())
        .offset(pagination["offset"])
        .limit(pagination["limit"])
        .all()
    )

    return {
        "limit": pagination["limit"],
        "offset": pagination["offset"],
        "items": [
            {
                "indicator_id": r.indicator_id,
                "stix_id": r.stix_id,
                "indicator_type": r.indicator_type,
                "value": r.value,
                "confidence": r.confidence,
                "source": r.source,
                "valid_from": r.valid_from.isoformat() if r.valid_from else None,
                "valid_until": r.valid_until.isoformat() if r.valid_until else None,
                "tags": r.tags_json,
                "metadata": r.metadata_json,
                "created_at": r.created_at.isoformat(),
                "updated_at": r.updated_at.isoformat(),
            }
            for r in rows
        ],
    }


@router.post("/threat-intel/import-stix")
def import_threat_intel(bundle: dict, source: str = Query(default="stix"), db: Session = Depends(get_db)):
    try:
        return import_stix_bundle(db=db, bundle=bundle, source=source)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"threat_intel_import_failed:{e}")


@router.post("/threat-intel/export-stix")
def export_threat_intel(source: str = Query(default="sentinel"), limit: int = Query(default=200, ge=1, le=5000), db: Session = Depends(get_db)):
    try:
        return export_stix_bundle(db=db, source=source, limit=limit)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"threat_intel_export_failed:{e}")

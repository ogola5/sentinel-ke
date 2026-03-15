from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
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
from app.analytics.layer3.forecasting import build_risk_forecast, summarize_forecast_card
from app.analytics.layer3.local_analyst_query import answer_local_analyst_query
from app.analytics.layer3.threat_intel_worker import export_stix_bundle, import_stix_bundle
from app.analytics.layer3.trust_service import build_entity_trust_summary, build_platform_trust_summary

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


def _top_feature(details: dict) -> str | None:
    attributions = details.get("feature_attributions", [])
    if not isinstance(attributions, list) or not attributions:
        return None
    first = attributions[0] if isinstance(attributions[0], dict) else {}
    name = str(first.get("feature") or "").strip()
    return name or None


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
                "explanation_method": (r.details_json or {}).get("explanation_method"),
                "top_feature": _top_feature(dict(r.details_json or {})),
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
        "explanation_method": (r.details_json or {}).get("explanation_method"),
        "top_feature": _top_feature(dict(r.details_json or {})),
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
    details = dict(expl.details_json or {})
    method = str(details.get("explanation_method") or "unknown")
    top_feature = _top_feature(details)
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
        "explanation_method": method,
        "model_based": method == "gradient_x_input",
        "top_feature": top_feature,
        "feature_attributions": details.get("feature_attributions", []),
        "attribution_group_scores": details.get("attribution_group_scores", []),
        "details": details,
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
                "fairness_gate": (r.metrics_json or {}).get("fairness_gate", {}),
                "fairness_blocked": (
                    ((r.metrics_json or {}).get("fairness", {}).get(
                        "max_positive_rate_disparity", 0
                    ) > settings.fairness_disparity_threshold)
                    and not bool(((r.metrics_json or {}).get("fairness_gate") or {}).get("override_applied", False))
                ),
                "provenance": (r.metrics_json or {}).get("provenance", {}),
                "real_data_gate": (r.metrics_json or {}).get("real_data_gate", {}),
                "real_data_gate_passed": bool(
                    ((r.metrics_json or {}).get("real_data_gate") or {}).get("passed", False)
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
    wait_for_completion: bool = True
    allow_demo_real_data_override: bool = False
    allow_demo_fairness_override: bool = False


class DriftRunRequest(BaseModel):
    prediction_type: Literal["risk_gnn", "corruption_risk"] = "risk_gnn"
    window_key: str | None = None
    model_version: str | None = None


def _run_cyber_train(
    epochs: int,
    model_version: str,
    *,
    allow_demo_real_data_override: bool = False,
    allow_demo_fairness_override: bool = False,
) -> dict[str, Any]:
    from app.analytics.layer3.gnn_train_worker import run_once
    from app.ledger.db import SessionLocal
    db = SessionLocal()
    try:
        result = run_once(
            db=db,
            window_key="Wmid",
            epochs=epochs,
            model_version=model_version,
            allow_demo_real_data_override=allow_demo_real_data_override,
            allow_demo_fairness_override=allow_demo_fairness_override,
        )
        log.info("gnn_train_cyber_done: %s", result)
        return result
    except Exception as exc:
        log.exception("gnn_train_cyber_failed: %s", exc)
        return {"status": "error", "stage": "api_train", "detail": str(exc)}
    finally:
        db.close()


def _run_corruption_train(
    epochs: int,
    model_version: str,
    *,
    allow_demo_real_data_override: bool = False,
    allow_demo_fairness_override: bool = False,
) -> dict[str, Any]:
    from app.analytics.corruption.train_worker import run_once
    from app.ledger.db import SessionLocal
    db = SessionLocal()
    try:
        result = run_once(
            db=db,
            window_key="Wcorruption",
            epochs=epochs,
            model_version=model_version,
            allow_demo_real_data_override=allow_demo_real_data_override,
            allow_demo_fairness_override=allow_demo_fairness_override,
        )
        log.info("gnn_train_corruption_done: %s", result)
        return result
    except Exception as exc:
        log.exception("gnn_train_corruption_failed: %s", exc)
        return {"status": "error", "stage": "api_train", "detail": str(exc)}
    finally:
        db.close()


@router.post("/gnn/train")
@limiter.limit("5/minute")
def trigger_gnn_train(
    request: Request,
    body: GNNTrainRequest,
    background_tasks: BackgroundTasks,
    _principal=Depends(require_central_access),
):
    """
    Trigger a GNN retraining run.

    domain = "cyber"       → cyber threat GNN (window_key Wmid, feat_dim 44)
    domain = "corruption"  → corruption risk GNN (window_key Wcorruption, feat_dim 42)

    By default this waits for the selected training run to complete and returns
    the actual outcome. Set wait_for_completion=false for fire-and-forget mode.
    """
    default_versions = {"cyber": "gnn-sage-v1", "corruption": "corruption-gnn-v1"}
    mv = body.model_version or default_versions[body.domain]

    if body.wait_for_completion:
        if body.domain == "cyber":
            result = _run_cyber_train(
                body.epochs,
                mv,
                allow_demo_real_data_override=body.allow_demo_real_data_override,
                allow_demo_fairness_override=body.allow_demo_fairness_override,
            )
        else:
            result = _run_corruption_train(
                body.epochs,
                mv,
                allow_demo_real_data_override=body.allow_demo_real_data_override,
                allow_demo_fairness_override=body.allow_demo_fairness_override,
            )

        payload = {
            "accepted": result.get("status") in {"ok", "blocked"},
            "domain": body.domain,
            "model_version": mv,
            "epochs": body.epochs,
            "wait_for_completion": True,
            "demo_real_data_override_requested": bool(body.allow_demo_real_data_override),
            "demo_fairness_override_requested": bool(body.allow_demo_fairness_override),
            **result,
        }
        status_code = 200
        if result.get("status") == "blocked":
            status_code = 409
        elif result.get("status") == "error":
            status_code = 500
        return JSONResponse(status_code=status_code, content=payload)

    if body.domain == "cyber":
        background_tasks.add_task(
            _run_cyber_train,
            body.epochs,
            mv,
            allow_demo_real_data_override=body.allow_demo_real_data_override,
            allow_demo_fairness_override=body.allow_demo_fairness_override,
        )
    else:
        background_tasks.add_task(
            _run_corruption_train,
            body.epochs,
            mv,
            allow_demo_real_data_override=body.allow_demo_real_data_override,
            allow_demo_fairness_override=body.allow_demo_fairness_override,
        )

    return JSONResponse(
        status_code=202,
        content={
            "accepted": True,
            "domain": body.domain,
            "model_version": mv,
            "epochs": body.epochs,
            "wait_for_completion": False,
            "demo_real_data_override_requested": bool(body.allow_demo_real_data_override),
            "demo_fairness_override_requested": bool(body.allow_demo_fairness_override),
            "message": "Training started in background. Poll GET /v1/ai/gnn/runs for results.",
        },
    )


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
        "fairness": (r.metrics_json or {}).get("fairness", {}),
        "fairness_gate": (r.metrics_json or {}).get("fairness_gate", {}),
        "fairness_blocked": (
            ((r.metrics_json or {}).get("fairness", {}).get(
                "max_positive_rate_disparity", 0
            ) > settings.fairness_disparity_threshold)
            and not bool(((r.metrics_json or {}).get("fairness_gate") or {}).get("override_applied", False))
        ),
        "provenance": (r.metrics_json or {}).get("provenance", {}),
        "real_data_gate": (r.metrics_json or {}).get("real_data_gate", {}),
        "real_data_gate_passed": bool(
            ((r.metrics_json or {}).get("real_data_gate") or {}).get("passed", False)
        ),
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


@router.post("/drift-reports/run")
def run_drift_report(
    body: DriftRunRequest,
    _principal=Depends(require_central_access),
    db: Session = Depends(get_db),
):
    latest_run = (
        db.query(GNNTrainingRun)
        .filter(GNNTrainingRun.prediction_type == body.prediction_type)
        .order_by(GNNTrainingRun.window_end.desc(), GNNTrainingRun.created_at.desc())
        .first()
    )
    model_version = body.model_version or (latest_run.model_version if latest_run else None)
    if not model_version:
        raise HTTPException(status_code=404, detail="gnn_run_not_found")

    window_key = body.window_key or (latest_run.window_key if latest_run else None)
    if not window_key:
        window_key = "Wmid" if body.prediction_type == "risk_gnn" else "Wcorruption"

    try:
        from app.analytics.layer3.drift_worker import run_once as run_drift  # noqa: PLC0415

        return run_drift(
            db=db,
            prediction_type=body.prediction_type,
            window_key=window_key,
            model_version=model_version,
        )
    except Exception:
        log.exception("ai_run_drift_report_failed")
        raise HTTPException(status_code=500, detail="internal_error")


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


# ── /v1/ai/tool-attribution ───────────────────────────────────────────────────
@router.get("/tool-attribution")
def tool_attribution(
    entity_key: str = Query(..., description="Entity key to look up"),
    db: Session = Depends(get_db),
):
    """
    Enriches entity's ATT&CK technique hits with known attacker tools/malware
    from the curated MITRE ATT&CK Software catalog.
    """
    from app.analytics.ai_models import AIAttackTechniqueHit
    from app.analytics.layer3.ai_intel import techniques_to_tools

    rows = (
        db.query(AIAttackTechniqueHit)
        .filter(AIAttackTechniqueHit.entity_key == entity_key)
        .order_by(AIAttackTechniqueHit.confidence.desc())
        .limit(50)
        .all()
    )
    if not rows:
        return {
            "entity_key": entity_key,
            "techniques": [],
            "tools": [],
            "summary": {"technique_count": 0, "tool_count": 0, "top_tactic": None},
        }
    techniques = [
        {
            "technique_id": r.technique_id,
            "tactic": r.tactic,
            "confidence": float(r.confidence or 0.0),
            "source_event_type": r.source_event_type,
        }
        for r in rows
    ]
    technique_ids = [r.technique_id for r in rows]
    tools = techniques_to_tools(technique_ids)
    tactic_counts: Dict[str, int] = {}
    for t in techniques:
        tac = str(t.get("tactic") or "unknown")
        tactic_counts[tac] = tactic_counts.get(tac, 0) + 1
    top_tactic = max(tactic_counts, key=lambda k: tactic_counts[k]) if tactic_counts else None
    return {
        "entity_key": entity_key,
        "techniques": techniques,
        "tools": tools,
        "summary": {
            "technique_count": len(techniques),
            "tool_count": len(tools),
            "top_tactic": top_tactic,
            "tactic_distribution": tactic_counts,
        },
    }


# ── /v1/ai/tools/summary ─────────────────────────────────────────────────────
@router.get("/tools/summary")
def tools_summary(
    min_score: float = Query(default=70.0, ge=0.0, le=100.0),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """
    Top attacker tools inferred from ATT&CK technique hits of all high-risk entities.
    """
    from app.analytics.ai_models import AIAttackTechniqueHit, AIPrediction
    from app.analytics.layer3.ai_intel import techniques_to_tools
    from collections import Counter

    high_risk = (
        db.query(AIPrediction.entity_key)
        .filter(AIPrediction.prediction_type == "risk_gnn")
        .filter(AIPrediction.score >= min_score)
        .order_by(AIPrediction.score.desc())
        .limit(limit)
        .all()
    )
    entity_keys = [str(r[0]) for r in high_risk]
    if not entity_keys:
        return {"tools": [], "techniques": [], "entity_count": 0}
    tech_rows = (
        db.query(AIAttackTechniqueHit)
        .filter(AIAttackTechniqueHit.entity_key.in_(entity_keys))
        .all()
    )
    all_technique_ids = [r.technique_id for r in tech_rows]
    tactic_counter: Counter = Counter(r.tactic for r in tech_rows)
    tool_counter: Counter = Counter()
    for r in tech_rows:
        for sw in techniques_to_tools([r.technique_id]):
            tool_counter[sw["name"]] += 1
    top_tools = [{"name": n, "entity_hits": c} for n, c in tool_counter.most_common(20)]
    tools = techniques_to_tools(all_technique_ids)
    return {
        "entity_count": len(entity_keys),
        "min_score_filter": min_score,
        "top_tools": top_tools,
        "tactic_distribution": dict(tactic_counter.most_common()),
        "unique_tools_inferred": len({sw["name"] for sw in tools}),
        "unique_techniques_observed": len(set(all_technique_ids)),
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


# ── /v1/ai/indicators/summary ─────────────────────────────────────────────────
# Unified threat-indicator summary for the S2 Timeline / Indicators screen.
# Sources: event_log (all event types) + ai_prediction (risk_gnn) +
#          ai_campaign_risk_indicator.  No OpenSearch dependency.
@router.get("/indicators/summary")
def threat_indicators_summary(
    days: int = Query(default=7, ge=1, le=30),
    db: Session = Depends(get_db),
):
    from sqlalchemy import text as _text
    from datetime import timezone

    # ── 1. Event volume by day + category ───────────────────────────────────
    vol_sql = _text("""
        SELECT
            date_trunc('day', occurred_at AT TIME ZONE 'UTC')::date AS day,
            CASE
                WHEN event_type IN (
                    'TRANSACTION_EVENT','AIRTIME_TRANSFER_EVENT',
                    'PAYMENT_DISBURSEMENT','SIM_SWAP_EVENT'
                ) THEN 'fraud'
                WHEN event_type = 'DDOS_SIGNAL_EVENT'         THEN 'ddos'
                WHEN event_type IN ('DFIR_FINDING_EVENT','DNS_RESOLUTION_EVENT',
                                    'NETWORK_ANOMALY_EVENT')  THEN 'network'
                WHEN event_type = 'VULNERABILITY_EVENT'        THEN 'vulnerability'
                WHEN event_type = 'PHISHING_MESSAGE_EVENT'     THEN 'phishing'
                WHEN event_type IN ('THREAT_INTEL_EVENT','INDICATOR_EVENT') THEN 'threat_intel'
                ELSE 'other'
            END AS category,
            COUNT(*) AS cnt
        FROM event_log
        WHERE occurred_at >= NOW() - INTERVAL '1 day' * :days
        GROUP BY 1, 2
        ORDER BY 1
    """)
    vol_rows = db.execute(vol_sql, {"days": days}).fetchall()

    # Pivot into day → {category: count}
    from collections import defaultdict
    day_vol: dict = defaultdict(lambda: {"fraud": 0, "ddos": 0, "network": 0,
                                          "vulnerability": 0, "phishing": 0,
                                          "threat_intel": 0, "other": 0, "total": 0})
    for row in vol_rows:
        d = str(row[0])
        cat = row[1]
        cnt = int(row[2])
        day_vol[d][cat] = cnt
        day_vol[d]["total"] += cnt

    event_volume_series = [
        {"date": d, **v} for d, v in sorted(day_vol.items())
    ]

    # ── 2. GNN risk trajectory by day ───────────────────────────────────────
    gnn_sql = _text("""
        SELECT
            date_trunc('day', window_end AT TIME ZONE 'UTC')::date AS day,
            COUNT(*)                                                AS prediction_count,
            AVG(score)                                              AS avg_score,
            MAX(score)                                              AS max_score,
            PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY score)     AS p90_score
        FROM ai_prediction
        WHERE prediction_type = 'risk_gnn'
          AND window_end >= NOW() - INTERVAL '1 day' * :days
        GROUP BY 1
        ORDER BY 1
    """)
    gnn_rows = db.execute(gnn_sql, {"days": days}).fetchall()
    gnn_risk_series = [
        {
            "date":             str(r[0]),
            "prediction_count": int(r[1]),
            "avg_score":        round(float(r[2]), 1),
            "max_score":        round(float(r[3]), 1),
            "p90_score":        round(float(r[4]), 1),
        }
        for r in gnn_rows
    ]

    # ── 3. Campaign risk severity breakdown ──────────────────────────────────
    sev_sql = _text("""
        SELECT severity, COUNT(*) AS cnt
        FROM ai_campaign_risk_indicator
        GROUP BY severity
    """)
    sev_rows = db.execute(sev_sql).fetchall()
    campaign_risk: dict = {"critical": 0, "high": 0, "medium": 0, "low": 0, "total": 0}
    for r in sev_rows:
        sev = str(r[0]).lower()
        cnt = int(r[1])
        if sev in campaign_risk:
            campaign_risk[sev] = cnt
        campaign_risk["total"] += cnt

    # ── 4. Top at-risk entities (latest GNN window) ──────────────────────────
    top_sql = _text("""
        SELECT DISTINCT ON (entity_key)
            entity_key,
            entity_type,
            score,
            kill_chain_stage,
            reason_codes,
            window_end
        FROM ai_prediction
        WHERE prediction_type = 'risk_gnn'
        ORDER BY entity_key, window_end DESC, score DESC
    """)
    top_all = db.execute(top_sql).fetchall()
    top_all_sorted = sorted(top_all, key=lambda r: float(r[2]), reverse=True)[:10]
    top_threats = [
        {
            "entity_key":       r[0],
            "entity_type":      r[1],
            "score":            round(float(r[2]), 1),
            "kill_chain_stage": r[3],
            "reason_codes":     r[4] if isinstance(r[4], list) else [],
            "severity":         _severity_from_score(float(r[2])),
        }
        for r in top_all_sorted
    ]

    # ── 5. Kill-chain stage distribution ────────────────────────────────────
    kc_sql = _text("""
        SELECT kill_chain_stage, COUNT(*) AS cnt
        FROM ai_prediction
        WHERE prediction_type = 'risk_gnn'
          AND kill_chain_stage IS NOT NULL
        GROUP BY kill_chain_stage
        ORDER BY cnt DESC
    """)
    kc_rows = db.execute(kc_sql).fetchall()
    kill_chain_distribution = {str(r[0]): int(r[1]) for r in kc_rows}

    # ── 6. Quick event-type totals (for summary cards) ───────────────────────
    totals_sql = _text("""
        SELECT
            SUM(CASE WHEN event_type IN ('TRANSACTION_EVENT','AIRTIME_TRANSFER_EVENT',
                'PAYMENT_DISBURSEMENT','SIM_SWAP_EVENT') THEN 1 ELSE 0 END) AS fraud,
            SUM(CASE WHEN event_type = 'DDOS_SIGNAL_EVENT' THEN 1 ELSE 0 END) AS ddos,
            SUM(CASE WHEN event_type IN ('DFIR_FINDING_EVENT','DNS_RESOLUTION_EVENT',
                'NETWORK_ANOMALY_EVENT') THEN 1 ELSE 0 END)                  AS network,
            SUM(CASE WHEN event_type = 'VULNERABILITY_EVENT' THEN 1 ELSE 0 END)     AS vulnerability,
            SUM(CASE WHEN event_type = 'PHISHING_MESSAGE_EVENT' THEN 1 ELSE 0 END)  AS phishing,
            COUNT(*)                                                                 AS total
        FROM event_log
    """)
    tot = db.execute(totals_sql).fetchone()
    event_totals = {
        "fraud":         int(tot[0] or 0),
        "ddos":          int(tot[1] or 0),
        "network":       int(tot[2] or 0),
        "vulnerability": int(tot[3] or 0),
        "phishing":      int(tot[4] or 0),
        "total":         int(tot[5] or 0),
    }

    # ── 7. Shared limited-data forecast based on daily GNN avg scores ───────
    forecast_detail = build_risk_forecast(history=gnn_risk_series, horizon=7, alpha=0.3, beta=0.1)
    forecast = summarize_forecast_card(forecast_detail, target_day=3)

    return {
        "generated_at":          datetime.now(timezone.utc).isoformat(),
        "window_days":           days,
        "event_volume_series":   event_volume_series,
        "gnn_risk_series":       gnn_risk_series,
        "campaign_risk":         campaign_risk,
        "top_threats":           top_threats,
        "kill_chain_distribution": kill_chain_distribution,
        "event_totals":          event_totals,
        "forecast":              forecast,
        "forecast_detail":       forecast_detail,
    }


# ── /v1/ai/forecast ───────────────────────────────────────────────────────────
@router.get("/forecast")
def ai_risk_forecast(
    days: int = Query(default=14, ge=3, le=60, description="History window in days"),
    horizon: int = Query(default=7, ge=1, le=30, description="Forecast horizon in days"),
    alpha: float = Query(default=0.3, ge=0.05, le=0.95, description="Level smoothing factor"),
    beta: float = Query(default=0.1, ge=0.01, le=0.5, description="Trend smoothing factor"),
    db: Session = Depends(get_db),
):
    from sqlalchemy import text as _text

    hist_sql = _text("""
        SELECT
            date_trunc('day', window_end AT TIME ZONE 'UTC')::date AS day,
            AVG(score)   AS avg_score,
            MAX(score)   AS max_score,
            COUNT(*)     AS n
        FROM ai_prediction
        WHERE prediction_type = 'risk_gnn'
          AND window_end >= NOW() - INTERVAL '1 day' * :days
        GROUP BY 1
        ORDER BY 1
    """)
    rows = db.execute(hist_sql, {"days": days}).fetchall()
    history = [
        {
            "date": str(r[0]),
            "avg_score": round(float(r[1] or 0.0), 2),
            "max_score": round(float(r[2] or 0.0), 2),
            "n": int(r[3] or 0),
        }
        for r in rows
    ]
    return build_risk_forecast(
        history=history,
        horizon=horizon,
        alpha=alpha,
        beta=beta,
    )


@router.get("/trust/entity")
def entity_trust_summary(
    entity_key: str = Query(..., description="Entity key to inspect"),
    prediction_type: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    try:
        return build_entity_trust_summary(
            db=db,
            entity_key=entity_key,
            prediction_type=prediction_type,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/trust/summary")
def platform_trust_summary(db: Session = Depends(get_db)):
    return build_platform_trust_summary(db=db)


# ---------------------------------------------------------------------------
# NL Analyst Copilot
# POST /v1/ai/query
# ---------------------------------------------------------------------------

class CopilotQueryRequest(BaseModel):
    question: str
    context: dict[str, Any] | None = None


@router.post("/query", summary="NL analyst copilot — ask Sentinel Copilot a question")
def nl_copilot_query(payload: CopilotQueryRequest, db: Session = Depends(get_db)):
    """
    Local natural-language analyst copilot.
    """
    if not settings.ai_copilot_enabled:
        raise HTTPException(status_code=503, detail="ai_copilot_disabled")
    try:
        result = answer_local_analyst_query(
            db=db,
            question=payload.question.strip(),
            context=payload.context,
        )
    except Exception as exc:
        log.exception("copilot_error: %s", exc)
        raise HTTPException(status_code=500, detail=f"local_copilot_error: {exc}")

    return {
        "answer": result["answer"],
        "model": result["model"],
        "intent": result.get("intent"),
        "sources": result.get("sources", []),
        "question": payload.question,
        "context_provided": payload.context is not None,
    }

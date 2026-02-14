from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db, pagination_params
from app.analytics.ai_models import AIPrediction, AIExplanation, GNNTrainingRun

router = APIRouter(prefix="/v1/ai", tags=["ai"])


@router.get("/predictions")
def list_predictions(
    pagination: dict = Depends(pagination_params),
    prediction_type: str | None = Query(default=None),
    window_key: str | None = Query(default=None),
    entity_key: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    q = db.query(AIPrediction)
    if prediction_type:
        q = q.filter(AIPrediction.prediction_type == prediction_type)
    if window_key:
        q = q.filter(AIPrediction.window_key == window_key)
    if entity_key:
        q = q.filter(AIPrediction.entity_key == entity_key)

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
                "window_key": r.window_key,
                "window_end": r.window_end.isoformat(),
                "score": r.score,
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
        "window_key": r.window_key,
        "window_end": r.window_end.isoformat(),
        "score": r.score,
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
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ],
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

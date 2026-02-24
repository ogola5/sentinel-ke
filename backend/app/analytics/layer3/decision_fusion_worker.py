from __future__ import annotations

import json
from datetime import datetime
from typing import Dict, Optional

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.analytics.ai_models import AIAttackPathScore, AIDecisionFusion, AIPrediction
from app.analytics.anomalies import AnomalyScore
from app.ledger.db import SessionLocal


def _severity(score: float) -> str:
    s = float(score)
    if s >= 90.0:
        return "critical"
    if s >= 75.0:
        return "high"
    if s >= 55.0:
        return "medium"
    return "low"


def _latest_window_end(db: Session, prediction_type: str, window_key: str) -> Optional[datetime]:
    return (
        db.query(func.max(AIPrediction.window_end))
        .filter(AIPrediction.prediction_type == prediction_type)
        .filter(AIPrediction.window_key == window_key)
        .scalar()
    )


def run_once(
    *,
    db: Session,
    prediction_type: str = "risk_gnn",
    window_key: str = "Wmid",
    window_end: Optional[datetime] = None,
    max_entities: int = 5000,
) -> int:
    if window_end is None:
        window_end = _latest_window_end(db, prediction_type, window_key)
    if window_end is None:
        return 0

    preds = (
        db.query(AIPrediction)
        .filter(AIPrediction.prediction_type == prediction_type)
        .filter(AIPrediction.window_key == window_key)
        .filter(AIPrediction.window_end == window_end)
        .order_by(AIPrediction.score.desc())
        .limit(max_entities)
        .all()
    )
    if not preds:
        return 0

    path_rows = (
        db.query(AIAttackPathScore)
        .filter(AIAttackPathScore.prediction_type == prediction_type)
        .filter(AIAttackPathScore.window_key == window_key)
        .filter(AIAttackPathScore.window_end == window_end)
        .all()
    )
    path_by_entity: Dict[str, float] = {str(r.entity_key): float(r.path_score or 0.0) for r in path_rows}

    anomaly_rows = (
        db.query(AnomalyScore)
        .filter(AnomalyScore.window_end == window_end)
        .all()
    )
    anomaly_by_entity: Dict[str, float] = {}
    for a in anomaly_rows:
        if a.service_id:
            anomaly_by_entity[f"service_id:{a.service_id}"] = max(
                anomaly_by_entity.get(f"service_id:{a.service_id}", 0.0),
                float(a.score or 0.0) * 100.0,
            )
        if a.endpoint:
            anomaly_by_entity[f"endpoint:{a.endpoint}"] = max(
                anomaly_by_entity.get(f"endpoint:{a.endpoint}", 0.0),
                float(a.score or 0.0) * 100.0,
            )

    rows = []
    for p in preds:
        gnn_score = float(p.score or 0.0)
        path_score = float(path_by_entity.get(str(p.entity_key), gnn_score))
        anomaly_score = float(anomaly_by_entity.get(str(p.entity_key), 0.0))
        fused = min(100.0, 0.6 * gnn_score + 0.25 * path_score + 0.15 * anomaly_score)
        severity = _severity(fused)
        decision = "monitor"
        if fused >= 80:
            decision = "escalate"
        elif fused >= 55:
            decision = "review"

        rows.append(
            {
                "entity_key": str(p.entity_key),
                "prediction_type": prediction_type,
                "window_key": window_key,
                "window_end": window_end,
                "fused_score": round(fused, 6),
                "severity": severity,
                "decision": decision,
                "selected_model_version": str(p.model_version or "unknown"),
                "signals_json": {
                    "gnn_score": round(gnn_score, 6),
                    "path_score": round(path_score, 6),
                    "anomaly_score": round(anomaly_score, 6),
                },
            }
        )

    stmt = insert(AIDecisionFusion).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["entity_key", "prediction_type", "window_key", "window_end"],
        set_={
            "fused_score": stmt.excluded.fused_score,
            "severity": stmt.excluded.severity,
            "decision": stmt.excluded.decision,
            "selected_model_version": stmt.excluded.selected_model_version,
            "signals_json": stmt.excluded.signals_json,
            "created_at": stmt.excluded.created_at,
        },
    )
    res = db.execute(stmt)
    db.commit()
    return int(res.rowcount or 0)


def main() -> None:
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--prediction-type", default="risk_gnn")
    p.add_argument("--window-key", default="Wmid")
    p.add_argument("--window-end", default=None)
    args = p.parse_args()

    window_end = None
    if args.window_end:
        window_end = datetime.fromisoformat(args.window_end.replace("Z", "+00:00"))

    db = SessionLocal()
    try:
        n = run_once(
            db=db,
            prediction_type=args.prediction_type,
            window_key=args.window_key,
            window_end=window_end,
        )
        print(json.dumps({"decision_fusions_upserted": n}))
    finally:
        db.close()


if __name__ == "__main__":
    main()

from __future__ import annotations

import json
from typing import Dict

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.analytics.ai_models import AIInputAnomalyAlert, AIPrediction, EntityRiskBaseline
from app.ledger.db import SessionLocal


def run_once(
    *,
    db: Session,
    prediction_type: str = "risk_gnn",
    window_key: str = "Wmid",
    z_threshold: float = 3.0,
) -> int:
    latest_window = (
        db.query(func.max(AIPrediction.window_end))
        .filter(AIPrediction.prediction_type == prediction_type)
        .filter(AIPrediction.window_key == window_key)
        .scalar()
    )
    if latest_window is None:
        return 0

    preds = (
        db.query(AIPrediction)
        .filter(AIPrediction.prediction_type == prediction_type)
        .filter(AIPrediction.window_key == window_key)
        .filter(AIPrediction.window_end == latest_window)
        .all()
    )
    if not preds:
        return 0

    baselines = (
        db.query(EntityRiskBaseline)
        .filter(EntityRiskBaseline.window_key == window_key)
        .all()
    )
    by_entity: Dict[str, EntityRiskBaseline] = {str(b.entity_key): b for b in baselines}

    rows = []
    for p in preds:
        b = by_entity.get(str(p.entity_key))
        if not b:
            continue
        std = max(1.0, float(b.baseline_std or 0.0))
        z = abs(float(p.score or 0.0) - float(b.baseline_score or 0.0)) / std
        if z < float(z_threshold):
            continue
        rows.append(
            {
                "entity_key": str(p.entity_key),
                "window_key": window_key,
                "window_end": latest_window,
                "anomaly_type": "prediction_outlier",
                "score": round(float(z), 6),
                "details_json": {
                    "current_score": float(p.score or 0.0),
                    "baseline_score": float(b.baseline_score or 0.0),
                    "baseline_std": float(b.baseline_std or 0.0),
                    "z_threshold": float(z_threshold),
                },
            }
        )

    if not rows:
        return 0

    stmt = insert(AIInputAnomalyAlert).values(rows)
    res = db.execute(stmt)
    db.commit()
    return int(res.rowcount or 0)


def main() -> None:
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--prediction-type", default="risk_gnn")
    p.add_argument("--window-key", default="Wmid")
    p.add_argument("--z-threshold", type=float, default=3.0)
    args = p.parse_args()

    db = SessionLocal()
    try:
        n = run_once(
            db=db,
            prediction_type=args.prediction_type,
            window_key=args.window_key,
            z_threshold=args.z_threshold,
        )
        print(json.dumps({"input_anomaly_alerts_created": n}))
    finally:
        db.close()


if __name__ == "__main__":
    main()

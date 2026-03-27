"""
Input anomaly worker — detects entities whose risk scores deviate abnormally.

Two detection methods (both self-contained — no pre-populated baseline table required):

1. Entity-level historical deviation (per-entity Z-score):
   Compare an entity's current score against its own rolling history
   across the past N windows. Flags entities that deviate from their
   own baseline (e.g., an IP that was always low-risk suddenly spikes).

2. Population-level IQR outlier (cross-entity in current window):
   Flag entities whose current score is a statistical outlier relative
   to the full population of scores in this window. Catches mass
   anomalies (e.g., a new botnet campaign flooding scores above normal).

Both methods write AIInputAnomalyAlert rows with anomaly_type set to
"entity_history_deviation" or "population_iqr_outlier" respectively.
"""
from __future__ import annotations

import logging
import math
from typing import Dict, List, Optional, Tuple

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.analytics.ai_models import AIInputAnomalyAlert, AIPrediction
from app.ledger.db import SessionLocal

log = logging.getLogger("sentinel.layer3.input_anomaly_worker")


# ---------------------------------------------------------------------------
# Statistics helpers
# ---------------------------------------------------------------------------

def _mean_std(values: List[float]) -> Tuple[float, float]:
    if not values:
        return 0.0, 1.0
    n = len(values)
    mean = sum(values) / n
    variance = sum((v - mean) ** 2 for v in values) / n
    std = math.sqrt(variance) if variance > 0 else 1.0
    return mean, std


def _iqr_bounds(values: List[float], multiplier: float = 1.5) -> Tuple[float, float]:
    if len(values) < 4:
        return 0.0, 1.0
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    q1 = sorted_vals[n // 4]
    q3 = sorted_vals[(3 * n) // 4]
    iqr = q3 - q1
    return q1 - multiplier * iqr, q3 + multiplier * iqr


# ---------------------------------------------------------------------------
# Detection methods
# ---------------------------------------------------------------------------

def _entity_history_anomalies(
    db: Session,
    *,
    prediction_type: str,
    window_key: str,
    current_window_end,
    z_threshold: float,
    history_windows: int,
) -> List[dict]:
    """
    Per-entity Z-score: compare current score against entity's own history.
    """
    # Current window predictions
    current_preds = (
        db.query(AIPrediction.entity_key, AIPrediction.score)
        .filter(AIPrediction.prediction_type == prediction_type)
        .filter(AIPrediction.window_key == window_key)
        .filter(AIPrediction.window_end == current_window_end)
        .all()
    )
    if not current_preds:
        return []

    entity_keys = [str(r[0]) for r in current_preds]
    current_by_key: Dict[str, float] = {str(r[0]): float(r[1]) for r in current_preds}

    # Historical predictions for the same entities (last N windows before current)
    historical = (
        db.query(AIPrediction.entity_key, AIPrediction.score, AIPrediction.window_end)
        .filter(AIPrediction.prediction_type == prediction_type)
        .filter(AIPrediction.window_key == window_key)
        .filter(AIPrediction.window_end < current_window_end)
        .filter(AIPrediction.entity_key.in_(entity_keys))
        .order_by(AIPrediction.window_end.desc())
        .limit(len(entity_keys) * history_windows)
        .all()
    )

    # Build {entity_key: [historical_scores]}
    history_by_key: Dict[str, List[float]] = {}
    for ek, score, _ in historical:
        history_by_key.setdefault(str(ek), []).append(float(score))

    rows = []
    for ek, current_score in current_by_key.items():
        hist = history_by_key.get(ek, [])
        if len(hist) < 2:
            continue  # need at least 2 points for meaningful std
        mean, std = _mean_std(hist)
        z = abs(current_score - mean) / std
        if z < z_threshold:
            continue
        rows.append({
            "entity_key": ek,
            "window_key": window_key,
            "window_end": current_window_end,
            "anomaly_type": "entity_history_deviation",
            "score": round(z, 6),
            "details_json": {
                "current_score": current_score,
                "historical_mean": round(mean, 6),
                "historical_std": round(std, 6),
                "history_sample_count": len(hist),
                "z_score": round(z, 6),
                "z_threshold": z_threshold,
            },
        })
    return rows


def _population_iqr_anomalies(
    db: Session,
    *,
    prediction_type: str,
    window_key: str,
    current_window_end,
    iqr_multiplier: float,
) -> List[dict]:
    """
    IQR-based cross-entity outlier detection within the current window.
    """
    preds = (
        db.query(AIPrediction.entity_key, AIPrediction.score)
        .filter(AIPrediction.prediction_type == prediction_type)
        .filter(AIPrediction.window_key == window_key)
        .filter(AIPrediction.window_end == current_window_end)
        .all()
    )
    if len(preds) < 4:
        return []

    all_scores = [float(r[1]) for r in preds]
    lower, upper = _iqr_bounds(all_scores, multiplier=iqr_multiplier)

    rows = []
    for ek, score in preds:
        score = float(score)
        if lower <= score <= upper:
            continue
        # Only flag upward outliers (suspicious spikes, not just low scores)
        if score <= upper:
            continue
        rows.append({
            "entity_key": str(ek),
            "window_key": window_key,
            "window_end": current_window_end,
            "anomaly_type": "population_iqr_outlier",
            "score": round(score, 6),
            "details_json": {
                "current_score": score,
                "iqr_upper_bound": round(upper, 6),
                "iqr_lower_bound": round(lower, 6),
                "population_size": len(all_scores),
                "iqr_multiplier": iqr_multiplier,
            },
        })
    return rows


# ---------------------------------------------------------------------------
# run_once
# ---------------------------------------------------------------------------

def run_once(
    *,
    db: Session,
    prediction_type: str = "risk_gnn",
    window_key: str = "Wmid",
    z_threshold: float = 3.0,
    history_windows: int = 5,
    iqr_multiplier: float = 1.5,
) -> dict:
    """
    Parameters
    ----------
    z_threshold     : Per-entity Z-score threshold for history deviation alerts.
    history_windows : How many past windows to use for per-entity baseline.
    iqr_multiplier  : IQR fence multiplier for population outlier detection (1.5 = standard Tukey).
    """
    current_window_end = (
        db.query(func.max(AIPrediction.window_end))
        .filter(AIPrediction.prediction_type == prediction_type)
        .filter(AIPrediction.window_key == window_key)
        .scalar()
    )
    if current_window_end is None:
        return {"input_anomaly_alerts_created": 0, "status": "no_predictions"}

    history_rows = _entity_history_anomalies(
        db,
        prediction_type=prediction_type,
        window_key=window_key,
        current_window_end=current_window_end,
        z_threshold=z_threshold,
        history_windows=history_windows,
    )
    iqr_rows = _population_iqr_anomalies(
        db,
        prediction_type=prediction_type,
        window_key=window_key,
        current_window_end=current_window_end,
        iqr_multiplier=iqr_multiplier,
    )

    all_rows = history_rows + iqr_rows
    if not all_rows:
        return {
            "input_anomaly_alerts_created": 0,
            "status": "no_anomalies",
            "history_checked": True,
            "iqr_checked": True,
        }

    stmt = insert(AIInputAnomalyAlert).values(all_rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["entity_key", "window_key", "window_end", "anomaly_type"],
        set_={"score": stmt.excluded.score, "details_json": stmt.excluded.details_json},
    )
    res = db.execute(stmt)
    db.commit()
    n = int(res.rowcount or len(all_rows))

    log.info(
        "input_anomaly_worker alerts=%d history=%d iqr=%d window_end=%s",
        n, len(history_rows), len(iqr_rows), current_window_end,
    )
    return {
        "input_anomaly_alerts_created": n,
        "history_deviation_alerts": len(history_rows),
        "iqr_outlier_alerts": len(iqr_rows),
        "status": "ok",
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    import argparse
    import json

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    p = argparse.ArgumentParser(description="Detect input anomalies using Z-score and IQR methods.")
    p.add_argument("--prediction-type", default="risk_gnn")
    p.add_argument("--window-key", default="Wmid")
    p.add_argument("--z-threshold", type=float, default=3.0,
                   help="Per-entity Z-score threshold for history deviation (default 3.0).")
    p.add_argument("--history-windows", type=int, default=5,
                   help="How many past windows to use for per-entity baseline (default 5).")
    p.add_argument("--iqr-multiplier", type=float, default=1.5,
                   help="IQR fence multiplier for population outlier detection (default 1.5).")
    args = p.parse_args()

    db = SessionLocal()
    try:
        result = run_once(
            db=db,
            prediction_type=args.prediction_type,
            window_key=args.window_key,
            z_threshold=args.z_threshold,
            history_windows=args.history_windows,
            iqr_multiplier=args.iqr_multiplier,
        )
        print(json.dumps(result, default=str))
    finally:
        db.close()


if __name__ == "__main__":
    main()

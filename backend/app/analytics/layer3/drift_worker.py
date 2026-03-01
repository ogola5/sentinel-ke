from __future__ import annotations

import json
from datetime import datetime
from statistics import mean, pstdev
from typing import Dict, List, Optional, Tuple

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.analytics.ai_models import AIDriftReport, AIModelRollout, AIPrediction
from app.core.config import settings
from app.ledger.db import SessionLocal


def _latest_two_windows(
    db: Session,
    *,
    prediction_type: str,
    window_key: str,
    model_version: str,
) -> List[datetime]:
    rows = (
        db.query(AIPrediction.window_end)
        .filter(AIPrediction.prediction_type == prediction_type)
        .filter(AIPrediction.window_key == window_key)
        .filter(AIPrediction.model_version == model_version)
        .group_by(AIPrediction.window_end)
        .order_by(AIPrediction.window_end.desc())
        .limit(2)
        .all()
    )
    return [r[0] for r in rows if r and r[0] is not None]


def _window_scores(
    db: Session,
    *,
    prediction_type: str,
    window_key: str,
    model_version: str,
    window_end: datetime,
    limit: int = 20000,
) -> List[float]:
    rows = (
        db.query(AIPrediction.score)
        .filter(AIPrediction.prediction_type == prediction_type)
        .filter(AIPrediction.window_key == window_key)
        .filter(AIPrediction.model_version == model_version)
        .filter(AIPrediction.window_end == window_end)
        .limit(limit)
        .all()
    )
    return [float(r[0] or 0.0) for r in rows]


def _drift_score(baseline: List[float], current: List[float]) -> Tuple[float, Dict[str, float]]:
    if not baseline or not current:
        return 0.0, {"mean_shift": 0.0, "std_shift": 0.0, "rate_shift": 0.0}

    base_mean = mean(baseline)
    cur_mean = mean(current)
    base_std = pstdev(baseline) if len(baseline) > 1 else 0.0
    cur_std = pstdev(current) if len(current) > 1 else 0.0

    base_high = sum(1 for x in baseline if x >= 75.0) / max(1, len(baseline))
    cur_high = sum(1 for x in current if x >= 75.0) / max(1, len(current))

    mean_shift = abs(cur_mean - base_mean) / 100.0
    std_shift = abs(cur_std - base_std) / 100.0
    rate_shift = abs(cur_high - base_high)
    score = 0.45 * mean_shift + 0.35 * std_shift + 0.2 * rate_shift

    return round(float(score), 6), {
        "mean_shift": round(float(mean_shift), 6),
        "std_shift": round(float(std_shift), 6),
        "rate_shift": round(float(rate_shift), 6),
        "baseline_mean": round(float(base_mean), 6),
        "current_mean": round(float(cur_mean), 6),
        "baseline_std": round(float(base_std), 6),
        "current_std": round(float(cur_std), 6),
        "baseline_high_rate": round(float(base_high), 6),
        "current_high_rate": round(float(cur_high), 6),
    }


def _status_for_score(score: float) -> str:
    if score >= float(settings.ai_drift_critical_threshold):
        return "critical"
    if score >= float(settings.ai_drift_warn_threshold):
        return "warning"
    return "ok"


def _status_rank(status: str) -> int:
    s = str(status or "ok").lower()
    if s == "critical":
        return 3
    if s == "warning":
        return 2
    return 1


def _status_for_fairness(disparity: Optional[float]) -> str:
    if disparity is None:
        return "ok"
    warn_threshold = max(0.0, float(settings.fairness_disparity_threshold) * 0.75)
    crit_threshold = max(0.0, float(settings.fairness_disparity_threshold))
    if float(disparity) > crit_threshold:
        return "critical"
    if float(disparity) > warn_threshold:
        return "warning"
    return "ok"


def _live_fairness_metrics(
    db: Session,
    *,
    prediction_type: str,
    window_key: str,
    model_version: str,
    window_end: datetime,
    positive_threshold: float = 75.0,
    min_group_size: int = 3,
) -> Dict[str, object]:
    rows = (
        db.query(AIPrediction.entity_type, AIPrediction.score)
        .filter(AIPrediction.prediction_type == prediction_type)
        .filter(AIPrediction.window_key == window_key)
        .filter(AIPrediction.model_version == model_version)
        .filter(AIPrediction.window_end == window_end)
        .all()
    )
    grouped: Dict[str, List[float]] = {}
    for entity_type, score in rows:
        grouped.setdefault(str(entity_type or "unknown"), []).append(float(score or 0.0))

    per_type: Dict[str, Dict[str, object]] = {}
    rates: List[float] = []
    for entity_type, scores in grouped.items():
        n = len(scores)
        if n < min_group_size:
            per_type[entity_type] = {"count": n, "skipped": True, "reason": "too_few_samples"}
            continue
        pos = sum(1 for s in scores if float(s) >= positive_threshold)
        rate = pos / max(1, n)
        per_type[entity_type] = {
            "count": n,
            "positive_rate": round(rate, 6),
            "positive_count": int(pos),
        }
        rates.append(rate)

    disparity = round(max(rates) - min(rates), 6) if len(rates) >= 2 else None
    status = _status_for_fairness(disparity)
    return {
        "per_type": per_type,
        "types_evaluated": len(rates),
        "max_positive_rate_disparity": disparity,
        "threshold_score": positive_threshold,
        "status": status,
    }


def _auto_rollback_if_needed(
    db: Session,
    *,
    prediction_type: str,
    model_version: str,
    score: float,
) -> bool:
    if score < float(settings.ai_drift_critical_threshold):
        return False

    rollout = (
        db.query(AIModelRollout)
        .filter(AIModelRollout.prediction_type == prediction_type)
        .filter(AIModelRollout.status == "active")
        .order_by(AIModelRollout.updated_at.desc())
        .first()
    )
    if not rollout or not bool(rollout.auto_rollback):
        return False
    if rollout.active_model_version != model_version:
        return False
    if not rollout.shadow_model_version:
        return False

    prev_active = rollout.active_model_version
    rollout.active_model_version = rollout.shadow_model_version
    rollout.status = "rolled_back"
    md = dict(rollout.metadata_json or {})
    md["rollback_reason"] = "critical_drift"
    md["rolled_back_from"] = prev_active
    md["rolled_back_at"] = datetime.utcnow().isoformat() + "Z"
    rollout.metadata_json = md
    return True


def run_once(
    *,
    db: Session,
    prediction_type: str = "risk_gnn",
    window_key: str = "Wmid",
    model_version: str = "gnn-sage-v1",
) -> Dict[str, object]:
    windows = _latest_two_windows(
        db,
        prediction_type=prediction_type,
        window_key=window_key,
        model_version=model_version,
    )
    if len(windows) < 2:
        return {"status": "insufficient_windows", "upserted": 0}

    current_window, baseline_window = windows[0], windows[1]
    baseline_scores = _window_scores(
        db,
        prediction_type=prediction_type,
        window_key=window_key,
        model_version=model_version,
        window_end=baseline_window,
    )
    current_scores = _window_scores(
        db,
        prediction_type=prediction_type,
        window_key=window_key,
        model_version=model_version,
        window_end=current_window,
    )

    drift_score, metrics = _drift_score(baseline_scores, current_scores)
    drift_status = _status_for_score(drift_score)
    fairness_live = _live_fairness_metrics(
        db,
        prediction_type=prediction_type,
        window_key=window_key,
        model_version=model_version,
        window_end=current_window,
    )
    fairness_status = str(fairness_live.get("status") or "ok")
    status = drift_status if _status_rank(drift_status) >= _status_rank(fairness_status) else fairness_status

    row = {
        "model_version": model_version,
        "prediction_type": prediction_type,
        "window_key": window_key,
        "window_end": current_window,
        "drift_score": drift_score,
        "status": status,
        "metrics_json": {
            **metrics,
            "baseline_window_end": baseline_window.isoformat(),
            "current_window_end": current_window.isoformat(),
            "baseline_count": len(baseline_scores),
            "current_count": len(current_scores),
            "drift_status": drift_status,
            "fairness_live": fairness_live,
        },
    }

    stmt = insert(AIDriftReport).values([row])
    stmt = stmt.on_conflict_do_update(
        index_elements=["model_version", "prediction_type", "window_key", "window_end"],
        set_={
            "drift_score": stmt.excluded.drift_score,
            "status": stmt.excluded.status,
            "metrics_json": stmt.excluded.metrics_json,
            "created_at": stmt.excluded.created_at,
        },
    )
    res = db.execute(stmt)

    rolled_back = _auto_rollback_if_needed(
        db,
        prediction_type=prediction_type,
        model_version=model_version,
        score=drift_score,
    )

    db.commit()
    return {
        "status": status,
        "drift_status": drift_status,
        "fairness_status": fairness_status,
        "drift_score": drift_score,
        "upserted": int(res.rowcount or 0),
        "rolled_back": bool(rolled_back),
        "fairness_live": fairness_live,
    }


def main() -> None:
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--prediction-type", default="risk_gnn")
    p.add_argument("--window-key", default="Wmid")
    p.add_argument("--model-version", default="gnn-sage-v1")
    args = p.parse_args()

    db = SessionLocal()
    try:
        out = run_once(
            db=db,
            prediction_type=args.prediction_type,
            window_key=args.window_key,
            model_version=args.model_version,
        )
        print(json.dumps(out))
    finally:
        db.close()


if __name__ == "__main__":
    main()

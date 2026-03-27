"""
Feedback worker — processes analyst label corrections and triggers GNN retraining.

What it does:
1. Validates queued AIFeedbackLabel rows (status: queued → validated).
2. Counts how many validated labels have not yet been consumed by a training run.
3. When the accumulated count reaches retrain_threshold, fires a retraining run
   so the GNN learns from analyst corrections immediately rather than waiting
   for the next scheduled training cycle.

The actual label integration (weight 1.75 for analyst_feedback) is already
implemented in gnn_train_worker._apply_feedback_overrides(). This worker's
sole job is to act as the trigger.
"""
from __future__ import annotations

import logging
from typing import Dict

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.analytics.ai_models import AIFeedbackLabel
from app.ledger.db import SessionLocal

log = logging.getLogger("sentinel.layer3.feedback_worker")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _count_pending_feedback(db: Session) -> int:
    """Count validated labels not yet consumed by any training run.
    After training, gnn_train_worker._mark_feedback_consumed() sets status='consumed'.
    So 'validated' labels are the ones waiting to be used.
    """
    return (
        db.query(func.count(AIFeedbackLabel.id))
        .filter(AIFeedbackLabel.status == "validated")
        .scalar()
        or 0
    )


def _trigger_retrain(
    db: Session,
    *,
    prediction_type: str,
    window_key: str,
) -> Dict[str, object]:
    """
    Call gnn_train_worker.run_once() to retrain the GNN with the new feedback labels.
    The train worker reads AIFeedbackLabel rows and applies them as gold labels.
    """
    try:
        from app.analytics.layer3.gnn_train_worker import run_once as train_run_once
        result = train_run_once(
            db=db,
            prediction_type=prediction_type,
            window_key=window_key,
        )
        log.info(
            "feedback_worker retrain triggered prediction_type=%s window_key=%s status=%s",
            prediction_type, window_key, result.get("status"),
        )
        return {"triggered": True, "train_result": result.get("status")}
    except Exception as exc:
        log.error("feedback_worker retrain failed err=%s", exc)
        return {"triggered": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# run_once
# ---------------------------------------------------------------------------

def run_once(
    *,
    db: Session,
    batch_size: int = 500,
    retrain_threshold: int = 50,
    prediction_type: str = "risk_gnn",
    window_key: str = "Wmid",
    auto_retrain: bool = True,
) -> Dict[str, object]:
    """
    Parameters
    ----------
    retrain_threshold : Number of new validated labels that triggers a retraining run.
    auto_retrain      : Set False to validate labels without triggering retraining
                        (useful in tests or when retraining is managed externally).
    """
    # Step 1: validate queued labels
    rows = (
        db.query(AIFeedbackLabel)
        .filter(AIFeedbackLabel.status == "queued")
        .order_by(AIFeedbackLabel.created_at.asc())
        .limit(max(1, int(batch_size)))
        .all()
    )
    for r in rows:
        r.status = "validated"
        r.used_in_training = True
    if rows:
        db.commit()

    # Step 2: count accumulated labels not yet consumed
    pending = _count_pending_feedback(db)
    log.info(
        "feedback_worker validated=%d accumulated_pending=%d threshold=%d",
        len(rows), pending, retrain_threshold,
    )

    # Step 3: trigger retraining if threshold reached
    retrain_result: Dict[str, object] = {"triggered": False}
    if auto_retrain and pending >= retrain_threshold:
        retrain_result = _trigger_retrain(db, prediction_type=prediction_type, window_key=window_key)

    return {
        "queued_found": len(rows),
        "processed": len(rows),
        "accumulated_pending": pending,
        "retrain_threshold": retrain_threshold,
        **retrain_result,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    import argparse
    import json

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    p = argparse.ArgumentParser(description="Process analyst feedback labels and optionally trigger GNN retraining.")
    p.add_argument("--batch-size", type=int, default=500)
    p.add_argument("--retrain-threshold", type=int, default=50,
                   help="Number of new validated labels before retraining is triggered (default 50).")
    p.add_argument("--prediction-type", default="risk_gnn")
    p.add_argument("--window-key", default="Wmid")
    p.add_argument("--no-auto-retrain", action="store_true",
                   help="Validate labels but do not trigger retraining.")
    args = p.parse_args()

    db = SessionLocal()
    try:
        result = run_once(
            db=db,
            batch_size=args.batch_size,
            retrain_threshold=args.retrain_threshold,
            prediction_type=args.prediction_type,
            window_key=args.window_key,
            auto_retrain=not args.no_auto_retrain,
        )
        print(json.dumps(result, default=str))
    finally:
        db.close()


if __name__ == "__main__":
    main()

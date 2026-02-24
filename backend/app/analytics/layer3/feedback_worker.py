from __future__ import annotations

import json
from typing import Dict

from sqlalchemy.orm import Session

from app.analytics.ai_models import AIFeedbackLabel
from app.ledger.db import SessionLocal


def run_once(*, db: Session, batch_size: int = 500) -> Dict[str, int]:
    rows = (
        db.query(AIFeedbackLabel)
        .filter(AIFeedbackLabel.status == "queued")
        .order_by(AIFeedbackLabel.created_at.asc())
        .limit(max(1, int(batch_size)))
        .all()
    )
    if not rows:
        return {"queued": 0, "processed": 0}

    processed = 0
    for r in rows:
        r.status = "validated"
        r.used_in_training = True
        processed += 1

    db.commit()
    return {"queued": len(rows), "processed": processed}


def main() -> None:
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--batch-size", type=int, default=500)
    args = p.parse_args()

    db = SessionLocal()
    try:
        out = run_once(db=db, batch_size=args.batch_size)
        print(json.dumps(out))
    finally:
        db.close()


if __name__ == "__main__":
    main()

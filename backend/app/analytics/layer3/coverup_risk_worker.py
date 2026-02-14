from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy.orm import Session

from app.economy.coverup import run_coverup_detection
from app.ledger.db import SessionLocal
from app.legal.service import LegalAuthorizationService


def run_once(
    *,
    db: Session,
    window_days: int = 30,
    as_of: datetime | None = None,
    min_score: float = 0.45,
) -> dict:
    return run_coverup_detection(db, window_days=window_days, as_of=as_of, min_score=min_score)


def main() -> None:
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--window-days", type=int, default=30)
    p.add_argument("--as-of", default=None, help="ISO timestamp override")
    p.add_argument("--min-score", type=float, default=0.45)
    p.add_argument("--grant-token", required=True, help="Legal execution token from /v1/legal/authorize")
    p.add_argument("--target", default="economy:coverup")
    args = p.parse_args()

    as_of = None
    if args.as_of:
        as_of = datetime.fromisoformat(args.as_of.replace("Z", "+00:00"))

    db = SessionLocal()
    try:
        auth = LegalAuthorizationService(db).verify_grant_token(
            execution_token=args.grant_token,
            action_type="coverup_risk_scan",
            target=args.target,
            actor_id="coverup_risk_worker",
        )
        res = run_coverup_detection(
            db,
            window_days=args.window_days,
            as_of=as_of,
            min_score=args.min_score,
        )
        res["legal_authorization"] = auth
        print(json.dumps(res))
    finally:
        db.close()


if __name__ == "__main__":
    main()

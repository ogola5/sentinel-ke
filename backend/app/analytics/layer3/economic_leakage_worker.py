from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy.orm import Session

from app.economy.leakage import run_leakage_detection
from app.ledger.db import SessionLocal


def run_once(*, db: Session, window_days: int = 30) -> dict:
    return run_leakage_detection(db, window_days=window_days)


def main() -> None:
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--window-days", type=int, default=30)
    p.add_argument("--as-of", default=None, help="ISO timestamp override")
    args = p.parse_args()

    as_of = None
    if args.as_of:
        as_of = datetime.fromisoformat(args.as_of.replace("Z", "+00:00"))

    db = SessionLocal()
    try:
        res = run_leakage_detection(db, window_days=args.window_days, as_of=as_of)
        print(json.dumps(res))
    finally:
        db.close()


if __name__ == "__main__":
    main()

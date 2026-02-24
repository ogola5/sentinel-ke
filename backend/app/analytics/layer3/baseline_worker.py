from __future__ import annotations

import json
from collections import defaultdict
from statistics import mean, pstdev
from typing import Dict, List

from sqlalchemy import desc
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.analytics.ai_models import AIPrediction, EntityRiskBaseline
from app.ledger.db import SessionLocal


def run_once(
    *,
    db: Session,
    prediction_type: str = "risk_gnn",
    window_key: str = "Wmid",
    history_windows: int = 10,
    max_entities: int = 10000,
) -> int:
    rows = (
        db.query(AIPrediction)
        .filter(AIPrediction.prediction_type == prediction_type)
        .filter(AIPrediction.window_key == window_key)
        .order_by(desc(AIPrediction.window_end))
        .limit(max_entities)
        .all()
    )
    if not rows:
        return 0

    by_entity: Dict[str, List[AIPrediction]] = defaultdict(list)
    for r in rows:
        key = str(r.entity_key)
        if len(by_entity[key]) >= max(2, int(history_windows)):
            continue
        by_entity[key].append(r)

    upserts = []
    for entity_key, vals in by_entity.items():
        scores = [float(v.score or 0.0) for v in vals]
        if len(scores) < 2:
            continue
        upserts.append(
            {
                "entity_key": entity_key,
                "entity_type": str(vals[0].entity_type or "unknown"),
                "window_key": window_key,
                "baseline_score": round(float(mean(scores)), 6),
                "baseline_std": round(float(pstdev(scores) if len(scores) > 1 else 0.0), 6),
                "sample_count": len(scores),
                "last_window_end": vals[0].window_end,
            }
        )

    if not upserts:
        return 0

    stmt = insert(EntityRiskBaseline).values(upserts)
    stmt = stmt.on_conflict_do_update(
        index_elements=["entity_key", "window_key"],
        set_={
            "entity_type": stmt.excluded.entity_type,
            "baseline_score": stmt.excluded.baseline_score,
            "baseline_std": stmt.excluded.baseline_std,
            "sample_count": stmt.excluded.sample_count,
            "last_window_end": stmt.excluded.last_window_end,
            "updated_at": stmt.excluded.updated_at,
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
    p.add_argument("--history-windows", type=int, default=10)
    args = p.parse_args()

    db = SessionLocal()
    try:
        n = run_once(
            db=db,
            prediction_type=args.prediction_type,
            window_key=args.window_key,
            history_windows=args.history_windows,
        )
        print(json.dumps({"baselines_upserted": n}))
    finally:
        db.close()


if __name__ == "__main__":
    main()

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from sqlalchemy import func, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.analytics.ai_models import AIAttackPathScore, AIPrediction
from app.ledger.db import SessionLocal


def _latest_window_end(db: Session, prediction_type: str) -> Optional[datetime]:
    return (
        db.query(func.max(AIPrediction.window_end))
        .filter(AIPrediction.prediction_type == prediction_type)
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
        window_end = _latest_window_end(db, prediction_type)
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

    score_by_entity: Dict[str, float] = {str(p.entity_key): float(p.score or 0.0) for p in preds}
    entities = sorted(score_by_entity.keys())

    rows = db.execute(
        text(
            """
            SELECT a.entity_key AS src, b.entity_key AS dst, COUNT(*)::float AS weight
            FROM event_entity_index a
            JOIN event_entity_index b
              ON a.event_hash = b.event_hash
             AND a.entity_key < b.entity_key
            JOIN event_log el ON el.event_hash = a.event_hash
            WHERE el.occurred_at <= :window_end
              AND a.entity_key = ANY(:entities)
              AND b.entity_key = ANY(:entities)
            GROUP BY a.entity_key, b.entity_key
            HAVING COUNT(*) >= 1
            """
        ),
        {"window_end": window_end, "entities": entities},
    ).fetchall()

    adj: Dict[str, List[Tuple[str, float]]] = defaultdict(list)
    for src, dst, w in rows:
        s = str(src)
        d = str(dst)
        weight = float(w or 0.0)
        adj[s].append((d, weight))
        adj[d].append((s, weight))

    upserts = []
    for entity_key in entities:
        neigh = sorted(adj.get(entity_key, []), key=lambda x: x[1], reverse=True)
        top_neigh = neigh[:5]
        if not top_neigh:
            path_score = score_by_entity.get(entity_key, 0.0)
            evidence = []
            hop_count = 0
        else:
            neigh_score = sum(score_by_entity.get(n, 0.0) * min(1.0, w / 5.0) for n, w in top_neigh)
            path_score = min(100.0, 0.7 * score_by_entity.get(entity_key, 0.0) + 0.3 * neigh_score)
            evidence = [n for n, _ in top_neigh]
            hop_count = 1

        upserts.append(
            {
                "entity_key": entity_key,
                "prediction_type": prediction_type,
                "window_key": window_key,
                "window_end": window_end,
                "path_score": round(float(path_score), 6),
                "hop_count": hop_count,
                "evidence_entity_keys": evidence,
                "details_json": {
                    "neighbor_count": len(neigh),
                    "top_neighbors": evidence,
                },
            }
        )

    if not upserts:
        return 0

    stmt = insert(AIAttackPathScore).values(upserts)
    stmt = stmt.on_conflict_do_update(
        index_elements=["entity_key", "prediction_type", "window_key", "window_end"],
        set_={
            "path_score": stmt.excluded.path_score,
            "hop_count": stmt.excluded.hop_count,
            "evidence_entity_keys": stmt.excluded.evidence_entity_keys,
            "details_json": stmt.excluded.details_json,
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
        print(json.dumps({"path_scores_upserted": n}))
    finally:
        db.close()


if __name__ == "__main__":
    main()

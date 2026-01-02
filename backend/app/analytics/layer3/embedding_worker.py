from __future__ import annotations

import hashlib
from typing import List, Optional

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.analytics.ai_models import EntityEmbedding, GraphFeatureSnapshot
from app.ledger.db import SessionLocal


def _hash_embedding(seed: str, dims: int = 16) -> List[float]:
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    values: List[float] = []
    for i in range(0, dims * 2, 2):
        chunk = digest[i:i + 2]
        if len(chunk) < 2:
            chunk = hashlib.sha256(chunk).digest()[:2]
        val = int.from_bytes(chunk, "big") / 65535.0
        values.append(round(val, 6))
    return values


def _latest_window_end(db: Session, window_key: str) -> Optional[object]:
    return (
        db.query(func.max(GraphFeatureSnapshot.window_end))
        .filter(GraphFeatureSnapshot.window_key == window_key)
        .scalar()
    )


def run_once(
    *,
    db: Session,
    window_key: str = "Wshort",
    window_end: Optional[object] = None,
    dims: int = 16,
    model_version: str = "hash-v1",
) -> int:
    if window_end is None:
        window_end = _latest_window_end(db, window_key)
    if window_end is None:
        return 0

    snapshots = (
        db.query(GraphFeatureSnapshot)
        .filter(GraphFeatureSnapshot.window_key == window_key)
        .filter(GraphFeatureSnapshot.window_end == window_end)
        .all()
    )
    if not snapshots:
        return 0

    rows = []
    for snap in snapshots:
        seed = f"{snap.entity_key}:{window_key}:{snap.window_end.isoformat()}"
        rows.append(
            {
                "entity_key": snap.entity_key,
                "entity_type": snap.entity_type,
                "window_key": window_key,
                "window_end": snap.window_end,
                "model_version": model_version,
                "embedding": _hash_embedding(seed, dims=dims),
            }
        )

    stmt = insert(EntityEmbedding).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["entity_key", "window_key", "window_end", "model_version"],
        set_={"embedding": stmt.excluded.embedding},
    )
    res = db.execute(stmt)
    db.commit()
    return res.rowcount or 0


def main() -> None:
    import argparse
    import json

    p = argparse.ArgumentParser()
    p.add_argument("--window-key", default="Wshort")
    p.add_argument("--window-end", default=None, help="ISO timestamp override")
    p.add_argument("--dims", type=int, default=16)
    p.add_argument("--model-version", default="hash-v1")
    args = p.parse_args()

    window_end = None
    if args.window_end:
        from datetime import datetime

        window_end = datetime.fromisoformat(args.window_end.replace("Z", "+00:00"))

    db = SessionLocal()
    try:
        n = run_once(
            db=db,
            window_key=args.window_key,
            window_end=window_end,
            dims=args.dims,
            model_version=args.model_version,
        )
        print(json.dumps({"embeddings_upserted": n}))
    finally:
        db.close()


if __name__ == "__main__":
    main()

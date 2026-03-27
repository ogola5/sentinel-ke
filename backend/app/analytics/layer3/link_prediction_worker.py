"""
Link prediction worker — finds new suspects by embedding similarity.

After a GNN training run, every entity has a real embedding in EntityEmbedding.
This worker uses cosine similarity to ask: "which entities are most similar
to known high-risk entities?" — surfacing new suspects the analyst hasn't
looked at yet.

Algorithm:
1. Read EntityEmbedding rows for the latest window (prefers GNN, falls back to hash).
2. Read AIPrediction rows to identify HIGH-RISK anchors (score >= risk_threshold).
3. For each high-risk anchor: compute cosine similarity against every other entity.
4. Write top-K per anchor to AILinkPrediction (method="cosine_similarity").

Unlike the training-time dot-product scan in gnn_train_worker, this:
- Uses cosine similarity (magnitude-invariant, better for cross-type comparison)
- Runs between training runs so new entities get scored immediately
- Focuses on high-risk anchors so O(n²) is bounded to anchor_count × n
"""
from __future__ import annotations

import logging
import math
from typing import Dict, List, Optional, Sequence, Tuple

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.analytics.ai_models import AILinkPrediction, AIPrediction, EntityEmbedding
from app.ledger.db import SessionLocal

log = logging.getLogger("sentinel.layer3.link_prediction_worker")


# ---------------------------------------------------------------------------
# Math helpers
# ---------------------------------------------------------------------------

def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(float(x) * float(y) for x, y in zip(a, b))
    mag_a = math.sqrt(sum(float(x) ** 2 for x in a))
    mag_b = math.sqrt(sum(float(x) ** 2 for x in b))
    if mag_a < 1e-9 or mag_b < 1e-9:
        return 0.0
    return round(dot / (mag_a * mag_b), 6)


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _latest_window_end(db: Session, window_key: str):
    return (
        db.query(func.max(EntityEmbedding.window_end))
        .filter(EntityEmbedding.window_key == window_key)
        .scalar()
    )


def _load_embeddings(
    db: Session,
    window_key: str,
    window_end,
) -> Tuple[List[str], List[str], List[List[float]], str]:
    """
    Return (entity_keys, entity_types, embeddings, model_version).
    Prefers the most recent non-hash model_version.
    """
    # Find the best model_version: prefer non-hash
    version_row = (
        db.query(EntityEmbedding.model_version)
        .filter(EntityEmbedding.window_key == window_key)
        .filter(EntityEmbedding.window_end == window_end)
        .filter(EntityEmbedding.model_version != "hash-v1")
        .order_by(EntityEmbedding.model_version.desc())
        .first()
    )
    model_version = str(version_row[0]) if version_row else "hash-v1"

    rows = (
        db.query(EntityEmbedding)
        .filter(EntityEmbedding.window_key == window_key)
        .filter(EntityEmbedding.window_end == window_end)
        .filter(EntityEmbedding.model_version == model_version)
        .all()
    )

    keys = [str(r.entity_key) for r in rows]
    types = [str(r.entity_type) for r in rows]
    embs = [[float(v) for v in (r.embedding or [])] for r in rows]
    return keys, types, embs, model_version


def _high_risk_anchors(
    db: Session,
    window_key: str,
    window_end,
    prediction_type: str,
    risk_threshold: float,
) -> Dict[str, float]:
    """Return {entity_key: score} for entities above risk_threshold."""
    rows = (
        db.query(AIPrediction.entity_key, AIPrediction.score)
        .filter(AIPrediction.window_key == window_key)
        .filter(AIPrediction.window_end == window_end)
        .filter(AIPrediction.prediction_type == prediction_type)
        .filter(AIPrediction.score >= risk_threshold)
        .all()
    )
    return {str(r[0]): float(r[1]) for r in rows}


# ---------------------------------------------------------------------------
# run_once
# ---------------------------------------------------------------------------

def run_once(
    *,
    db: Session,
    window_key: str = "Wmid",
    window_end=None,
    prediction_type: str = "risk_gnn",
    risk_threshold: float = 0.65,
    top_k: int = 20,
    min_similarity: float = 0.60,
) -> dict:
    """
    Parameters
    ----------
    risk_threshold : GNN score threshold to qualify an entity as a high-risk anchor.
    top_k          : Max similar entities to store per anchor.
    min_similarity : Cosine similarity floor (filters noise).
    """
    if window_end is None:
        window_end = _latest_window_end(db, window_key)
    if window_end is None:
        return {"status": "no_embeddings", "link_predictions_upserted": 0}

    entity_keys, entity_types, embeddings, model_version = _load_embeddings(
        db, window_key, window_end
    )
    if not entity_keys:
        return {"status": "no_embeddings", "link_predictions_upserted": 0}

    anchors = _high_risk_anchors(db, window_key, window_end, prediction_type, risk_threshold)
    if not anchors:
        log.info("link_prediction_worker: no high-risk anchors at threshold=%.2f", risk_threshold)
        return {"status": "no_anchors", "link_predictions_upserted": 0, "model_version": model_version}

    # Index embeddings by entity_key for fast lookup
    emb_by_key: Dict[str, List[float]] = {
        entity_keys[i]: embeddings[i]
        for i in range(len(entity_keys))
        if embeddings[i]
    }

    rows = []
    for anchor_key, anchor_score in anchors.items():
        anchor_emb = emb_by_key.get(anchor_key)
        if not anchor_emb:
            continue

        # Score all other entities by cosine similarity
        candidates: List[Tuple[float, str, str]] = []
        for i, ek in enumerate(entity_keys):
            if ek == anchor_key or not embeddings[i]:
                continue
            sim = _cosine(anchor_emb, embeddings[i])
            if sim >= min_similarity:
                candidates.append((sim, ek, entity_types[i]))

        # Keep top_k by similarity
        candidates.sort(reverse=True)
        for sim, dst_key, dst_type in candidates[:top_k]:
            rows.append({
                "src_entity_key": anchor_key,
                "dst_entity_key": dst_key,
                "prediction_type": prediction_type,
                "model_version": model_version,
                "window_key": window_key,
                "window_end": window_end,
                "score": sim,
                "method": "cosine_similarity",
                "details_json": {
                    "anchor_score": anchor_score,
                    "similarity": sim,
                    "dst_entity_type": dst_type,
                },
            })

    if not rows:
        return {"status": "no_links", "link_predictions_upserted": 0, "model_version": model_version}

    stmt = insert(AILinkPrediction).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=[
            "src_entity_key", "dst_entity_key",
            "prediction_type", "model_version",
            "window_key", "window_end",
        ],
        set_={"score": stmt.excluded.score, "details_json": stmt.excluded.details_json},
    )
    res = db.execute(stmt)
    db.commit()
    n = int(res.rowcount or len(rows))
    log.info(
        "link_prediction_worker anchors=%d rows=%d upserted=%d version=%s",
        len(anchors), len(rows), n, model_version,
    )
    return {
        "status": "ok",
        "link_predictions_upserted": n,
        "anchors": len(anchors),
        "model_version": model_version,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    import argparse
    import json

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    p = argparse.ArgumentParser(description="Find new suspects via GNN embedding cosine similarity.")
    p.add_argument("--window-key", default="Wmid")
    p.add_argument("--prediction-type", default="risk_gnn")
    p.add_argument("--risk-threshold", type=float, default=0.65,
                   help="Min GNN score to qualify as a high-risk anchor (default 0.65).")
    p.add_argument("--top-k", type=int, default=20,
                   help="Max similar entities to store per anchor (default 20).")
    p.add_argument("--min-similarity", type=float, default=0.60,
                   help="Min cosine similarity to include (default 0.60).")
    args = p.parse_args()

    db = SessionLocal()
    try:
        result = run_once(
            db=db,
            window_key=args.window_key,
            prediction_type=args.prediction_type,
            risk_threshold=args.risk_threshold,
            top_k=args.top_k,
            min_similarity=args.min_similarity,
        )
        print(json.dumps(result))
    finally:
        db.close()


if __name__ == "__main__":
    main()

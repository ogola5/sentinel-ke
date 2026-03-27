"""
Embedding worker — produces real GNN embeddings for all entities.

Priority order:
1. If a trained GNN artifact exists: run forward pass → real embed_dim embeddings
2. For entities not yet embedded (new arrivals between training runs): hash fallback
3. Cold-start (no artifact at all): hash fallback for everything

The DB always has embeddings for every entity in the current window.
They become real GNN embeddings as soon as the first training run completes.
"""
from __future__ import annotations

import hashlib
import logging
import os
from typing import Dict, List, Optional, Sequence

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.analytics.ai_models import EntityEmbedding, GNNTrainingRun, GraphFeatureSnapshot
from app.ledger.db import SessionLocal

log = logging.getLogger("sentinel.layer3.embedding_worker")


# ---------------------------------------------------------------------------
# Hash fallback (cold-start / new entities only)
# ---------------------------------------------------------------------------

def _hash_embedding(seed: str, dims: int = 32) -> List[float]:
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    values: List[float] = []
    for i in range(dims):
        idx = (i * 2) % len(digest)
        chunk = digest[idx: idx + 2]
        if len(chunk) < 2:
            chunk = hashlib.sha256(chunk).digest()[:2]
        val = int.from_bytes(chunk, "big") / 65535.0
        values.append(round(val, 6))
    return values


# ---------------------------------------------------------------------------
# GNN artifact → real embeddings
# ---------------------------------------------------------------------------

def _load_gnn_embeddings(
    artifact_path: str,
    snapshots: Sequence,
    *,
    hidden_dim: int = 64,
    embed_dim: int = 32,
    feat_dim: int = 44,
) -> Optional[Dict[str, List[float]]]:
    """
    Load trained GNN artifact, run forward pass, return {entity_key: embedding}.
    Returns None if torch is unavailable or artifact is corrupt.
    """
    try:
        import torch
        from app.analytics.layer3.gnn_backbone import build_feature_vector
        from app.analytics.layer3.gnn_model import build_sentinel_gnn
    except ImportError:
        log.warning("embedding_worker: torch not available, using hash fallback")
        return None

    try:
        state = torch.load(artifact_path, map_location="cpu", weights_only=False)
        model_state = state.get("model_state") if isinstance(state, dict) else state
        feat_dim_saved = int(state.get("feat_dim", feat_dim)) if isinstance(state, dict) else feat_dim

        model = build_sentinel_gnn(
            feat_dim=feat_dim_saved,
            hidden_dim=hidden_dim,
            embed_dim=embed_dim,
        )
        model.load_state_dict(model_state, strict=False)
        model.eval()
    except Exception as exc:
        log.warning("embedding_worker: artifact load failed path=%s err=%s", artifact_path, exc)
        return None

    try:
        feature_rows: List[List[float]] = []
        entity_keys: List[str] = []
        for snap in snapshots:
            fv = build_feature_vector(snap)
            feature_rows.append(fv)
            entity_keys.append(str(snap.entity_key))

        feat_tensor = torch.tensor(feature_rows, dtype=torch.float32)
        n = feat_tensor.shape[0]
        # Self-loop edges only — no neighborhood aggregation needed for standalone embed
        edge_index = torch.stack([
            torch.arange(n, dtype=torch.long),
            torch.arange(n, dtype=torch.long),
        ], dim=0)

        with torch.no_grad():
            embeddings = model.embed(feat_tensor, edge_index)  # [n, embed_dim]

        return {
            entity_keys[i]: [round(float(v), 6) for v in embeddings[i].tolist()]
            for i in range(len(entity_keys))
        }
    except Exception as exc:
        log.warning("embedding_worker: forward pass failed err=%s", exc)
        return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _latest_window_end(db: Session, window_key: str):
    return (
        db.query(func.max(GraphFeatureSnapshot.window_end))
        .filter(GraphFeatureSnapshot.window_key == window_key)
        .scalar()
    )


def _latest_training_run(db: Session, window_key: str) -> Optional[GNNTrainingRun]:
    return (
        db.query(GNNTrainingRun)
        .filter(GNNTrainingRun.window_key == window_key)
        .order_by(GNNTrainingRun.window_end.desc())
        .first()
    )


def _already_embedded_keys(db: Session, window_key: str, window_end, model_version: str):
    rows = (
        db.query(EntityEmbedding.entity_key)
        .filter(EntityEmbedding.window_key == window_key)
        .filter(EntityEmbedding.window_end == window_end)
        .filter(EntityEmbedding.model_version == model_version)
        .all()
    )
    return {str(r[0]) for r in rows}


# ---------------------------------------------------------------------------
# run_once
# ---------------------------------------------------------------------------

def run_once(
    *,
    db: Session,
    window_key: str = "Wmid",
    window_end=None,
    model_version: Optional[str] = None,
) -> dict:
    if window_end is None:
        window_end = _latest_window_end(db, window_key)
    if window_end is None:
        return {"embeddings_upserted": 0, "mode": "no_data"}

    snapshots = (
        db.query(GraphFeatureSnapshot)
        .filter(GraphFeatureSnapshot.window_key == window_key)
        .filter(GraphFeatureSnapshot.window_end == window_end)
        .all()
    )
    if not snapshots:
        return {"embeddings_upserted": 0, "mode": "no_snapshots"}

    # Resolve training artifact
    training_run = _latest_training_run(db, window_key)
    artifact_path: Optional[str] = None
    effective_version = model_version or "hash-v1"
    hidden_dim = 64
    embed_dim = 32

    if training_run and training_run.artifact_path:
        if os.path.exists(str(training_run.artifact_path)):
            artifact_path = str(training_run.artifact_path)
            effective_version = model_version or str(training_run.model_version)
            params = training_run.params_json or {}
            hidden_dim = int(params.get("hidden_dim", 64))
            embed_dim = int(params.get("embed_dim", 32))

    # Skip entities already embedded with this version (idempotent)
    already_done = _already_embedded_keys(db, window_key, window_end, effective_version)
    pending = [s for s in snapshots if str(s.entity_key) not in already_done]
    if not pending:
        return {"embeddings_upserted": 0, "mode": "already_current", "model_version": effective_version}

    # Try GNN forward pass
    gnn_embeddings: Optional[Dict[str, List[float]]] = None
    mode = "hash_fallback"
    if artifact_path:
        gnn_embeddings = _load_gnn_embeddings(
            artifact_path, pending,
            hidden_dim=hidden_dim,
            embed_dim=embed_dim,
        )
        if gnn_embeddings:
            mode = "gnn_artifact"

    # Build rows — use GNN embedding if available, hash otherwise
    rows = []
    for snap in pending:
        ek = str(snap.entity_key)
        if gnn_embeddings and ek in gnn_embeddings:
            emb = gnn_embeddings[ek]
        else:
            seed = f"{ek}:{window_key}:{window_end.isoformat()}"
            emb = _hash_embedding(seed, dims=embed_dim)
        rows.append({
            "entity_key": ek,
            "entity_type": snap.entity_type,
            "window_key": window_key,
            "window_end": window_end,
            "model_version": effective_version,
            "embedding": emb,
        })

    stmt = insert(EntityEmbedding).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["entity_key", "window_key", "window_end", "model_version"],
        set_={"embedding": stmt.excluded.embedding},
    )
    res = db.execute(stmt)
    db.commit()
    n = int(res.rowcount or len(rows))
    log.info("embedding_worker mode=%s version=%s upserted=%d", mode, effective_version, n)
    return {"embeddings_upserted": n, "mode": mode, "model_version": effective_version}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    import argparse
    import json

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    p = argparse.ArgumentParser(description="Generate entity embeddings from GNN artifact or hash fallback.")
    p.add_argument("--window-key", default="Wmid")
    p.add_argument("--window-end", default=None, help="ISO timestamp override")
    p.add_argument("--model-version", default=None, help="Override model version tag")
    args = p.parse_args()

    window_end = None
    if args.window_end:
        from datetime import datetime
        window_end = datetime.fromisoformat(args.window_end.replace("Z", "+00:00"))

    db = SessionLocal()
    try:
        result = run_once(db=db, window_key=args.window_key, window_end=window_end, model_version=args.model_version)
        print(json.dumps(result))
    finally:
        db.close()


if __name__ == "__main__":
    main()

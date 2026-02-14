from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.analytics.ai_models import (
    AIExplanation,
    AIPrediction,
    EntityEmbedding,
    GNNTrainingRun,
)
from app.analytics.layer3.gnn_backbone import GNNDataset, load_dataset
from app.analytics.layer3.gnn_model import train_graphsage
from app.core.config import settings
from app.ledger.db import SessionLocal


def _event_hashes(
    db: Session,
    *,
    entity_key: str,
    window_start: datetime,
    window_end: datetime,
    limit: int = 20,
) -> List[str]:
    rows = db.execute(
        text(
            """
            SELECT ee.event_hash
            FROM event_entity_index ee
            JOIN event_log el ON el.event_hash = ee.event_hash
            WHERE ee.entity_key = :entity_key
              AND el.occurred_at >= :start
              AND el.occurred_at <= :end
            ORDER BY el.occurred_at DESC
            LIMIT :limit
            """
        ),
        {
            "entity_key": entity_key,
            "start": window_start,
            "end": window_end,
            "limit": limit,
        },
    ).fetchall()
    return [str(r[0]) for r in rows]


def _reason_codes(meta: Dict[str, object], prob: float) -> List[str]:
    reasons: List[str] = []
    risk_flags = set(meta.get("risk_flags") or [])
    event_count = int(meta.get("event_count") or 0)
    source_count = int(meta.get("source_count") or 0)
    event_types = meta.get("event_types") or {}

    if prob >= 0.9:
        reasons.append("GNN_RISK_CRITICAL")
    elif prob >= 0.75:
        reasons.append("GNN_RISK_HIGH")
    elif prob >= 0.55:
        reasons.append("GNN_RISK_ELEVATED")
    else:
        reasons.append("GNN_RISK_LOW")

    if source_count >= 3:
        reasons.append("MULTI_SOURCE")
    if event_count >= 20:
        reasons.append("EVENT_VOLUME_HIGH")
    elif event_count >= 8:
        reasons.append("EVENT_VOLUME_MED")

    if "CAMPAIGN_ENTITY" in risk_flags:
        reasons.append("CAMPAIGN_LINKED")
    if "VPN_CLUSTER_MEMBER" in risk_flags:
        reasons.append("VPN_INFRA_REUSE")
    if "DDOS_CLUSTER_MEMBER" in risk_flags:
        reasons.append("DDOS_INFRA_REUSE")
    if "DDOS_ALERT_SERVICE" in risk_flags or "DDOS_ALERT_ENDPOINT" in risk_flags:
        reasons.append("DDOS_ALERT_ACTIVE")

    if isinstance(event_types, dict):
        ranked = sorted(
            ((str(k), int(v or 0)) for k, v in event_types.items()),
            key=lambda x: x[1],
            reverse=True,
        )
        for name, count in ranked[:2]:
            if count > 0:
                reasons.append(f"TOP_EVENT_{name}")

    return sorted(set(reasons))


def _persist_artifact(
    *,
    run_id: str,
    model_state,
    artifact_dir: str,
    metadata: Dict[str, object],
) -> Optional[str]:
    try:
        import torch

        d = Path(artifact_dir)
        d.mkdir(parents=True, exist_ok=True)
        out_path = d / f"{run_id}.pt"
        torch.save(
            {
                "model_state": model_state,
                "metadata": metadata,
            },
            str(out_path),
        )
        return str(out_path)
    except Exception:
        return None


def _upsert_embeddings(
    db: Session,
    *,
    dataset: GNNDataset,
    model_version: str,
    embeddings: List[List[float]],
) -> int:
    if not embeddings:
        return 0

    rows = []
    for i, emb in enumerate(embeddings):
        rows.append(
            {
                "entity_key": dataset.entity_keys[i],
                "entity_type": dataset.entity_types[i],
                "window_key": dataset.window_key,
                "window_end": dataset.window_end,
                "model_version": model_version,
                "embedding": [round(float(v), 6) for v in emb],
            }
        )

    stmt = insert(EntityEmbedding).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["entity_key", "window_key", "window_end", "model_version"],
        set_={"embedding": stmt.excluded.embedding},
    )
    res = db.execute(stmt)
    return int(res.rowcount or 0)


def run_once(
    *,
    db: Session,
    window_key: str,
    window_end: Optional[datetime] = None,
    edge_backend: str = "hybrid",
    max_entities: int = 3000,
    max_edges: int = 30000,
    min_edge_weight: int = 1,
    epochs: int = 60,
    hidden_dim: int = 64,
    embed_dim: int = 32,
    dropout: float = 0.2,
    learning_rate: float = 0.001,
    weight_decay: float = 0.0001,
    seed: int = 7,
    model_version: str = "gnn-sage-v1",
    prediction_type: str = "risk_gnn",
    artifact_dir: str = "/app/artifacts/gnn",
) -> Dict[str, object]:
    dataset = load_dataset(
        db,
        window_key=window_key,
        window_end=window_end,
        max_entities=max_entities,
        edge_backend=edge_backend,
        min_edge_weight=min_edge_weight,
        max_edges=max_edges,
    )
    if dataset is None:
        return {"status": "no_data", "created": 0, "updated": 0}

    train_result = train_graphsage(
        dataset,
        epochs=epochs,
        hidden_dim=hidden_dim,
        embed_dim=embed_dim,
        dropout=dropout,
        learning_rate=learning_rate,
        weight_decay=weight_decay,
        seed=seed,
    )

    run = GNNTrainingRun(
        model_version=model_version,
        prediction_type=prediction_type,
        source_backend=dataset.source_backend_used,
        window_key=dataset.window_key,
        window_end=dataset.window_end,
        node_count=len(dataset.entity_keys),
        edge_count=len(dataset.edges),
        feature_dim=len(dataset.feature_matrix[0]) if dataset.feature_matrix else 0,
        positive_count=sum(int(v) for v in dataset.labels),
        epochs=int(epochs),
        train_loss=float(train_result.metrics.get("train_loss") or 0.0),
        val_loss=float(train_result.metrics.get("val_loss") or 0.0),
        auc=float(train_result.metrics.get("auc") or 0.0),
        precision=float(train_result.metrics.get("precision") or 0.0),
        recall=float(train_result.metrics.get("recall") or 0.0),
        f1=float(train_result.metrics.get("f1") or 0.0),
        params_json={
            "edge_backend": edge_backend,
            "max_entities": max_entities,
            "max_edges": max_edges,
            "min_edge_weight": min_edge_weight,
            "epochs": epochs,
            "hidden_dim": hidden_dim,
            "embed_dim": embed_dim,
            "dropout": dropout,
            "learning_rate": learning_rate,
            "weight_decay": weight_decay,
            "seed": seed,
        },
        metrics_json=train_result.metrics,
    )
    db.add(run)
    db.flush()

    artifact_path = _persist_artifact(
        run_id=str(run.id),
        model_state=train_result.model_state,
        artifact_dir=artifact_dir,
        metadata={
            "model_version": model_version,
            "prediction_type": prediction_type,
            "window_key": dataset.window_key,
            "window_end": dataset.window_end.isoformat(),
            "feature_dim": len(dataset.feature_matrix[0]) if dataset.feature_matrix else 0,
            "hidden_dim": hidden_dim,
            "embed_dim": embed_dim,
        },
    )
    run.artifact_path = artifact_path

    embeddings_upserted = _upsert_embeddings(
        db,
        dataset=dataset,
        model_version=model_version,
        embeddings=train_result.embeddings,
    )

    created = 0
    updated = 0

    for i, entity_key in enumerate(dataset.entity_keys):
        prob = float(train_result.probabilities[i])
        score = round(prob * 100.0, 4)
        meta = dataset.node_meta[i]
        reasons = _reason_codes(meta, prob)

        details = {
            "probability": round(prob, 6),
            "predicted_label": int(train_result.predicted_labels[i]),
            "model_version": model_version,
            "gnn_run_id": str(run.id),
            "source_backend": dataset.source_backend_used,
            "feature_dim": len(dataset.feature_matrix[i]),
        }

        pred = (
            db.query(AIPrediction)
            .filter(AIPrediction.entity_key == entity_key)
            .filter(AIPrediction.prediction_type == prediction_type)
            .filter(AIPrediction.window_key == dataset.window_key)
            .filter(AIPrediction.window_end == dataset.window_end)
            .first()
        )

        if pred:
            pred.score = score
            pred.reason_codes = reasons
            pred.details_json = details
            updated += 1
        else:
            pred = AIPrediction(
                entity_key=entity_key,
                entity_type=dataset.entity_types[i],
                prediction_type=prediction_type,
                window_key=dataset.window_key,
                window_end=dataset.window_end,
                score=score,
                reason_codes=reasons,
                details_json=details,
            )
            db.add(pred)
            db.flush()
            created += 1

        evidence_hashes: List[str] = []
        if prob >= 0.5:
            evidence_hashes = _event_hashes(
                db,
                entity_key=entity_key,
                window_start=dataset.window_start,
                window_end=dataset.window_end,
                limit=20,
            )

        expl = db.query(AIExplanation).filter(AIExplanation.prediction_id == pred.id).first()
        expl_payload = {
            "window_start": dataset.window_start.isoformat(),
            "window_end": dataset.window_end.isoformat(),
            "gnn_run_id": str(run.id),
            "probability": round(prob, 6),
        }
        if expl:
            expl.reason_codes = reasons
            expl.evidence_hashes = evidence_hashes
            expl.evidence_paths = []
            expl.details_json = expl_payload
        else:
            db.add(
                AIExplanation(
                    prediction_id=pred.id,
                    reason_codes=reasons,
                    evidence_hashes=evidence_hashes,
                    evidence_paths=[],
                    details_json=expl_payload,
                )
            )

    db.commit()

    return {
        "status": "ok",
        "gnn_run_id": str(run.id),
        "window_key": dataset.window_key,
        "window_end": dataset.window_end.isoformat(),
        "nodes": len(dataset.entity_keys),
        "edges": len(dataset.edges),
        "source_backend": dataset.source_backend_used,
        "embeddings_upserted": embeddings_upserted,
        "predictions_created": created,
        "predictions_updated": updated,
        "metrics": train_result.metrics,
        "artifact_path": artifact_path,
    }


def main() -> None:
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--window-key", default=settings.gnn_window_key)
    p.add_argument("--window-end", default=None, help="ISO timestamp override")
    p.add_argument("--edge-backend", default=settings.gnn_edge_backend, choices=["postgres", "neo4j", "hybrid"])
    p.add_argument("--max-entities", type=int, default=settings.gnn_max_entities)
    p.add_argument("--max-edges", type=int, default=settings.gnn_max_edges)
    p.add_argument("--min-edge-weight", type=int, default=settings.gnn_min_edge_weight)
    p.add_argument("--epochs", type=int, default=settings.gnn_epochs)
    p.add_argument("--hidden-dim", type=int, default=settings.gnn_hidden_dim)
    p.add_argument("--embed-dim", type=int, default=settings.gnn_embed_dim)
    p.add_argument("--dropout", type=float, default=settings.gnn_dropout)
    p.add_argument("--learning-rate", type=float, default=settings.gnn_learning_rate)
    p.add_argument("--weight-decay", type=float, default=settings.gnn_weight_decay)
    p.add_argument("--seed", type=int, default=settings.gnn_seed)
    p.add_argument("--model-version", default=settings.gnn_model_version)
    p.add_argument("--prediction-type", default=settings.gnn_prediction_type)
    p.add_argument("--artifact-dir", default=settings.gnn_artifact_dir)
    args = p.parse_args()

    if not settings.gnn_enabled:
        print(json.dumps({"status": "disabled", "detail": "GNN_ENABLED=false"}))
        return

    window_end = None
    if args.window_end:
        window_end = datetime.fromisoformat(args.window_end.replace("Z", "+00:00"))

    db = SessionLocal()
    try:
        out = run_once(
            db=db,
            window_key=args.window_key,
            window_end=window_end,
            edge_backend=args.edge_backend,
            max_entities=args.max_entities,
            max_edges=args.max_edges,
            min_edge_weight=args.min_edge_weight,
            epochs=args.epochs,
            hidden_dim=args.hidden_dim,
            embed_dim=args.embed_dim,
            dropout=args.dropout,
            learning_rate=args.learning_rate,
            weight_decay=args.weight_decay,
            seed=args.seed,
            model_version=args.model_version,
            prediction_type=args.prediction_type,
            artifact_dir=args.artifact_dir,
        )
        print(json.dumps(out))
    finally:
        db.close()


if __name__ == "__main__":
    main()

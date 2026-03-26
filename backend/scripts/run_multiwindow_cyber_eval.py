from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import desc

from app.analytics.ai_models import GraphFeatureSnapshot
from app.analytics.layer3.gnn_backbone import load_dataset
from app.analytics.layer3.gnn_train_worker import run_once
from app.ledger.db import SessionLocal


def _candidate_windows(
    *,
    window_key: str,
    max_scan: int,
    max_entities: int,
    max_edges: int,
    min_edge_weight: int,
    edge_backend: str,
    minimum_negative_count: int,
    minimum_negative_ratio: float,
    negative_multiplier: float,
) -> list[dict[str, Any]]:
    db = SessionLocal()
    try:
        rows = (
            db.query(GraphFeatureSnapshot.window_end)
            .filter(GraphFeatureSnapshot.window_key == window_key)
            .distinct()
            .order_by(desc(GraphFeatureSnapshot.window_end))
            .limit(max_scan)
            .all()
        )
        candidates: list[dict[str, Any]] = []
        for (window_end,) in rows:
            dataset = load_dataset(
                db,
                window_key=window_key,
                window_end=window_end,
                max_entities=max_entities,
                max_edges=max_edges,
                min_edge_weight=min_edge_weight,
                edge_backend=edge_backend,
                min_negative_count=minimum_negative_count,
                min_negative_ratio=minimum_negative_ratio,
                negative_multiplier=negative_multiplier,
                benchmark_window_candidates=1,
            )
            selection = dict(dataset.selection_metadata or {})
            readiness = dict(selection.get("benchmark_readiness") or {})
            candidates.append(
                {
                    "window_key": window_key,
                    "window_end": window_end.isoformat(),
                    "node_count": len(dataset.entity_keys),
                    "edge_count": len(dataset.edges),
                    "positive_count": int(dataset.positive_count),
                    "negative_count": int(dataset.negative_count),
                    "benign_negative_count": int(dataset.benign_negative_count),
                    "benchmarkable": bool(readiness.get("benchmarkable")),
                    "benchmark_reasons": list(readiness.get("reasons") or []),
                    "scientific_score": float(selection.get("selected_scientific_score") or selection.get("scientific_score") or 0.0),
                    "positive_ratio": readiness.get("positive_ratio"),
                    "balance_ratio": readiness.get("balance_ratio"),
                    "real_ratio": float(((selection.get("provenance") or {}).get("real_ratio")) or 0.0),
                }
            )
        candidates.sort(
            key=lambda item: (
                1 if item["benchmarkable"] else 0,
                float(item["scientific_score"]),
                int(item["negative_count"]),
                int(item["node_count"]),
                str(item["window_end"]),
            ),
            reverse=True,
        )
        deduped: list[dict[str, Any]] = []
        seen_signatures: set[tuple[Any, ...]] = set()
        for item in candidates:
            signature = (
                int(item["node_count"]),
                int(item["edge_count"]),
                int(item["positive_count"]),
                int(item["negative_count"]),
                int(item["benign_negative_count"]),
                round(float(item["scientific_score"]), 3),
            )
            if signature in seen_signatures:
                continue
            seen_signatures.add(signature)
            deduped.append(item)
        return deduped
    finally:
        db.close()


def _run_window(
    *,
    window_key: str,
    window_end: datetime,
    epochs: int,
    model_version: str,
    prediction_type: str,
    max_entities: int,
    max_edges: int,
    min_edge_weight: int,
    edge_backend: str,
    minimum_negative_count: int,
    minimum_negative_ratio: float,
    negative_multiplier: float,
) -> dict[str, Any]:
    db = SessionLocal()
    try:
        return run_once(
            db=db,
            window_key=window_key,
            window_end=window_end,
            epochs=epochs,
            model_version=model_version,
            prediction_type=prediction_type,
            max_entities=max_entities,
            max_edges=max_edges,
            min_edge_weight=min_edge_weight,
            edge_backend=edge_backend,
            minimum_negative_count=minimum_negative_count,
            minimum_negative_ratio=minimum_negative_ratio,
            negative_multiplier=negative_multiplier,
            benchmark_window_candidates=1,
        )
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Train Sentinel-KE cyber GNN across several benchmarkable windows.")
    parser.add_argument("--window-key", default="Wmid")
    parser.add_argument("--prediction-type", default="risk_gnn")
    parser.add_argument("--model-version", default="gnn-sage-v1")
    parser.add_argument("--max-scan", type=int, default=12)
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--epochs", type=int, default=8)
    parser.add_argument("--max-entities", type=int, default=2000)
    parser.add_argument("--max-edges", type=int, default=50000)
    parser.add_argument("--min-edge-weight", type=int, default=1)
    parser.add_argument("--edge-backend", default="hybrid")
    parser.add_argument("--minimum-negative-count", type=int, default=20)
    parser.add_argument("--minimum-negative-ratio", type=float, default=0.15)
    parser.add_argument("--negative-multiplier", type=float, default=1.5)
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    candidates = _candidate_windows(
        window_key=args.window_key,
        max_scan=max(1, args.max_scan),
        max_entities=args.max_entities,
        max_edges=args.max_edges,
        min_edge_weight=args.min_edge_weight,
        edge_backend=args.edge_backend,
        minimum_negative_count=args.minimum_negative_count,
        minimum_negative_ratio=args.minimum_negative_ratio,
        negative_multiplier=args.negative_multiplier,
    )
    selected = candidates[: max(1, args.top_k)]
    training_order = list(reversed(selected))
    runs: list[dict[str, Any]] = []
    for candidate in training_order:
        result = _run_window(
            window_key=args.window_key,
            window_end=datetime.fromisoformat(str(candidate["window_end"])),
            epochs=args.epochs,
            model_version=args.model_version,
            prediction_type=args.prediction_type,
            max_entities=args.max_entities,
            max_edges=args.max_edges,
            min_edge_weight=args.min_edge_weight,
            edge_backend=args.edge_backend,
            minimum_negative_count=args.minimum_negative_count,
            minimum_negative_ratio=args.minimum_negative_ratio,
            negative_multiplier=args.negative_multiplier,
        )
        runs.append(
            {
                "window_end": candidate["window_end"],
                "scientific_score": candidate["scientific_score"],
                "benchmarkable": candidate["benchmarkable"],
                "result": result,
            }
        )

    payload = {
        "window_key": args.window_key,
        "prediction_type": args.prediction_type,
        "model_version": args.model_version,
        "candidate_count": len(candidates),
        "selected_count": len(selected),
        "selected_windows": selected,
        "runs": runs,
    }
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
select_training_window.py
=========================

Recommend the best real-data-backed training window for the cyber and
corruption GNNs without changing training semantics.

The selector scores existing feature-store windows by:
- node coverage
- negative coverage
- benign-negative coverage
- edge coverage
- real-signal ratio

This is intentionally lightweight. It is a planning/helper script, not a
trainer.
"""
from __future__ import annotations

import argparse
import json
import os
import math
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Sequence

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import app.db.registry  # noqa: F401 - register ORM models

from app.analytics.ai_models import GraphFeatureSnapshot
from app.analytics.corruption.train_worker import _load_corruption_dataset
from app.analytics.layer3.gnn_backbone import GNNDataset, load_dataset
from app.ledger.db import SessionLocal


@dataclass
class WindowCandidate:
    window_end: str
    nodes: int
    edges: int
    positives: int
    negatives: int
    benign_negatives: int
    real_ratio: float
    positive_ratio: float
    balance_ratio: float
    label_source_mix: dict[str, int]
    score: float
    scientific_score: float
    eligible: bool
    demo_worthy: bool
    reason: str


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _candidate_window_ends(db, *, window_key: str, limit: int) -> list[datetime]:
    rows = (
        db.query(GraphFeatureSnapshot.window_end)
        .filter(GraphFeatureSnapshot.window_key == window_key)
        .filter(GraphFeatureSnapshot.window_end.isnot(None))
        .distinct()
        .order_by(GraphFeatureSnapshot.window_end.desc())
        .limit(max(1, limit))
        .all()
    )
    return [row[0] for row in rows if row and row[0] is not None]


def _real_ratio(dataset: GNNDataset) -> float:
    values: list[float] = []
    for meta in dataset.node_meta or []:
        try:
            values.append(float((meta or {}).get("real_signal_ratio") or 0.0))
        except Exception:  # noqa: BLE001
            continue
    if not values:
        return 0.0
    return round(sum(values) / float(len(values)), 6)


def _label_source_mix(dataset: GNNDataset) -> dict[str, int]:
    out: dict[str, int] = {}
    for meta in dataset.node_meta or []:
        source = str((meta or {}).get("label_source") or "unknown")
        out[source] = out.get(source, 0) + 1
    return out


def _score_dataset(
    dataset: GNNDataset,
    *,
    min_nodes: int,
    min_negatives: int,
    min_real_ratio: float,
) -> WindowCandidate:
    nodes = int(len(dataset.entity_keys))
    edges = int(len(dataset.edges))
    positives = int(dataset.positive_count)
    negatives = int(dataset.negative_count)
    benign_negatives = int(dataset.benign_negative_count)
    real_ratio = _real_ratio(dataset)
    label_mix = _label_source_mix(dataset)
    positive_ratio = round(float(positives / max(1, nodes)), 6)
    balance_ratio = round(float(min(positives, negatives) / max(1, nodes)), 6)

    eligible = (
        nodes >= min_nodes
        and negatives >= min_negatives
        and real_ratio >= min_real_ratio
    )

    balance = balance_ratio
    scientific_score = (
        (18.0 * balance)
        + (4.5 * math.log1p(max(1, nodes)))
        + (1.8 * math.log1p(max(0, edges)))
        + (1.2 * math.log1p(max(1, negatives)))
        + (0.8 * math.log1p(max(1, benign_negatives)))
        + (7.5 * real_ratio)
        - (10.0 * abs(positives - negatives) / float(max(1, nodes)))
    )
    score = (
        scientific_score
        + (2.0 * nodes)
        + (1.0 * negatives)
        + (0.5 * benign_negatives)
        + (0.1 * edges)
    )

    reason = "eligible" if eligible else "below_floor"
    if nodes < min_nodes:
        reason = f"nodes<{min_nodes}"
        score -= 1000.0
    elif negatives < min_negatives:
        reason = f"negatives<{min_negatives}"
        score -= 1000.0
    elif real_ratio < min_real_ratio:
        reason = f"real_ratio<{min_real_ratio:.2f}"
        score -= 250.0

    demo_worthy = eligible and score >= 100.0

    return WindowCandidate(
        window_end="",
        nodes=nodes,
        edges=edges,
        positives=positives,
        negatives=negatives,
        benign_negatives=benign_negatives,
        real_ratio=round(real_ratio, 6),
        positive_ratio=positive_ratio,
        balance_ratio=balance_ratio,
        label_source_mix=label_mix,
        score=round(score, 3),
        scientific_score=round(scientific_score, 3),
        eligible=eligible,
        demo_worthy=demo_worthy,
        reason=reason,
    )


def _evaluate_domain(
    db,
    *,
    domain: str,
    window_key: str,
    max_candidates: int,
    min_nodes: int,
    min_negatives: int,
    min_real_ratio: float,
    max_entities: int,
    max_edges: int,
    min_edge_weight: int,
    negative_multiplier: float,
) -> dict[str, Any]:
    window_ends = _candidate_window_ends(db, window_key=window_key, limit=max_candidates)
    if not window_ends:
        return {
            "domain": domain,
            "window_key": window_key,
            "selected": None,
            "candidates": [],
            "status": "no_windows",
        }

    candidates: list[WindowCandidate] = []
    for window_end in window_ends:
        try:
            if domain == "corruption":
                dataset = _load_corruption_dataset(
                    db,
                    window_key=window_key,
                    window_end=window_end,
                    max_entities=max_entities,
                    max_edges=max_edges,
                    min_edge_weight=min_edge_weight,
                    negative_multiplier=negative_multiplier,
                )
            else:
                dataset = load_dataset(
                    db,
                    window_key=window_key,
                    window_end=window_end,
                    max_entities=max_entities,
                    edge_backend="hybrid",
                    min_edge_weight=min_edge_weight,
                    max_edges=max_edges,
                    negative_multiplier=negative_multiplier,
                )
        except Exception as exc:  # noqa: BLE001
            candidates.append(
                WindowCandidate(
                    window_end=window_end.isoformat(),
                    nodes=0,
                    edges=0,
                    positives=0,
                    negatives=0,
                    benign_negatives=0,
                    real_ratio=0.0,
                    label_source_mix={"error": 1},
                    score=-9999.0,
                    eligible=False,
                    demo_worthy=False,
                    reason=f"load_error:{exc}",
                )
            )
            continue

        if dataset is None:
            candidates.append(
                WindowCandidate(
                    window_end=window_end.isoformat(),
                    nodes=0,
                    edges=0,
                    positives=0,
                    negatives=0,
                    benign_negatives=0,
                    real_ratio=0.0,
                    label_source_mix={},
                    score=-9999.0,
                    eligible=False,
                    demo_worthy=False,
                    reason="empty_dataset",
                )
            )
            continue

        candidate = _score_dataset(
            dataset,
            min_nodes=min_nodes,
            min_negatives=min_negatives,
            min_real_ratio=min_real_ratio,
        )
        candidate.window_end = window_end.isoformat()
        candidates.append(candidate)

    candidates.sort(
        key=lambda c: (
            c.score,
            c.scientific_score,
            c.nodes,
            c.negatives,
            c.real_ratio,
        ),
        reverse=True,
    )
    selected = candidates[0] if candidates else None
    return {
        "domain": domain,
        "window_key": window_key,
        "selected": asdict(selected) if selected else None,
        "candidates": [asdict(candidate) for candidate in candidates[: max(1, min(10, len(candidates)))]],
        "status": "ok" if selected else "no_selection",
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Select the best real-data-backed GNN training window")
    parser.add_argument("--domain", choices=["both", "cyber", "corruption"], default="both")
    parser.add_argument("--cyber-window-key", default="Wmid")
    parser.add_argument("--corruption-window-key", default="Wcorruption")
    parser.add_argument("--max-candidates", type=int, default=12)
    parser.add_argument("--max-entities", type=int, default=2000)
    parser.add_argument("--max-edges", type=int, default=50000)
    parser.add_argument("--min-edge-weight", type=int, default=1)
    parser.add_argument("--negative-multiplier", type=float, default=1.5)
    parser.add_argument("--min-nodes", type=int, default=50)
    parser.add_argument("--min-negatives", type=int, default=20)
    parser.add_argument("--min-real-ratio", type=float, default=0.3)
    parser.add_argument("--out", default="", help="Optional JSON output path")
    args = parser.parse_args(argv)

    db = SessionLocal()
    try:
        payload: dict[str, Any] = {
            "checked_at": _utcnow(),
            "parameters": {
                "domain": args.domain,
                "max_candidates": args.max_candidates,
                "max_entities": args.max_entities,
                "max_edges": args.max_edges,
                "min_edge_weight": args.min_edge_weight,
                "negative_multiplier": args.negative_multiplier,
                "min_nodes": args.min_nodes,
                "min_negatives": args.min_negatives,
                "min_real_ratio": args.min_real_ratio,
            },
        }
        if args.domain in {"both", "cyber"}:
            payload["cyber"] = _evaluate_domain(
                db,
                domain="cyber",
                window_key=args.cyber_window_key,
                max_candidates=args.max_candidates,
                min_nodes=args.min_nodes,
                min_negatives=args.min_negatives,
                min_real_ratio=args.min_real_ratio,
                max_entities=args.max_entities,
                max_edges=args.max_edges,
                min_edge_weight=args.min_edge_weight,
                negative_multiplier=args.negative_multiplier,
            )
        if args.domain in {"both", "corruption"}:
            payload["corruption"] = _evaluate_domain(
                db,
                domain="corruption",
                window_key=args.corruption_window_key,
                max_candidates=args.max_candidates,
                min_nodes=args.min_nodes,
                min_negatives=args.min_negatives,
                min_real_ratio=args.min_real_ratio,
                max_entities=args.max_entities,
                max_edges=args.max_edges,
                min_edge_weight=args.min_edge_weight,
                negative_multiplier=args.negative_multiplier,
            )
    finally:
        db.close()

    print(json.dumps(payload, indent=2, default=str))
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

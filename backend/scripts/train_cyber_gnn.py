#!/usr/bin/env python3
"""
train_cyber_gnn.py — Train Sentinel-KE Cyber GNN on real event data
=====================================================================
Trains on window_key="Wmid" (7-day medium window) by default.
Uses temporal holdout, negative floor enforcement, label ladder metadata.

Usage:
    cd backend
    DATABASE_URL=... python scripts/train_cyber_gnn.py
    DATABASE_URL=... python scripts/train_cyber_gnn.py --window-key Wlong

Expected output: AUC > 0.85 with temporal holdout
Results written to: artifacts/gnn/cyber_train_result.json
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import app.db.registry  # noqa: F401

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("train_cyber_gnn")

ARTIFACT_PATH = Path(__file__).parent.parent / "artifacts" / "gnn" / "cyber_train_result.json"


def _print_summary(result: dict) -> None:
    """Print a human-readable training summary to stdout."""
    status = result.get("status", "unknown")
    print()
    print("=" * 60)
    print("  Sentinel-KE  |  CYBER GNN Training Summary")
    print("=" * 60)
    print(f"  Status       : {status.upper()}")

    if status == "ok":
        metrics = result.get("metrics") or {}
        auc = metrics.get("val_auc") or metrics.get("auc") or metrics.get("test_auc")
        print(f"  AUC          : {auc:.4f}" if auc is not None else "  AUC          : n/a")
        print(f"  Window key   : {result.get('window_key', 'n/a')}")
        print(f"  Nodes        : {result.get('nodes', 'n/a')}")
        print(f"  Edges        : {result.get('edges', 'n/a')}")
        print(f"  Positives    : {result.get('positive_count', 'n/a')}")
        print(f"  Negatives    : {result.get('negative_count', 'n/a')}")

        # Label ladder
        label_ladder = result.get("label_ladder") or {}
        tier_counts = label_ladder.get("tier_counts") or {}
        if tier_counts:
            print()
            print("  Label Ladder Breakdown:")
            for tier, count in sorted(tier_counts.items()):
                print(f"    {tier:<10}: {count}")
            dominant = label_ladder.get("dominant_tier", "unknown")
            ground_truth = label_ladder.get("tier_counts", {}).get("gold", 0) > 0
            print(f"    dominant   : {dominant}")
            print(f"    gold-backed: {'yes' if ground_truth else 'no'}")

        # Gates
        print()
        print("  Governance Gates:")
        fairness_override = result.get("fairness_gate_override_applied", False)
        real_data_passed = result.get("real_data_gate_passed", False)
        real_data_override = result.get("real_data_gate_override_applied", False)
        print(f"    fairness_gate   : {'OVERRIDE' if fairness_override else 'PASSED'}")
        print(f"    real_data_gate  : {'PASSED' if real_data_passed else ('OVERRIDE' if real_data_override else 'FAILED')}")
        print(f"  Benchmarkable    : {result.get('benchmarkable', False)}")

    elif status == "blocked":
        gate = result.get("gate", "unknown")
        print(f"  Blocked by gate  : {gate}")
        print(f"  Detail           : {result.get('detail', '')}")
        label_ladder = result.get("label_ladder") or {}
        tier_counts = label_ladder.get("tier_counts") or {}
        if tier_counts:
            print()
            print("  Label Ladder at block time:")
            for tier, count in sorted(tier_counts.items()):
                print(f"    {tier:<10}: {count}")

    elif status in ("no_data", "no_features"):
        print(f"  Detail: {result.get('message', status)}")

    elif status == "error":
        print(f"  Stage  : {result.get('stage', 'unknown')}")
        print(f"  Detail : {result.get('detail', '')}")

    print("=" * 60)
    print()


def main() -> None:
    p = argparse.ArgumentParser(description="Train Sentinel-KE Cyber GNN")
    p.add_argument(
        "--window-key",
        default="Wmid",
        help='Graph feature snapshot window key (default: "Wmid")',
    )
    p.add_argument(
        "--prediction-type",
        default="risk_gnn",
        help='Prediction type written to AIPrediction (default: "risk_gnn")',
    )
    p.add_argument(
        "--artifact-dir",
        default=str(Path(__file__).parent.parent / "artifacts" / "gnn"),
        help="Directory for .pt model artifacts",
    )
    p.add_argument(
        "--allow-demo-fairness-override",
        action="store_true",
        default=False,
        help="Bypass fairness governance gate (demo mode only)",
    )
    p.add_argument(
        "--allow-demo-real-data-override",
        action="store_true",
        default=False,
        help="Bypass real-data governance gate (demo mode only)",
    )
    p.add_argument("--epochs", type=int, default=60)
    p.add_argument("--edge-backend", default="hybrid", choices=["postgres", "neo4j", "hybrid"])
    args = p.parse_args()

    # Import here so sys.path insert above takes effect first
    from app.analytics.layer3.gnn_train_worker import run_once
    from app.ledger.db import SessionLocal

    db = SessionLocal()
    result: dict
    try:
        result = run_once(
            db=db,
            window_key=args.window_key,
            prediction_type=args.prediction_type,
            artifact_dir=args.artifact_dir,
            edge_backend=args.edge_backend,
            epochs=args.epochs,
            allow_demo_fairness_override=args.allow_demo_fairness_override,
            allow_demo_real_data_override=args.allow_demo_real_data_override,
        )
    finally:
        db.close()

    _print_summary(result)

    # Persist result to JSON artifact
    out_path = ARTIFACT_PATH
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as fh:
        json.dump(result, fh, indent=2, default=str)
    log.info("cyber_train_result written to %s", out_path)

    # Exit 1 if training was blocked or errored
    if result.get("status") in ("blocked", "error"):
        sys.exit(1)


if __name__ == "__main__":
    main()

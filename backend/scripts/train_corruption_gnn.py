#!/usr/bin/env python3
"""
train_corruption_gnn.py — Train Sentinel-KE Corruption GNN
===========================================================
Trains on window_key="Wcorruption" using PPRA + Kenya Law + EACC data.
Uses allow_demo_fairness_override=True for demo runs.

Usage:
    cd backend
    DATABASE_URL=... python scripts/train_corruption_gnn.py
    DATABASE_URL=... python scripts/train_corruption_gnn.py --strict  # no override

Results written to: artifacts/gnn/corruption_train_result.json
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
log = logging.getLogger("train_corruption_gnn")

ARTIFACT_PATH = (
    Path(__file__).parent.parent / "artifacts" / "gnn" / "corruption_train_result.json"
)

# Recommended fixes keyed by entity type for high-disparity guidance
_DISPARITY_FIX_HINTS: dict[str, str] = {
    "official":    "Collect more labelled procurement events for public officials.",
    "company":     "Expand PPRA debarment list import; cross-reference county spending data.",
    "contractor":  "Add EACC contractor watchlist; ingest Kenya Gazette sanctions.",
    "procurement": "Re-balance procurement award labels using PPRA open-data API.",
    "tender":      "Seed gold labels from Kenya Law supply-chain judgments.",
}
_DEFAULT_FIX = (
    "Balance entity-type label distribution before retraining: "
    "add labelled samples for the entity type with highest positive-rate disparity."
)


def _highest_disparity_entity(fairness_per_type: dict) -> tuple[str, float]:
    """Return (entity_type, disparity) for the type with the largest positive rate."""
    best_type = ""
    best_rate = -1.0
    for entity_type, stats in fairness_per_type.items():
        rate = float(stats.get("positive_rate") or 0.0)
        if rate > best_rate:
            best_rate = rate
            best_type = entity_type
    return best_type, best_rate


def _print_summary(result: dict) -> None:
    """Print a human-readable training summary to stdout."""
    status = result.get("status", "unknown")
    print()
    print("=" * 60)
    print("  Sentinel-KE  |  CORRUPTION GNN Training Summary")
    print("=" * 60)
    print(f"  Status       : {status.upper()}")

    if status == "ok":
        metrics = result.get("metrics") or {}
        auc = metrics.get("val_auc") or metrics.get("auc") or metrics.get("test_auc")
        print(f"  AUC          : {auc:.4f}" if auc is not None else "  AUC          : n/a")
        print(f"  Window key   : {result.get('window_key', 'n/a')}")
        print(f"  Domain       : {result.get('domain', 'corruption')}")
        print(f"  Nodes        : {result.get('nodes', 'n/a')}")
        print(f"  Edges        : {result.get('edges', 'n/a')}")
        print(f"  Positives    : {result.get('positive_count', 'n/a')}")
        print(f"  Negatives    : {result.get('negative_count', 'n/a')}")
        print(f"  Predictions  : {result.get('predictions', 'n/a')}")

        # Fairness status
        override_applied = result.get("fairness_gate_override_applied", False)
        real_data_passed = result.get("real_data_gate_passed", False)
        real_data_override = result.get("real_data_gate_override_applied", False)
        print()
        print("  Fairness / Governance:")
        print(f"    fairness_gate   : {'OVERRIDE APPLIED' if override_applied else 'PASSED'}")
        print(f"    real_data_gate  : {'PASSED' if real_data_passed else ('OVERRIDE' if real_data_override else 'FAILED')}")
        print(f"  Benchmarkable    : {result.get('benchmarkable', False)}")

    elif status == "blocked":
        gate = result.get("gate", "unknown")
        print(f"  Blocked by gate  : {gate}")
        print(f"  Detail           : {result.get('detail', '')}")

        if gate == "fairness":
            disparity = result.get("max_positive_rate_disparity")
            threshold = result.get("threshold")
            if disparity is not None:
                print(f"  Max disparity    : {disparity:.4f}  (threshold: {threshold})")

            # Pull per-type breakdown from result if present
            per_type = result.get("fairness_per_type") or {}
            if per_type:
                print()
                print("  Entity-type positive rates:")
                for et, stats in sorted(per_type.items()):
                    rate = stats.get("positive_rate", 0.0)
                    n = stats.get("n", 0)
                    print(f"    {et:<20}: rate={rate:.3f}  n={n}")
                bad_type, bad_rate = _highest_disparity_entity(per_type)
                if bad_type:
                    fix = _DISPARITY_FIX_HINTS.get(bad_type, _DEFAULT_FIX)
                    print()
                    print(f"  Highest disparity entity type : {bad_type} (rate={bad_rate:.3f})")
                    print(f"  Recommended fix : {fix}")
            else:
                print()
                print(f"  Recommended fix : {_DEFAULT_FIX}")

    elif status in ("no_data", "no_features"):
        print(f"  Detail: {result.get('message', status)}")
        print("  Hint  : Run synthetic_corruption_data or ingest PPRA/EACC data first.")

    elif status == "error":
        print(f"  Stage  : {result.get('stage', 'unknown')}")
        print(f"  Detail : {result.get('detail', '')}")

    print("=" * 60)
    print()


def main() -> None:
    p = argparse.ArgumentParser(description="Train Sentinel-KE Corruption GNN")
    p.add_argument(
        "--window-key",
        default="Wcorruption",
        help='Graph feature snapshot window key (default: "Wcorruption")',
    )
    p.add_argument(
        "--strict",
        action="store_true",
        default=False,
        help="Disable demo fairness override — block if fairness gate fails (production mode)",
    )
    p.add_argument(
        "--artifact-dir",
        default=str(Path(__file__).parent.parent / "artifacts" / "gnn"),
        help="Directory for .pt model artifacts",
    )
    p.add_argument("--epochs", type=int, default=60)
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()

    # Import after sys.path setup
    from app.analytics.corruption.train_worker import run_once
    from app.ledger.db import SessionLocal

    # Default: allow_demo_fairness_override=True for demo runs
    # --strict disables both overrides (production-safe mode)
    allow_fairness_override = not args.strict
    allow_real_data_override = not args.strict

    db = SessionLocal()
    result: dict
    try:
        result = run_once(
            db=db,
            window_key=args.window_key,
            artifact_dir=args.artifact_dir,
            epochs=args.epochs,
            seed=args.seed,
            allow_demo_fairness_override=allow_fairness_override,
            allow_demo_real_data_override=allow_real_data_override,
        )
    finally:
        db.close()

    _print_summary(result)

    # Persist result to JSON artifact
    out_path = ARTIFACT_PATH
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as fh:
        json.dump(result, fh, indent=2, default=str)
    log.info("corruption_train_result written to %s", out_path)

    # Exit 1 if blocked or errored
    if result.get("status") in ("blocked", "error"):
        sys.exit(1)


if __name__ == "__main__":
    main()

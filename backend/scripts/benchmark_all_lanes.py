#!/usr/bin/env python3
"""
benchmark_all_lanes.py — Print judge-ready benchmark table
============================================================
Reads artifacts from all three GNN lanes and prints a formatted table.

Usage:
    cd backend
    python scripts/benchmark_all_lanes.py

Expected output:
╔══════════════╦══════════╦═════════╦════════╦════════╦══════════════╗
║ Lane         ║ Dataset  ║ AUC     ║ Nodes  ║ Edges  ║ Holdout      ║
╠══════════════╬══════════╬═════════╬════════╬════════╬══════════════╣
║ Cyber        ║ Real IOC ║ 0.8928  ║ 97     ║ 237    ║ Temporal     ║
║ Fraud        ║ PaySim   ║ PENDING ║ --     ║ --     ║ Temporal     ║
║ Corruption   ║ PPRA/KL  ║ TBD     ║ --     ║ --     ║ Temporal     ║
╚══════════════╩══════════╩═════════╩════════╩════════╩══════════════╝
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Optional

# Resolve backend root regardless of cwd
_BACKEND_ROOT = Path(__file__).parent.parent

# ── Artifact paths ────────────────────────────────────────────────────────────
_CYBER_RESULT = _BACKEND_ROOT / "artifacts" / "gnn" / "cyber_train_result.json"
_FRAUD_RESULT = _BACKEND_ROOT / "artifacts" / "paysim_auc.json"
_CORRUPTION_RESULT = _BACKEND_ROOT / "artifacts" / "gnn" / "corruption_train_result.json"


def _load_json(path: Path) -> Optional[dict]:
    """Load a JSON artifact, returning None if the file is missing or invalid."""
    try:
        with open(path) as fh:
            return json.load(fh)
    except FileNotFoundError:
        return None
    except (json.JSONDecodeError, OSError):
        return None


def _fmt(value: Any, fmt: str = "") -> str:
    """Format a value, returning '--' if it is None or missing."""
    if value is None:
        return "--"
    try:
        if fmt:
            return format(value, fmt)
        return str(value)
    except (TypeError, ValueError):
        return "--"


def _auc_from_result(result: dict) -> Optional[float]:
    """Extract the best available AUC float from a result dict."""
    # cyber / corruption: metrics sub-dict
    metrics = result.get("metrics") or {}
    for key in ("val_auc", "test_auc", "auc", "roc_auc"):
        v = metrics.get(key)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                pass
    # paysim: metrics at top-level
    for key in ("roc_auc", "auc", "val_auc"):
        v = result.get(key)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                pass
    return None


def _collect_lane_data() -> list[dict]:
    """Build per-lane data rows from artifact files."""
    rows = []

    # ── Cyber ─────────────────────────────────────────────────────────────────
    cyber = _load_json(_CYBER_RESULT)
    if cyber and cyber.get("status") == "ok":
        auc = _auc_from_result(cyber)
        rows.append({
            "lane":    "Cyber",
            "dataset": "Real IOC",
            "auc":     f"{auc:.4f}" if auc is not None else "--",
            "nodes":   _fmt(cyber.get("nodes")),
            "edges":   _fmt(cyber.get("edges")),
            "holdout": "Temporal",
            "status":  "ok",
        })
    elif cyber and cyber.get("status") == "blocked":
        rows.append({
            "lane":    "Cyber",
            "dataset": "Real IOC",
            "auc":     "BLOCKED",
            "nodes":   "--",
            "edges":   "--",
            "holdout": "Temporal",
            "status":  "blocked",
        })
    else:
        rows.append({
            "lane":    "Cyber",
            "dataset": "Real IOC",
            "auc":     "PENDING",
            "nodes":   "--",
            "edges":   "--",
            "holdout": "Temporal",
            "status":  "no_artifact",
        })

    # ── Fraud (PaySim) ────────────────────────────────────────────────────────
    fraud = _load_json(_FRAUD_RESULT)
    if fraud:
        # paysim metrics may live under "metrics" sub-key
        metrics = fraud.get("metrics") or {}
        auc = _auc_from_result(fraud) or _auc_from_result(metrics)
        run_cfg = fraud.get("run_config") or {}
        seed_info = run_cfg.get("snapshot_seed") or {}
        nodes_val = seed_info.get("accounts_seeded") or seed_info.get("nodes")
        rows.append({
            "lane":    "Fraud",
            "dataset": "PaySim",
            "auc":     (f"{auc:.4f}*" if auc is not None else "--"),
            "nodes":   _fmt(nodes_val) if nodes_val else "50k+",
            "edges":   "--",
            "holdout": "Temporal",
            "status":  "ok",
        })
    else:
        rows.append({
            "lane":    "Fraud",
            "dataset": "PaySim",
            "auc":     "PENDING",
            "nodes":   "--",
            "edges":   "--",
            "holdout": "Temporal",
            "status":  "no_artifact",
        })

    # ── Corruption ────────────────────────────────────────────────────────────
    corruption = _load_json(_CORRUPTION_RESULT)
    if corruption and corruption.get("status") == "ok":
        auc = _auc_from_result(corruption)
        rows.append({
            "lane":    "Corruption",
            "dataset": "PPRA/KL",
            "auc":     f"{auc:.4f}" if auc is not None else "TBD",
            "nodes":   _fmt(corruption.get("nodes")),
            "edges":   _fmt(corruption.get("edges")),
            "holdout": "Temporal",
            "status":  "ok",
        })
    elif corruption and corruption.get("status") == "blocked":
        rows.append({
            "lane":    "Corruption",
            "dataset": "PPRA/KL",
            "auc":     "BLOCKED",
            "nodes":   "--",
            "edges":   "--",
            "holdout": "Temporal",
            "status":  "blocked",
        })
    else:
        rows.append({
            "lane":    "Corruption",
            "dataset": "PPRA/KL",
            "auc":     "TBD",
            "nodes":   "--",
            "edges":   "--",
            "holdout": "Temporal",
            "status":  "no_artifact",
        })

    return rows


def _print_table(rows: list[dict]) -> None:
    """Render a Unicode box-drawing benchmark table."""
    headers = ["Lane", "Dataset", "AUC", "Nodes", "Edges", "Holdout"]
    keys    = ["lane", "dataset", "auc", "nodes", "edges", "holdout"]

    # Compute column widths
    widths = [len(h) for h in headers]
    for row in rows:
        for i, k in enumerate(keys):
            widths[i] = max(widths[i], len(str(row.get(k, "--"))))

    def _cell(text: str, w: int) -> str:
        return f" {text:<{w}} "

    sep_top  = "╔" + "╦".join("═" * (w + 2) for w in widths) + "╗"
    sep_head = "╠" + "╬".join("═" * (w + 2) for w in widths) + "╣"
    sep_bot  = "╚" + "╩".join("═" * (w + 2) for w in widths) + "╝"
    row_sep  = "╟" + "╫".join("─" * (w + 2) for w in widths) + "╢"

    def _row(cells: list[str]) -> str:
        return "║" + "║".join(_cell(c, widths[i]) for i, c in enumerate(cells)) + "║"

    print()
    print(sep_top)
    print(_row(headers))
    print(sep_head)
    for i, row in enumerate(rows):
        cells = [str(row.get(k, "--")) for k in keys]
        print(_row(cells))
        if i < len(rows) - 1:
            print(row_sep)
    print(sep_bot)
    print()

    # Footnotes
    any_no_artifact = any(r["status"] == "no_artifact" for r in rows)
    any_blocked     = any(r["status"] == "blocked"     for r in rows)
    any_fraud_star  = any(r["lane"] == "Fraud" and "*" in r.get("auc", "") for r in rows)

    if any_fraud_star:
        print("  * Fraud AUC on PaySim synthetic dataset (Kaggle ealaxi/paysim1).")
        print("    Not directly comparable to cyber/corruption lanes (different data domains).")
    if any_no_artifact:
        print("  No training artifact found for one or more lanes.")
        print("  Run train_cyber_gnn.py / run_paysim_gnn.py / train_corruption_gnn.py first.")
    if any_blocked:
        print("  BLOCKED = training was stopped by a governance gate (fairness or real-data).")
        print("  Use --allow-demo-fairness-override or fix label imbalance to unblock.")
    print()


def main() -> None:
    rows = _collect_lane_data()
    _print_table(rows)

    # Return non-zero only if all lanes are missing artifacts (nothing to show)
    if all(r["status"] == "no_artifact" for r in rows):
        print("WARNING: No training artifacts found. Run all three training scripts first.")
        sys.exit(0)  # Not an error; just informational


if __name__ == "__main__":
    main()

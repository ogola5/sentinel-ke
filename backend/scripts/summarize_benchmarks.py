#!/usr/bin/env python3
"""Summarize Sentinel-KE benchmark artifacts without overstating claims.

This helper is intentionally read-only. It classifies benchmark artifacts into:
- fraud / PaySim
- cyber
- corruption

and prints a concise summary of what each lane can honestly support.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


@dataclass(frozen=True)
class ArtifactSummary:
    path: Path
    kind: str
    title: str
    metrics: dict[str, Any]
    run_config: dict[str, Any]


def _load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise ValueError(f"{path} does not contain a JSON object")
    return data


def _extract_metrics(payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    if isinstance(payload.get("metrics"), dict):
        metrics = payload["metrics"]
    else:
        metrics = payload
    run_config = payload.get("run_config") if isinstance(payload.get("run_config"), dict) else {}
    return metrics, run_config


def _classify(path: Path, payload: dict[str, Any], run_config: dict[str, Any]) -> tuple[str, str]:
    dataset = str(payload.get("dataset", "")).lower()
    prediction_type = str(run_config.get("prediction_type", payload.get("prediction_type", ""))).lower()
    window_key = str(run_config.get("window_key", payload.get("window_key", ""))).lower()

    if "paysim" in dataset or "paysim" in path.name.lower():
        return "fraud", "PaySim"
    if prediction_type == "corruption_risk" or window_key == "wcorruption":
        return "corruption", "Corruption GNN"
    if prediction_type == "risk_gnn" or window_key == "wmid":
        return "cyber", "Cyber GNN"
    return "unknown", "Unclassified benchmark"


def _format_metric(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def _maybe_get(metrics: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in metrics and metrics[key] is not None:
            return metrics[key]
    return None


def summarize(path: Path) -> ArtifactSummary:
    payload = _load_json(path)
    metrics, run_config = _extract_metrics(payload)
    kind, title = _classify(path, payload, run_config)
    return ArtifactSummary(path=path, kind=kind, title=title, metrics=metrics, run_config=run_config)


def render(summary: ArtifactSummary) -> str:
    metrics = summary.metrics
    lines: list[str] = []
    lines.append(f"{summary.title}: {summary.path}")

    if summary.kind == "fraud":
        auc = _maybe_get(metrics, "roc_auc", "auc", "val_auc")
        auprc = _maybe_get(metrics, "auprc", "pr_auc", "average_precision")
        precision = _maybe_get(metrics, "precision")
        recall = _maybe_get(metrics, "recall")
        ece = _maybe_get(metrics, "ece", "calibration_ece")
        brier = _maybe_get(metrics, "brier_score", "brier")
        lines.append(f"  proves: fraud ranking quality on a public benchmark")
        if auc is not None:
            lines.append(f"  auc_roc: {_format_metric(auc)}")
        if auprc is not None:
            lines.append(f"  auprc: {_format_metric(auprc)}")
        if precision is not None or recall is not None:
            lines.append(f"  precision: {_format_metric(precision) if precision is not None else 'n/a'}")
            lines.append(f"  recall: {_format_metric(recall) if recall is not None else 'n/a'}")
        if ece is not None:
            lines.append(f"  calibration_ece: {_format_metric(ece)}")
        if brier is not None:
            lines.append(f"  brier_score: {_format_metric(brier)}")
        lines.append("  do_not_overstate: cyber performance, corruption performance, or production threshold quality")
    elif summary.kind == "cyber":
        auc = _maybe_get(metrics, "auc", "roc_auc", "val_auc")
        precision = _maybe_get(metrics, "precision")
        train_count = _maybe_get(metrics, "train_count")
        val_count = _maybe_get(metrics, "val_count")
        real_ratio = _maybe_get(metrics, "real_data_ratio", "real_ratio")
        label_sources = metrics.get("label_source_counts")
        lines.append("  proves: operational graph-risk learning on cyber telemetry")
        if auc is not None:
            lines.append(f"  auc_roc: {_format_metric(auc)}")
        if precision is not None:
            lines.append(f"  precision: {_format_metric(precision)}")
        if train_count is not None or val_count is not None:
            lines.append(f"  train_count: {_format_metric(train_count) if train_count is not None else 'n/a'}")
            lines.append(f"  val_count: {_format_metric(val_count) if val_count is not None else 'n/a'}")
        if real_ratio is not None:
            lines.append(f"  real_ratio: {_format_metric(real_ratio)}")
        if label_sources is not None:
            lines.append(f"  label_source_counts: {label_sources}")
        lines.append("  do_not_overstate: PaySim performance, corruption performance, or global readiness from one window")
    elif summary.kind == "corruption":
        auc = _maybe_get(metrics, "auc", "roc_auc", "val_auc")
        precision = _maybe_get(metrics, "precision")
        outcome_rate = _maybe_get(metrics, "outcome_label_rate")
        real_ratio = _maybe_get(metrics, "real_ratio")
        provenance = metrics.get("provenance")
        lines.append("  proves: procurement / registry / payment / outcome graph prioritization")
        if auc is not None:
            lines.append(f"  auc_roc: {_format_metric(auc)}")
        if precision is not None:
            lines.append(f"  precision: {_format_metric(precision)}")
        if outcome_rate is not None:
            lines.append(f"  outcome_label_rate: {_format_metric(outcome_rate)}")
        if real_ratio is not None:
            lines.append(f"  real_ratio: {_format_metric(real_ratio)}")
        if provenance is not None:
            lines.append(f"  provenance: {provenance}")
        lines.append("  do_not_overstate: final corruption findings or fraud benchmark claims")
    else:
        lines.append("  proves: inspect manually")

    return "\n".join(lines)


def _default_paths() -> list[Path]:
    candidates = [
        Path("backend/artifacts/paysim_auc.json"),
        Path("backend/artifacts/paysim_auc_full.json"),
        Path("backend/artifacts/operational_scalability_report.json"),
    ]
    return [path for path in candidates if path.exists()]


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Summarize Sentinel-KE benchmark artifacts")
    parser.add_argument(
        "--artifact",
        action="append",
        default=[],
        help="Path to a benchmark artifact JSON file. Repeat for multiple artifacts.",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    paths = [Path(p) for p in args.artifact] if args.artifact else _default_paths()
    if not paths:
        print("No benchmark artifacts found. Pass one or more --artifact paths.")
        return 1

    summaries = [summarize(path) for path in paths]

    print("Sentinel-KE benchmark summary")
    print("=" * 40)
    for summary in summaries:
        print(render(summary))
        print("-" * 40)

    print("Recommended narrative")
    print("  PaySim is the fraud benchmark lane.")
    print("  Cyber uses its own operational telemetry and real-data mix.")
    print("  Corruption uses its own procurement / registry / payment / outcome graph.")
    print("  Do not use one lane to claim the other lanes are solved.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

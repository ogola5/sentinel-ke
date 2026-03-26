#!/usr/bin/env python3
"""
run_inference_check.py — Sanity-check GNN inference without retraining.

Loads the latest saved .pt artifact for the cyber domain (prediction_type=risk_gnn,
window_key=Wmid by default), runs predict_mc on up to 10 sample entities drawn from
GraphFeatureSnapshot, and prints per-entity inference results.

Usage:
    cd backend
    DATABASE_URL=postgresql://... PYTHONPATH=. python scripts/run_inference_check.py

Optional env vars:
    PREDICTION_TYPE    (default: risk_gnn)
    WINDOW_KEY         (default: Wmid)
    ARTIFACT_DIR       (default: /app/artifacts/gnn or artifacts/gnn in repo root)
    MC_SAMPLES         (default: 20)
    SAMPLE_ENTITIES    (default: 10)
    ARTIFACT_PATH      explicit path to a .pt file (bypasses DB lookup)

Exit codes:
    0   inference succeeded
    1   no artifact found or inference failed
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure the backend package root is on sys.path when run as a plain script.
_here = Path(__file__).resolve().parent          # backend/scripts/
_backend_root = _here.parent                     # backend/
if str(_backend_root) not in sys.path:
    sys.path.insert(0, str(_backend_root))


def _require_torch():
    try:
        import torch  # noqa: PLC0415
        return torch
    except ImportError:
        print("ERROR: PyTorch is not installed. Install it with: pip install torch", file=sys.stderr)
        sys.exit(1)


def _resolve_artifact_path(prediction_type: str, window_key: str, artifact_dir: str) -> str | None:
    """
    Look up the latest .pt artifact path.

    Strategy:
    1. Check ARTIFACT_PATH env var (explicit override).
    2. Query DB via SQLAlchemy for GNNTrainingRun with matching prediction_type / window_key.
    3. Fall back to scanning artifact_dir for *.pt files (newest first).
    """
    # Explicit override
    explicit = os.environ.get("ARTIFACT_PATH", "").strip()
    if explicit:
        if Path(explicit).exists():
            return explicit
        print(f"WARNING: ARTIFACT_PATH={explicit!r} does not exist.", file=sys.stderr)

    # DB lookup
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if database_url:
        try:
            from sqlalchemy import create_engine, desc  # noqa: PLC0415
            from sqlalchemy.orm import Session  # noqa: PLC0415
            from app.core.env_contract import normalize_database_url  # noqa: PLC0415
            from app.analytics.ai_models import GNNTrainingRun  # noqa: PLC0415

            engine = create_engine(normalize_database_url(database_url))
            with Session(engine) as session:
                run = (
                    session.query(GNNTrainingRun)
                    .filter(GNNTrainingRun.prediction_type == prediction_type)
                    .filter(GNNTrainingRun.window_key == window_key)
                    .filter(GNNTrainingRun.artifact_path.isnot(None))
                    .order_by(desc(GNNTrainingRun.created_at))
                    .first()
                )
                if run and run.artifact_path and Path(str(run.artifact_path)).exists():
                    print(f"DB artifact: {run.artifact_path}  (run_id={run.id})")
                    return str(run.artifact_path)
                elif run and run.artifact_path:
                    print(
                        f"WARNING: DB artifact_path={run.artifact_path!r} not on disk.",
                        file=sys.stderr,
                    )
        except Exception as exc:  # noqa: BLE001
            print(f"WARNING: DB lookup failed — {exc}", file=sys.stderr)

    # Filesystem scan
    art_dir = Path(artifact_dir)
    if art_dir.is_dir():
        candidates = sorted(art_dir.glob("*.pt"), key=lambda p: p.stat().st_mtime, reverse=True)
        if candidates:
            path = str(candidates[0])
            print(f"Filesystem artifact (newest): {path}")
            return path

    return None


def _fetch_sample_snapshots(prediction_type: str, window_key: str, limit: int) -> list:
    """Return up to `limit` GraphFeatureSnapshot rows for the given window."""
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        return []

    try:
        from sqlalchemy import create_engine  # noqa: PLC0415
        from sqlalchemy.orm import Session  # noqa: PLC0415
        from app.core.env_contract import normalize_database_url  # noqa: PLC0415
        from app.analytics.ai_models import GraphFeatureSnapshot  # noqa: PLC0415

        engine = create_engine(normalize_database_url(database_url))
        with Session(engine) as session:
            snaps = (
                session.query(GraphFeatureSnapshot)
                .filter(GraphFeatureSnapshot.window_key == window_key)
                .order_by(GraphFeatureSnapshot.event_count.desc())
                .limit(limit)
                .all()
            )
            # Detach from session so we can use them after close
            return [
                {
                    "entity_key": s.entity_key,
                    "risk_flags": list(s.risk_flags or []),
                    "features": dict(s.features or {}),
                    "event_count": int(s.event_count or 0),
                }
                for s in snaps
            ]
    except Exception as exc:  # noqa: BLE001
        print(f"WARNING: GraphFeatureSnapshot query failed — {exc}", file=sys.stderr)
        return []


def _gnn_reason_code(prob: float, snap: dict) -> str:
    """Derive the top reason code for a scored entity (mirrors ai_inference_worker logic)."""
    flags = set(snap.get("risk_flags") or [])
    event_count = int(snap.get("event_count") or 0)
    features = dict(snap.get("features") or {})
    source_count = int(features.get("source_count") or 0)

    reasons: list[str] = []

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

    for flag in ("CAMPAIGN_ENTITY", "DDOS_CLUSTER_MEMBER", "VPN_CLUSTER_MEMBER", "AIRTIME_SIPHON_MEMBER"):
        if flag in flags:
            reasons.append(flag)

    return reasons[0] if reasons else "GNN_RISK_LOW"


def _synthetic_nodes(n: int, feat_dim: int) -> list[dict]:
    """Generate synthetic sample entities for smoke-test when DB is unavailable."""
    import random  # noqa: PLC0415
    rng = random.Random(42)
    nodes = []
    for i in range(n):
        nodes.append({
            "entity_key": f"synthetic:node:{i:04d}",
            "risk_flags": ["CAMPAIGN_ENTITY"] if i % 3 == 0 else [],
            "features": {"source_count": rng.randint(1, 5), "event_count": rng.randint(1, 50)},
            "event_count": rng.randint(1, 50),
        })
    return nodes


def main() -> int:
    prediction_type = os.environ.get("PREDICTION_TYPE", "risk_gnn")
    window_key = os.environ.get("WINDOW_KEY", "Wmid")
    artifact_dir = os.environ.get(
        "ARTIFACT_DIR",
        os.environ.get("GNN_ARTIFACT_DIR", str(_backend_root.parent / "artifacts" / "gnn")),
    )
    mc_samples = int(os.environ.get("MC_SAMPLES", "20"))
    sample_entities = int(os.environ.get("SAMPLE_ENTITIES", "10"))

    torch = _require_torch()

    print(f"=== Sentinel-KE GNN Inference Check ===")
    print(f"  prediction_type : {prediction_type}")
    print(f"  window_key      : {window_key}")
    print(f"  artifact_dir    : {artifact_dir}")
    print(f"  mc_samples      : {mc_samples}")
    print(f"  device          : {'cuda' if torch.cuda.is_available() else 'cpu'}")
    print()

    # Resolve artifact
    artifact_path = _resolve_artifact_path(prediction_type, window_key, artifact_dir)
    if not artifact_path:
        print("ERROR: No artifact found. Run training first or set ARTIFACT_PATH.", file=sys.stderr)
        print(
            "  Tip: python -m app.analytics.layer3.gnn_train_worker "
            "--window-key Wmid --prediction-type risk_gnn",
            file=sys.stderr,
        )
        return 1

    # Load model
    try:
        from app.analytics.layer3.gnn_model import load_model, predict_mc  # noqa: PLC0415
    except ImportError as exc:
        print(f"ERROR: Could not import gnn_model — {exc}", file=sys.stderr)
        return 1

    # load_model already uses map_location="cpu"; move to GPU if available
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    try:
        model, meta = load_model(artifact_path)
        model = model.to(device)
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: Failed to load artifact {artifact_path!r} — {exc}", file=sys.stderr)
        return 1

    feat_dim = int(meta.get("feature_dim") or meta.get("feat_dim") or 44)
    print(f"Artifact loaded: feat_dim={feat_dim}  hidden={meta.get('hidden_dim')}  "
          f"embed={meta.get('embed_dim')}  window_end={meta.get('window_end')}")
    print()

    # Fetch sample entities
    snaps = _fetch_sample_snapshots(prediction_type, window_key, sample_entities)
    if not snaps:
        print("No GraphFeatureSnapshot rows found in DB — using synthetic nodes for smoke-test.")
        snaps = _synthetic_nodes(sample_entities, feat_dim)

    # Build a tiny graph (no real edges — isolated node inference)
    import random  # noqa: PLC0415
    n = len(snaps)

    # Build feature matrix — use a zero vector of the right dim as fallback
    def _node_features(snap: dict) -> list[float]:
        feats = snap.get("features") or {}
        # If a flat feature list exists (from snapshot), use it
        feat_vec = feats.get("feature_vector") or feats.get("feature_vec")
        if feat_vec and len(feat_vec) == feat_dim:
            return [float(v) for v in feat_vec]
        # Minimal synthetic fill from available scalars
        vec = [0.0] * feat_dim
        if feat_dim > 10:
            import math  # noqa: PLC0415
            ec = int(snap.get("event_count") or 0)
            vec[10] = math.log1p(ec)                         # log event_count
            src = int((snap.get("features") or {}).get("source_count") or 0)
            vec[11] = math.log1p(src)
        return vec

    feature_matrix = [_node_features(s) for s in snaps]
    # Pad or truncate to feat_dim
    for i, row in enumerate(feature_matrix):
        if len(row) < feat_dim:
            feature_matrix[i] = row + [0.0] * (feat_dim - len(row))
        else:
            feature_matrix[i] = row[:feat_dim]

    x = torch.tensor(feature_matrix, dtype=torch.float32).to(device)
    # No edges for this isolated-node inference check
    edge_src = torch.zeros(0, dtype=torch.long, device=device)
    edge_dst = torch.zeros(0, dtype=torch.long, device=device)
    edge_weight = torch.zeros(0, dtype=torch.float32, device=device)

    # Run MC inference
    try:
        mean_probs, uncertainties = predict_mc(
            model, x, edge_src, edge_dst, edge_weight, n_samples=mc_samples
        )
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: predict_mc failed — {exc}", file=sys.stderr)
        return 1

    # Print results
    print(f"{'entity_key':<40}  {'risk_score':>10}  {'uncertainty':>12}  {'top_reason'}")
    print("-" * 90)
    for snap, prob, unc in zip(snaps, mean_probs, uncertainties):
        risk_score = round(float(prob) * 100, 2)
        uncertainty = round(float(unc), 4)
        reason = _gnn_reason_code(float(prob), snap)
        entity_key = str(snap["entity_key"])[:40]
        print(f"{entity_key:<40}  {risk_score:>10.2f}  {uncertainty:>12.4f}  {reason}")

    print()
    print(f"Inference check passed: {n} entities scored  (mc_samples={mc_samples}  device={device})")
    return 0


if __name__ == "__main__":
    sys.exit(main())

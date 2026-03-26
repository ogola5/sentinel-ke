# Real Data Training Runs

This document records the real-data-backed GNN runs used to evaluate Sentinel-KE on the current stack.

## Cyber: `Wmid`

Command used:

```bash
docker exec sentinel-ke-backend-1 python -m app.analytics.layer3.gnn_train_worker \
  --window-key Wmid \
  --window-end 2026-03-24T20:39:28.757381+00:00 \
  --split-policy temporal_recency_holdout \
  --max-entities 2000 \
  --max-edges 50000 \
  --epochs 8 \
  --prediction-type risk_gnn \
  --artifact-dir /app/artifacts/gnn
```

Result:

```json
{
  "status": "ok",
  "gnn_run_id": "f635f4f9-bdea-43ec-a262-028fc7332c73",
  "window_key": "Wmid",
  "window_end": "2026-03-24T20:39:28.757381+00:00",
  "nodes": 97,
  "edges": 237,
  "positive_count": 44,
  "negative_count": 53,
  "artifact_path": "/app/artifacts/gnn/f635f4f9-bdea-43ec-a262-028fc7332c73.pt",
  "metrics": {
    "accuracy": 0.546392,
    "precision": 0.0,
    "recall": 0.0,
    "f1": 0.0,
    "auc": 0.892796,
    "brier": 0.2407,
    "ece": 0.00808,
    "calibration_ece": 0.536086,
    "calibration_mce": 0.536086
  }
}
```

Assessment:

- Usable as a live cyber demo path.
- Strong enough to present as the current cyber benchmark, but only as a ranking benchmark with a small real graph.
- The fixed 0.5-threshold precision/recall are weak; judges should hear the AUC story and the threshold caveat together.
- The slice is still small even though the ranking separation is meaningfully above chance.

## Corruption: `Wcorruption`

Command used:

```bash
docker exec sentinel-ke-backend-1 python -m app.analytics.corruption.train_worker \
  --window-key Wcorruption \
  --window-end 2026-03-15T17:43:42+00:00 \
  --max-entities 2000 \
  --max-edges 50000 \
  --epochs 8 \
  --artifact-dir /app/artifacts/gnn
```

Result:

```json
{
  "status": "blocked",
  "gate": "fairness",
  "model_version": "corruption-gnn-v1",
  "max_positive_rate_disparity": 0.9035,
  "threshold": 0.4,
  "detail": "Training run blocked by fairness governance gate."
}
```

Artifact path still saved before the gate blocked the run:

```text
/app/artifacts/gnn/corruption_corruption-gnn-v1.pt
```

Assessment:

- Not demo-worthy in strict mode.
- The dataset is large enough to train, but the fairness gate is correctly blocking the run.
- This is a governance blocker, not a crash.

## Notes

- The newest `Wmid` slice was too sparse for a serious run: it produced 27 nodes, 0 negatives, and AUC 0.5.
- The older cyber window above is the best current cyber window for presentation.
- The corruption window above is the best current corruption window, but it still fails strict fairness governance.
- PaySim remains the strongest fraud benchmark lane and should be kept separate from the cyber and corruption narratives.
- The selector helper currently recommends:
  - cyber: `2026-03-24T20:39:28.757381+00:00`
  - corruption: `2026-03-24T12:30:00+00:00`
- The selector output is written to `/app/artifacts/gnn/window_selection.json`.
- The selected corruption window above still fails the strict fairness gate on the current stack:
  - `max_positive_rate_disparity = 0.8904`
  - `threshold = 0.4`
- The corruption artifact still exists at `/app/artifacts/gnn/corruption_corruption-gnn-v1.pt`, but the run is blocked and should not be presented as demo-worthy until the fairness hardening worker lands.

## Window Selection Helper

Use the helper below before rerunning training so the trainers do not blindly pick the newest sparse slice:

```bash
docker exec sentinel-ke-backend-1 python /app/scripts/select_training_window.py \
  --domain both \
  --max-candidates 12 \
  --min-nodes 50 \
  --min-negatives 20 \
  --min-real-ratio 0.3 \
  --out /app/artifacts/gnn/window_selection.json
```

Expected behavior:

- cyber should prefer a denser historical `Wmid` slice, not the latest sparse slice
- corruption should prefer the densest `Wcorruption` slice that still meets the real-data floor
- the output JSON should list the selected window and the runner-up candidates for quick review

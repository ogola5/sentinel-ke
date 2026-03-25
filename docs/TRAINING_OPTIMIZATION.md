# Training Optimization

Last reviewed: 2026-03-25 (Africa/Nairobi)

This note describes the local runtime posture for the GNN / ML stack. The goal is to keep training and inference practical on developer hardware without changing the core model logic.

## What Was Tuned

- `docker-compose.yml` now defaults the API to `WEB_CONCURRENCY=1` so the web process does not compete with training for CPU and RAM.
- Cyber and corruption training workers now use local-friendly defaults:
  - `GNN_MAX_ENTITIES=2500`
  - `GNN_MAX_EDGES=20000`
  - `GNN_EPOCHS=30`
  - `GNN_SPLIT_POLICY=temporal_recency_holdout`
  - `GNN_MIN_NEGATIVE_COUNT=5`
  - `GNN_MIN_NEGATIVE_RATIO=0.10`
  - `GNN_BENCHMARK_WINDOW_CANDIDATES=12`
- `GNN_PRETRAIN_EPOCHS=3` for cyber training
  - smaller hidden / embedding dimensions: `48/24`
  - `RETRAIN_INTERVAL_SEC=14400` so the loop is not retriggering every hour by default
- Inference defaults are less bursty:
  - `INFERENCE_MIN_INTERVAL_SEC=30`
  - `INFERENCE_BATCH_THRESHOLD=25`
  - `INFERENCE_MAX_ENTITIES=2500`
  - `INFERENCE_CONSUMER_TIMEOUT_MS=1000`
- CPU thread pressure is capped through `GNN_CPU_THREADS=4` and the standard BLAS thread env vars in compose.
- CUDA determinism is enabled when `CUBLAS_WORKSPACE_CONFIG=:4096:8` is present, which the compose file now sets for training / notebook services.
- `GNN_WINDOW_KEY=Wmid` stays the default because the newest `Wshort` slice is often sparse and can make local runs look broken when they are only data-starved.
- The cyber trainer now prefers a recent benchmarkable `Wmid` slice over a newer but degenerate all-positive slice when no explicit `--window-end` is given.

## Current Model Behavior

These are properties of the existing model code, not new logic:

- `train_graphsage()` already uses AMP automatically when CUDA is available.
- On CUDA, deterministic algorithms are enabled when `CUBLAS_WORKSPACE_CONFIG` is set.
- On CPU, AMP is effectively disabled and training runs in full precision.
- The training workers already persist artifacts and metrics; the new config mainly reduces the runtime footprint and makes the defaults realistic for local machines.
- The corruption training worker can return `status=blocked` when the fairness gate or real-data gate fails. That is an expected governance stop, not a crash.

## Practical Hardware Assumptions

These are estimates, not hard requirements:

- CPU-only development: 8 vCPU and 16-32 GB RAM is the practical floor.
- GPU-assisted development: a single NVIDIA GPU with 8-12 GB VRAM is workable for the current local defaults.
- For larger graphs or higher epochs, 16 GB+ VRAM and 32 GB+ system RAM become much more comfortable.

## Expected Runtime

Approximate local expectations:

- CPU-only, 2.5k entities, 30 epochs: usually tens of minutes, sometimes longer if the graph is dense.
- GPU-backed, same settings: usually single-digit minutes to low tens of minutes.
- If you increase `GNN_MAX_ENTITIES`, `GNN_MAX_EDGES`, or `GNN_EPOCHS`, runtime and memory grow quickly.

These are operational estimates. They depend heavily on graph density, feature shape, and the host's BLAS / CUDA stack.

## Fallback Modes

- If CUDA is unavailable, the model should still train on CPU, just slower.
- If `CUBLAS_WORKSPACE_CONFIG` is missing, CUDA determinism is relaxed rather than failing the run.
- If the heuristic inference fallback is enabled in the environment, the API can still score with rules when model inference is not available.

## Validation

Run the local preflight script before training:

```bash
bash backend/scripts/check_training_env.sh
```

Use strict mode when you want the script to fail on warnings:

```bash
bash backend/scripts/check_training_env.sh --strict
```

Useful validation commands:

```bash
docker compose config
docker compose up -d postgres redpanda backend cyber-train-worker corruption-train-worker inference-consumer notebook
docker compose logs -f cyber-train-worker
```

## Residual Risks

- Dense graphs still dominate memory use even when entity counts are capped.
- CPU-only runs remain slow if you keep the default epoch count and raise the graph size.
- The compose defaults are tuned for local practicality, not maximum model quality; for benchmark runs, increase the limits explicitly.

# Local GNN Runtime

Last reviewed: 2026-03-25 (Africa/Nairobi)

This is the quick-start guide for running the GNN / ML stack locally with practical defaults.

## Recommended Setup

- `backend/scripts/check_training_env.sh` should pass before you start the workers.
- Use the compose defaults for a first pass. They are already tuned down from the earlier, heavier settings.
- If you have a GPU, keep `CUBLAS_WORKSPACE_CONFIG=:4096:8` in the environment to preserve deterministic CUDA behavior.
- Keep `GNN_WINDOW_KEY=Wmid` unless you explicitly want to test the freshest slice. The `Wshort` slice is often sparse and can fail min-signal checks.
- Keep `GNN_SPLIT_POLICY=temporal_recency_holdout` for benchmark-style runs. The older `entity_hash_holdout` mode is still available, but it should not be the headline evaluation default.

## Startup

```bash
bash backend/scripts/check_training_env.sh
docker compose up -d postgres redpanda backend cyber-train-worker corruption-train-worker inference-consumer notebook
```

If you want the validation command to fail on warnings:

```bash
bash backend/scripts/check_training_env.sh --strict
```

## Environment Presets

CPU-friendly local preset:

```bash
export GNN_CPU_THREADS=4
export GNN_WINDOW_KEY=Wmid
export GNN_SPLIT_POLICY=temporal_recency_holdout
export GNN_MAX_ENTITIES=2500
export GNN_MAX_EDGES=20000
export GNN_MIN_NEGATIVE_COUNT=5
export GNN_MIN_NEGATIVE_RATIO=0.10
export GNN_BENCHMARK_WINDOW_CANDIDATES=12
export GNN_EPOCHS=30
export GNN_PRETRAIN_EPOCHS=3
export RETRAIN_INTERVAL_SEC=14400
export INFERENCE_BATCH_THRESHOLD=25
export INFERENCE_MIN_INTERVAL_SEC=30
```

GPU-friendly local preset:

```bash
export GNN_CPU_THREADS=4
export GNN_WINDOW_KEY=Wmid
export GNN_SPLIT_POLICY=temporal_recency_holdout
export GNN_MAX_ENTITIES=3000
export GNN_MAX_EDGES=25000
export GNN_MIN_NEGATIVE_COUNT=5
export GNN_MIN_NEGATIVE_RATIO=0.10
export GNN_BENCHMARK_WINDOW_CANDIDATES=12
export GNN_EPOCHS=30
export GNN_PRETRAIN_EPOCHS=3
export RETRAIN_INTERVAL_SEC=14400
export INFERENCE_BATCH_THRESHOLD=50
export INFERENCE_MIN_INTERVAL_SEC=30
export CUBLAS_WORKSPACE_CONFIG=:4096:8
```

## Behavior To Expect

- Training workers retry in a loop, but the retrain interval is now long enough that they do not keep hammering your machine.
- Inference is batchy by design. It will not score every event immediately.
- CPU runs are acceptable for local validation, but they are not the right mode for large-scale benchmark claims.
- The corruption worker returning `status=blocked` on a fairness or real-data gate is an expected stop condition. Treat it as a governance decision, not a crash.

## When To Override Defaults

- Increase `GNN_EPOCHS` only when you are evaluating model quality, not when you are checking wiring.
- Increase `GNN_MAX_ENTITIES` and `GNN_MAX_EDGES` only when you have the RAM to support it.
- Reduce `RETRAIN_INTERVAL_SEC` only if you explicitly want aggressive retraining during a short experiment.

## Troubleshooting

- If training fails immediately, check `DATABASE_URL`, `REDPANDA_BROKERS`, and artifact directory permissions.
- If CUDA is present but determinism is not, verify `CUBLAS_WORKSPACE_CONFIG`.
- If the machine feels overloaded, lower `WEB_CONCURRENCY`, `GNN_MAX_ENTITIES`, and `GNN_EPOCHS` first.

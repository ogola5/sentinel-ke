# Sentinel-KE Notebook Pipeline

Use these notebooks in order:

1. `notebooks/00_pipeline_setup.ipynb`
2. `notebooks/04_real_data_ingest_and_hybrid_pipeline.ipynb` (optional but recommended)
3. `notebooks/01_feature_build.ipynb`
4. `notebooks/02_gnn_train.ipynb`
5. `notebooks/03_eval_and_explain.ipynb`

## What changed

- `notebooks/pipeline_bootstrap.py` now:
  - normalizes `DATABASE_URL` for local VS Code kernels (rewrites `postgres` host to `localhost:5433` outside Docker)
  - exposes helper functions for source seeding, real-data ingestion, feature building, and GNN training
  - validates schema prerequisites and applies minimal idempotent legacy repairs used by notebook pipeline

## Real data path

`notebooks/04_real_data_ingest_and_hybrid_pipeline.ipynb` ingests:

- KEV + EPSS -> `VULNERABILITY_EVENT`
- CIC rows -> `DDOS_SIGNAL_EVENT` / `WEB_ATTACK_EVENT`
- CAIDA rows -> `DDOS_SIGNAL_EVENT`

Then it runs:

- feature snapshots (`graph_feature_snapshot`)
- cyber GNN training (`gnn_training_run`)

## Troubleshooting

- If setup shows missing columns, run the repair cell in `00_pipeline_setup.ipynb`.
- If you want full migration alignment instead of minimal notebook repair:
  - `docker compose exec -w /app backend alembic -c alembic.ini upgrade head`

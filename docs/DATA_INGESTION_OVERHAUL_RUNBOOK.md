# Data Ingestion Overhaul Runbook

This runbook covers the live OSINT feed adapters, the OTX STIX bridge,
and the PPRA/OCDS corruption importer added for the GNN pipelines.

## 1. Seed the new feed sources

```bash
docker compose exec backend python -m app.ledger.seed_sources
```

Default source API keys seeded by that script:

- `feodo-live-secret-key`
- `urlhaus-live-secret-key`
- `otx-live-secret-key`
- `ppra-ocds-secret-key`

## 2. Run the live OSINT jobs manually

Feodo:

```bash
docker compose exec backend python -m app.integrations.real_data_pipeline \
  --source-api-key feodo-live-secret-key \
  --classification PUBLIC \
  --confidence 0.96 \
  feodo
```

URLhaus:

```bash
docker compose exec backend python -m app.integrations.real_data_pipeline \
  --source-api-key urlhaus-live-secret-key \
  --classification PUBLIC \
  --confidence 0.94 \
  urlhaus \
  --auth-key "$URLHAUS_AUTH_KEY" \
  --max-records 400 \
  --sleep-every 400 \
  --sleep-sec 65
```

OTX, importing both STIX indicators and DFIR events:

```bash
docker compose exec backend python -m app.integrations.real_data_pipeline \
  --source-api-key otx-live-secret-key \
  --classification PUBLIC \
  --confidence 0.93 \
  otx \
  --otx-api-key "$OTX_API_KEY" \
  --max-records 400 \
  --sleep-every 400 \
  --sleep-sec 65
```

OTX, STIX only:

```bash
docker compose exec backend python -m app.integrations.real_data_pipeline \
  --source-api-key otx-live-secret-key \
  --classification PUBLIC \
  --confidence 0.93 \
  otx \
  --otx-api-key "$OTX_API_KEY" \
  --max-records 400 \
  --sleep-every 400 \
  --sleep-sec 65 \
  --stix-only
```

## 3. Import PPRA / OCDS procurement data

Example with a flat CSV extract from Open Contracting publication 147:

```bash
docker compose exec backend python -m app.analytics.corruption.ocds_ingest \
  --input-file /app/data/ppra_publication_147.csv
```

For a smaller development pass:

```bash
docker compose exec backend python -m app.analytics.corruption.ocds_ingest \
  --input-file /app/data/ppra_publication_147.csv \
  --max-records 5000
```

## 4. Refresh features and train the GNNs

Refresh cyber snapshots:

```bash
docker compose exec backend python -m app.analytics.layer3.graph_feature_worker --window-key Wmid
```

Train cyber GNN:

```bash
docker compose exec cyber-train-worker python -m app.analytics.layer3.gnn_train_worker \
  --window-key Wmid \
  --edge-backend postgres \
  --epochs 20
```

Train corruption GNN:

```bash
docker compose exec corruption-train-worker python -m app.analytics.corruption.train_worker \
  --window-key Wcorruption \
  --edge-backend postgres \
  --epochs 20
```

## 5. Verify ingestion and training

Check that the new connectors are registered:

```bash
curl -sS http://localhost:8000/v1/integrations/connectors | jq '.items[] | .key'
```

Check event volume by source:

```bash
docker compose exec -T postgres psql -U sentinel -d sentinel -c \
"SELECT source_id, event_type, count(*) FROM event_log GROUP BY source_id, event_type ORDER BY count(*) DESC;"
```

Check corruption snapshots:

```bash
docker compose exec -T postgres psql -U sentinel -d sentinel -c \
"SELECT window_key, count(*), max(window_end) FROM graph_feature_snapshot GROUP BY window_key ORDER BY window_key;"
```

Check training freshness:

```bash
docker compose exec -T postgres psql -U sentinel -d sentinel -c \
"SELECT prediction_type, max(created_at), max(window_end) FROM gnn_training_run GROUP BY prediction_type ORDER BY prediction_type;"
```

Check AI predictions:

```bash
docker compose exec -T postgres psql -U sentinel -d sentinel -c \
"SELECT prediction_type, decision_source, count(*) FROM ai_prediction GROUP BY prediction_type, decision_source ORDER BY prediction_type, decision_source;"
```

## 6. Optional feeder workers

`docker-compose.yml` now includes:

- `feodo-ingest-worker`
- `urlhaus-ingest-worker`
- `otx-ingest-worker`

These poll on loops matching the planned cadence:

- Feodo: every 5 minutes
- URLhaus: every 15 minutes
- OTX: every 30 minutes

`urlhaus-ingest-worker` requires `URLHAUS_AUTH_KEY` and caps mirrored DFIR events
per run with `URLHAUS_EVENT_MAX_RECORDS`.
`otx-ingest-worker` will no-op until `OTX_API_KEY` is set. The worker also caps
mirrored DFIR events per run with `OTX_EVENT_MAX_RECORDS` so it stays below the
backend per-source ingest limiter.

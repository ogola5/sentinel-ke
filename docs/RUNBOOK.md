# Sentinel-KE Runbook

This runbook lists the common commands for demos, workers, and API usage.

## 1) Start the stack

```
docker compose up -d
```

Compose includes a background mule campaign worker (`sentinel-mule-campaign-worker`).
Frontend dev server is proxied to backend via `/v1`, `/health`, and `/ready`.
In Docker, proxy target is `http://backend:8000` (set in `docker-compose.yml`).

## 1.1) Dependency workflow in Docker (important)

Backend image uses:
- `backend/requirements.txt` for runtime dependencies
- `backend/requirements-dev.txt` for development tools (includes `pytest`)

When you add/change dependencies:
1. Runtime library:
   - add it to `backend/requirements.txt`
2. Dev/test tool:
   - add it to `backend/requirements-dev.txt`
3. Rebuild backend-based images:
```
docker compose build backend redpanda-consumer mule-campaign-worker
docker compose up -d backend redpanda-consumer mule-campaign-worker
```

Quick temporary install (not reproducible, lost on rebuild):
```
docker compose exec backend pip install <package>
```

Check pytest is installed in image:
```
docker compose run --rm --no-deps -e PYTHONPATH=/app backend python -m pytest --version
```

## 2) Seed sources (API keys)

```
docker compose run --rm --no-deps -e PYTHONPATH=/app backend python -m app.ledger.seed_sources
```

## 3) Generate demo data (scenarios)

All scenarios are defined in `simulator/scenarios/`. The runner writes directly to Postgres.

Run from repo root (host):
```
DATABASE_URL=postgresql+psycopg2://sentinel:sentinel@localhost:5433/sentinel \
PYTHONPATH=backend \
python simulator/run.py --scenario full_demo --seed-sources
```

Other scenarios:
```
DATABASE_URL=postgresql+psycopg2://sentinel:sentinel@localhost:5433/sentinel \
PYTHONPATH=backend \
python simulator/run.py --scenario ddos_rehearsal

DATABASE_URL=postgresql+psycopg2://sentinel:sentinel@localhost:5433/sentinel \
PYTHONPATH=backend \
python simulator/run.py --scenario ddos_active

DATABASE_URL=postgresql+psycopg2://sentinel:sentinel@localhost:5433/sentinel \
PYTHONPATH=backend \
python simulator/run.py --scenario vpn_rotation

DATABASE_URL=postgresql+psycopg2://sentinel:sentinel@localhost:5433/sentinel \
PYTHONPATH=backend \
python simulator/run.py --scenario fraud_chain
```

Inside docker (quick demo):
```
docker compose run --rm --no-deps -e PYTHONPATH=/app backend \
  python -m app.demo.run_demo --seed-sources --scenario ddos_vpn
```

Inside docker (DDoS + VPN + fraud):
```
docker compose run --rm --no-deps -e PYTHONPATH=/app backend \
  python -m app.demo.run_demo --seed-sources --scenario ddos_vpn_fraud
```

Inside docker (Kafka demo, uses sentinel.ingest topic):
```
docker compose run --rm --no-deps -e PYTHONPATH=/app backend \
  python -m app.demo.run_demo --seed-sources --scenario ddos_vpn --mode kafka --topic sentinel.ingest
```

## 4) Run workers

Graph projection:
```
docker compose run --rm --no-deps -e PYTHONPATH=/app backend python -m app.graph.neo4j_worker
```

DDoS alerts:
```
docker compose run --rm --no-deps -e PYTHONPATH=/app backend python -m app.analytics.layer3.ddos_alert_worker
```

VPN infra clustering:
```
docker compose run --rm --no-deps -e PYTHONPATH=/app backend python -m app.analytics.layer3.vpn_cluster_worker --minutes 60 --min-ips 2
```

Campaign detection (coordination from shared infra):
```
docker compose run --rm --no-deps -e PYTHONPATH=/app backend python -m app.analytics.layer3.campaign_detect_worker
```

Mule-ring campaign detection (SIM swap -> transfers -> cashout):
```
docker compose run --rm --no-deps -e PYTHONPATH=/app backend python -m app.analytics.layer3.mule_campaign_worker --minutes 180 --min-senders 2 --min-tx 4
```

Campaign claims + projection (optional):
```
docker compose run --rm --no-deps -e PYTHONPATH=/app backend python -m app.analytics.claims_worker
```

AI pipeline (features -> embeddings -> predictions):
```
docker compose run --rm --no-deps -e PYTHONPATH=/app backend python -m app.analytics.layer3.graph_feature_worker
docker compose run --rm --no-deps -e PYTHONPATH=/app backend python -m app.analytics.layer3.embedding_worker --window-key Wmid
docker compose run --rm --no-deps -e PYTHONPATH=/app backend python -m app.analytics.layer3.ai_inference_worker --window-key Wmid
```

GNN backbone training (hybrid Neo4j + Postgres edges):
```
docker compose run --rm --no-deps -e PYTHONPATH=/app backend \
  python -m app.analytics.layer3.gnn_train_worker \
  --window-key Wmid \
  --edge-backend hybrid \
  --epochs 80
```

Economic leakage worker:
```
docker compose run --rm --no-deps -e PYTHONPATH=/app backend \
  python -m app.analytics.layer3.economic_leakage_worker \
  --window-days 30 \
  --grant-token <LEGAL_GRANT_TOKEN> \
  --target economy:procurement
```

Cover-up risk fusion worker:
```
docker compose run --rm --no-deps -e PYTHONPATH=/app backend \
  python -m app.analytics.layer3.coverup_risk_worker \
  --window-days 30 \
  --min-score 0.45 \
  --grant-token <LEGAL_GRANT_TOKEN> \
  --target economy:coverup
```
## 5) Validate DB state (optional)

```
docker compose exec postgres psql -U sentinel -d sentinel \
  -c "SELECT COUNT(*) FROM event_log;"

docker compose exec postgres psql -U sentinel -d sentinel \
  -c "SELECT COUNT(*) FROM graph_delta_log;"

docker compose exec postgres psql -U sentinel -d sentinel \
  -c "SELECT COUNT(*) FROM ddos_alert;"
```

## 6) API endpoints (frontend consumption)

All endpoints are under `http://localhost:8000`.
If API auth is enabled, use `X-API-Key` (value: `FRONTEND_API_KEY` or `INGEST_API_KEY`).

Health / readiness:
```
GET /health
GET /ready
```

Ingestion:
```
POST /v1/ingest/event
POST /v1/ingest/batch
POST /v1/ingest/file
GET  /v1/ingest/schema
```

Integrations (external software connectors -> canonical ingest):
```
GET  /v1/integrations/connectors
POST /v1/integrations/{connector_key}/event
POST /v1/integrations/{connector_key}/batch
```

Legal controls (court-order constrained operations):
```
POST /v1/legal/orders
POST /v1/legal/orders/{order_id}/revoke
GET  /v1/legal/orders
POST /v1/legal/approval/payload
POST /v1/legal/authorize
POST /v1/legal/grants/verify
GET  /v1/legal/grants
POST /v1/legal/scan-plan
POST /v1/legal/evidence/export
GET  /v1/legal/evidence/bundles
GET  /v1/legal/evidence/bundles/{bundle_id}
GET  /v1/legal/evidence/bundles/{bundle_id}/anchor
POST /v1/legal/evidence/bundles/{bundle_id}/anchor/refresh
```

Legal approval workflow (2-person crypto):
```
# 1) Request canonical payload to sign
POST /v1/legal/approval/payload

# 2) Approvers sign the returned "message" with HMAC-SHA256 using approver secret keys
#    (configured in LEGAL_APPROVER_SECRETS)

# 3) Submit authorization request with approved_by + approval_signatures[]
POST /v1/legal/authorize
```

Sensitive economy operations now require header:
```
X-Legal-Grant-Token: <execution_token_from_authorize>
```

Legal evidence anchoring configuration (Phase 3):
```
# MinIO anchor modes: stub | webhook | s3 | disabled
MINIO_ANCHOR_MODE=stub
MINIO_ANCHOR_BUCKET=sentinel-legal-evidence
MINIO_ANCHOR_WEBHOOK_URL=
MINIO_S3_ENDPOINT=minio:9000
MINIO_S3_REGION=us-east-1
MINIO_S3_ACCESS_KEY=minioadmin
MINIO_S3_SECRET_KEY=minioadmin
MINIO_S3_SECURE=false
MINIO_S3_CREATE_BUCKET_IF_MISSING=false
MINIO_OBJECT_LOCK_RETENTION_DAYS=365
MINIO_OBJECT_LEGAL_HOLD=true

# immudb anchor modes: stub | webhook | http | disabled
IMMUDB_ANCHOR_MODE=stub
IMMUDB_ANCHOR_WEBHOOK_URL=
IMMUDB_HTTP_BASE_URL=
IMMUDB_HTTP_ANCHOR_PATH=/api/v2/anchor
IMMUDB_HTTP_TOKEN=
```

Local passive network probe connector:
```
# source key seeded by app.ledger.seed_sources:
#   source_id=local_net_probe
#   source_api_key=local-net-probe-secret-key
PYTHONPATH=backend python -m app.integrations.local_network_probe \
  --endpoint http://localhost:8000 \
  --x-api-key "${INGEST_API_KEY:-dev-secret-key}" \
  --interval-seconds 10
```

Events:
```
GET /v1/events
GET /v1/events/{event_hash}
GET /v1/events/timeline
```

Graph:
```
GET /v1/graph
GET /v1/infra/graph
```

Campaigns:
```
GET /v1/campaigns
GET /v1/campaigns/{id}
GET /v1/campaigns/{id}/events
GET /v1/campaigns/{id}/evidence
GET /v1/campaigns/{id}/risk
```

Infra clusters:
```
GET /v1/infra/clusters
GET /v1/infra/clusters/{id}
```

DDoS:
```
GET /v1/ddos/overview
GET /v1/ddos/indicators
GET /v1/ddos/alerts
```

Anomalies + mitigations:
```
GET /v1/anomalies
GET /v1/mitigations
GET /v1/mitigations/export
```

Cases + STIX:
```
POST /v1/cases/from-campaign/{campaign_id}
GET  /v1/cases/{case_id}
GET  /v1/stix/case/{campaign_id}
GET  /v1/stix/campaign/{campaign_id}
GET  /v1/stix/mitigations?kind=DDOS
```

Metrics:
```
GET /v1/metrics
```

Economy (procurement + guardrails + tamper integrity):
```
POST /v1/economy/procurement/analyze
POST /v1/economy/guardrail/evaluate
GET  /v1/economy/guardrail/decisions
POST /v1/economy/integrity/snapshot
GET  /v1/economy/integrity/alerts
POST /v1/economy/leakage/run
GET  /v1/economy/leakage/alerts
GET  /v1/economy/leakage/summary
POST /v1/economy/coverup/run
GET  /v1/economy/coverup/alerts
GET  /v1/economy/coverup/summary
GET  /v1/economy/signals
GET  /v1/economy/procurement/anomalies
```

## 7) Demo checks in Neo4j (optional)

```
docker compose exec neo4j cypher-shell -u neo4j -p "$NEO4J_PASSWORD" \
  "MATCH (n) RETURN labels(n)[0], n.key LIMIT 10;"
```

## Notes

- If DDoS/VPN alerts are empty, make sure demo scenarios ran and workers were executed.
- The simulator runs on the host using the DB URL; it does not require the API server.

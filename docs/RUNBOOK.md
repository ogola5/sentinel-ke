# Sentinel-KE Runbook

This runbook lists the common commands for demos, workers, and API usage.
Phase tracker is in:
`docs/PHASES_90_TRACKER.md`

Backend architecture and security reference:
`docs/BACKEND_DOCUMENTATION.md`

API examples for frontend/integration consumers:
`docs/API_CONSUMER_GUIDE.md`

Generated endpoint inventory:
`docs/API_ENDPOINT_INVENTORY.md`

## 1) Start the stack

```
docker compose up -d
```

Compose includes a background mule campaign worker (`sentinel-mule-campaign-worker`).
Frontend dev server is proxied to backend via `/v1`, `/health`, and `/ready`.
In Docker, proxy target is `http://backend:8000` (set in `docker-compose.yml`).

## 1.1) Dependency workflow in Docker (important)

Backend image uses:
- `backend/requirements-runtime.txt` for core runtime dependencies
- `backend/requirements-ml.txt` for heavy ML dependencies (CPU torch wheel, cached separately)
- `backend/requirements.txt` as aggregate full-dependency list (runtime + ML)
- `backend/requirements-dev.txt` for development tools (`pytest`, `jupyterlab`, data science libs)

Important:
- Code-only edits do not require rebuild (`./backend` is mounted into `/app`).
- Only dependency changes require rebuild.
- The Dockerfile installs ML dependencies only when `INSTALL_ML=1`, in a dedicated cached layer.
- Torch is pinned to CPU wheels to avoid massive CUDA downloads on slow links.

When you add/change dependencies:
1. Runtime library:
   - add it to `backend/requirements-runtime.txt`
2. Heavy ML library:
   - add it to `backend/requirements-ml.txt`
3. Dev/test tool:
   - add it to `backend/requirements-dev.txt`
4. Rebuild backend-based images:
```
docker compose build backend notebook redpanda-consumer mule-campaign-worker
docker compose up -d backend notebook redpanda-consumer mule-campaign-worker
```

Quick temporary install (not reproducible, lost on rebuild):
```
docker compose exec backend pip install <package>
```

Fast patch install to all Python services (temporary):
```
docker compose exec backend pip install <package>
docker compose exec notebook pip install <package>
docker compose exec redpanda-consumer pip install <package>
docker compose exec mule-campaign-worker pip install <package>
docker compose restart backend notebook redpanda-consumer mule-campaign-worker
```

Check pytest is installed in image:
```
docker compose run --rm --no-deps -e PYTHONPATH=/app backend python -m pytest --version
```

## 1.2) Jupyter Lab in Docker (VS Code notebook workflow)

Start notebook service:
```
docker compose up -d notebook
```

Open:
```
http://localhost:8888/lab?token=<JUPYTER_TOKEN>
```

Default token (from `.env.example`):
```
change-me-jupyter-token
```

Notebook files are in:
```
notebooks/
```

Suggested order:
1. `notebooks/01_feature_build.ipynb`
2. `notebooks/02_gnn_train.ipynb`
3. `notebooks/03_eval_and_explain.ipynb`

## 1.3) Database migrations (Alembic)

Migration config lives in:
`backend/alembic.ini`

Apply migrations:
```
docker compose exec -w /app backend alembic -c alembic.ini upgrade head
```

Create a new migration revision:
```
docker compose exec -w /app backend alembic -c alembic.ini revision -m "describe_change"
```

## 1.4) Repository health gate (before push)

Run from repo root:
```
./scripts/repo_health_check.sh
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
  --negative-multiplier 1.5 \
  --threshold-min-samples 10 \
  --epochs 80
```

AI intelligence enrichment workers:
```
docker compose run --rm --no-deps -e PYTHONPATH=/app backend \
  python -m app.analytics.layer3.path_risk_worker --prediction-type risk_gnn --window-key Wmid
docker compose run --rm --no-deps -e PYTHONPATH=/app backend \
  python -m app.analytics.layer3.decision_fusion_worker --prediction-type risk_gnn --window-key Wmid
docker compose run --rm --no-deps -e PYTHONPATH=/app backend \
  python -m app.analytics.layer3.baseline_worker --prediction-type risk_gnn --window-key Wmid
docker compose run --rm --no-deps -e PYTHONPATH=/app backend \
  python -m app.analytics.layer3.input_anomaly_worker --prediction-type risk_gnn --window-key Wmid
docker compose run --rm --no-deps -e PYTHONPATH=/app backend \
  python -m app.analytics.layer3.drift_worker --prediction-type risk_gnn --window-key Wmid --model-version gnn-sage-v1
```

Threat pattern alert worker:
```
docker compose run --rm --no-deps -e PYTHONPATH=/app backend \
  python -m app.analytics.layer3.threat_pattern_worker --minutes 60
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
Auth options:
- `X-API-Key` for service traffic (backward-compatible).
- `Authorization: Bearer <access_token>` for user login sessions.
- `central` access level is required for legal/economy control-plane routes.

Health / readiness:
```
GET /health
GET /ready
```

Ingestion:
```
POST /v1/ingest/event
POST /v1/ingest/batch
GET  /v1/ingest/schema
```

User auth + RBAC:
```
POST /v1/auth/login
POST /v1/auth/refresh
POST /v1/auth/logout
GET  /v1/auth/me
POST /v1/auth/users
GET  /v1/auth/users
POST /v1/auth/password/change
POST /v1/auth/users/{username}/password/reset
GET  /v1/auth/policies
POST /v1/auth/mfa/enroll/start
POST /v1/auth/mfa/enroll/verify
POST /v1/auth/mfa/disable
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
MINIO_S3_ACCESS_KEY=change-me-minio-access-key
MINIO_S3_SECRET_KEY=change-me-minio-secret-key
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
  --x-api-key "${INGEST_API_KEY}" \
  --interval-seconds 10
```

Events:
```
GET /v1/events/search
GET /v1/events/timeline
GET /v1/events/{event_hash}
```

Graph:
```
GET  /v1/graph/entity/{entity_key}
GET  /v1/graph/neighbors/{entity_key}
GET  /v1/graph/path?from=<entity_key>&to=<entity_key>
GET  /v1/graph/evidence/{event_hash}
POST /v1/graph/infra/project/{cluster_id}
POST /v1/graph/infra/project-recent
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

AI + GNN:
```
GET /v1/ai/predictions?prediction_type=risk_gnn
GET /v1/ai/explanations/{prediction_id}
GET /v1/ai/gnn/runs
GET /v1/ai/gnn/runs/{run_id}
GET /v1/ai/thresholds
GET /v1/ai/campaign-indicators
GET /v1/ai/techniques
GET /v1/ai/path-scores
GET /v1/ai/link-predictions
GET /v1/ai/decision-fusions
GET /v1/ai/drift-reports
GET /v1/ai/input-anomalies
GET /v1/ai/baselines
POST /v1/ai/feedback
GET /v1/ai/feedback
GET /v1/ai/rollouts
POST /v1/ai/rollouts
GET /v1/ai/threat-intel
POST /v1/ai/threat-intel/import-stix
POST /v1/ai/threat-intel/export-stix
```

Cases + STIX:
```
POST /v1/cases/from-campaign/{campaign_id}
GET  /v1/stix/from-campaign/{campaign_id}
GET  /v1/stix/from-case/{campaign_id}
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

Defense:
```
POST /v1/defense/vulnerabilities
GET  /v1/defense/vulnerabilities
POST /v1/defense/vulnerabilities/score-sla
POST /v1/defense/backups/attest
GET  /v1/defense/backups/attest
POST /v1/defense/backups/restore-drills
GET  /v1/defense/backups/restore-drills
POST /v1/defense/incidents/runs
GET  /v1/defense/incidents/runs
POST /v1/defense/incidents/runs/{run_id}/actions
GET  /v1/defense/threat-alerts
POST /v1/defense/threat-alerts/refresh
GET  /v1/defense/crypto/posture
POST /v1/defense/crypto/posture/snapshot
```

## 7) Demo checks in Neo4j (optional)

```
docker compose exec neo4j cypher-shell -u neo4j -p "$NEO4J_PASSWORD" \
  "MATCH (n) RETURN labels(n)[0], n.key LIMIT 10;"
```

## Notes

- If DDoS/VPN alerts are empty, make sure demo scenarios ran and workers were executed.
- The simulator runs on the host using the DB URL; it does not require the API server.

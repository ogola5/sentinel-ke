# Sentinel-KE Runbook

This runbook lists the common commands for demos, workers, and API usage.

## 1) Start the stack

```
docker compose up -d
```

Compose includes a background mule campaign worker (`sentinel-mule-campaign-worker`).

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

## 7) Demo checks in Neo4j (optional)

```
docker compose exec neo4j cypher-shell -u neo4j -p "$NEO4J_PASSWORD" \
  "MATCH (n) RETURN labels(n)[0], n.key LIMIT 10;"
```

## Notes

- If DDoS/VPN alerts are empty, make sure demo scenarios ran and workers were executed.
- The simulator runs on the host using the DB URL; it does not require the API server.

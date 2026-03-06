# Sentinel-KE Production Deployment Proof

Last updated: 2026-03-02 (Africa/Nairobi)

This document is the operational proof package for:

- HA readiness
- observability
- incident replay under load

## 1) HA Proof (Kubernetes)

Template: `infra/k8s/backend.yaml`

Implemented controls:

- `replicas: 3` backend pods
- rolling update strategy (`maxUnavailable: 1`, `maxSurge: 1`)
- readiness + liveness probes
- startup probe (`/ready`) for cold-start safety
- pod anti-affinity (prefer different nodes)
- topology spread constraint by hostname
- HPA (`minReplicas: 2`, `maxReplicas: 12`)
- PodDisruptionBudget (`minAvailable: 2`)

These controls collectively provide controlled upgrades and partial-node failure tolerance.

## 2) Observability Proof

### API-level telemetry

- JSON operational metrics: `GET /v1/metrics`
- Prometheus scrape endpoint: `GET /metrics`

Prometheus metrics exported:

- `sentinel_http_requests_total{method,path,status_code}`
- `sentinel_http_request_duration_ms_bucket{method,path,...}`

### Health endpoints

- `GET /health` (service + model + schema contract)
- `GET /ready` (component readiness: postgres/opensearch/neo4j)

## 3) Incident Replay Under Load

Replay tool: `backend/app/demo/replay.py`

### Purpose

Replays historical `event_log` windows into `/v1/ingest/event` with:

- controlled concurrency
- optional rate cap
- latency distribution and throughput summary
- strict pre-validation against `CanonicalEvent` + typed payload validators

### Command

```bash
PYTHONPATH=backend python -m app.demo.replay \
  --mode direct \
  --base-url http://localhost:8000 \
  --api-key <VALID_SOURCE_RAW_API_KEY> \
  --start-at 2026-03-01T00:00:00Z \
  --end-at 2026-03-01T23:59:59Z \
  --section-code telecom \
  --concurrency 20 \
  --rate-per-sec 120 \
  --limit 2000
```

Output is JSON with:

- `rows_loaded` and `skipped_invalid` (real-data quality signal)
- accepted/rejected/failure counts
- effective requests/sec
- p50/p95/p99 replay latency
- status distribution (`status_counts`)

### Example measured run (local, 2026-03-02)

Command:

```bash
KAFKA_ENABLED=false PYTHONPATH=backend python -m app.demo.replay \
  --mode direct \
  --base-url http://localhost:8000 \
  --api-key safaricom-secret-key \
  --start-at 2026-02-24T00:00:00Z \
  --end-at 2026-03-01T23:59:59Z \
  --limit 200 \
  --concurrency 10 \
  --rate-per-sec 50
```

Observed summary:

- `rows_loaded=200`
- `skipped_invalid=128` (non-canonical or schema-invalid historical rows)
- `total_events=72`
- `accepted_2xx=72`
- `failures=0`
- `rps_effective=49.75`
- `latency_p95_ms=67.9`

## 4) Evidence to capture for judges

For each run, capture:

1. `kubectl get deploy,hpa,pdb` output
2. sample `/metrics` snippet showing request counters/histograms
3. replay summary JSON from `app.demo.replay`
4. `/health` snapshot including schema contract + model metadata

This is the minimum defensible package for “production-level deployment proof”.

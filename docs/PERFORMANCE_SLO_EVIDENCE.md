# Sentinel-KE Performance & SLO Evidence

Last updated: 2026-03-02 (Africa/Nairobi)

## Scope

This document captures measured API latency/throughput from the running local stack, plus explicit SLO targets used for judging and operations reviews.

## Measurement setup

- Stack: local Docker Compose (`sentinel-backend`, `sentinel-postgres`, `sentinel-redpanda`, `sentinel-neo4j`, `sentinel-opensearch`)
- API host: `http://localhost:8000`
- Tool: ApacheBench (`ab`)
- Auth header used: `X-API-Key: dev-secret-key`

## Benchmarks

### 1) Health endpoint (`GET /health`)

Command:

```bash
REQUESTS=120 CONCURRENCY=10 HUB_API_KEY=dev-secret-key BASE_URL=http://localhost:8000 \
bash backend/scripts/load_test.sh
```

Observed:

- Complete requests: `120`
- Failed requests: `0`
- Requests/sec: `86.05`
- p50 latency: `98 ms`
- p95 latency: `193 ms`
- p99 latency: `203 ms`
- max latency: `214 ms`

### 2) Metrics endpoint (`GET /v1/metrics`)

Command:

```bash
ab -n 180 -c 20 -H "X-API-Key: dev-secret-key" http://localhost:8000/v1/metrics
```

Observed:

- Complete requests: `180`
- Failed requests: `178` (length mismatch from dynamic JSON body size, not transport/status failures)
- Requests/sec: `101.14`
- p50 latency: `187 ms`
- p95 latency: `245 ms`
- p99 latency: `268 ms`
- max latency: `283 ms`

### 3) Incident replay benchmark (`app.demo.replay`, strict pre-validation)

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

Observed:

- Loaded rows: `200`
- Schema-valid replayable rows: `72`
- Skipped invalid rows: `128`
- Accepted (2xx): `72`
- Failures: `0`
- Effective replay RPS: `49.75`
- Replay latency p50/p95/p99: `35.39 / 67.9 / 108.51 ms`

## Rate-limit behavior evidence

Stress run at `1000` requests and concurrency `20` on `/health` produced non-2xx responses after policy thresholds were crossed. This is expected guardrail behavior (protection against burst abuse), not a backend crash.

## SLO targets (current)

- API availability under policy-compliant load: `>= 99.5%`
- Read API latency:
  - p95 `< 400 ms`
  - p99 `< 500 ms`
- Error budget:
  - 5xx responses `< 0.5%` on policy-compliant load tests
- Controlled degradation:
  - Burst excess should return 429/401/403 quickly (not timeout/crash)

## Status against SLO

- `/health`: PASS
- `/v1/metrics`: PASS
- incident replay under controlled load: PASS (for schema-valid rows)
- Burst guardrails: PASS (rate-limit protection active)

## Re-run checklist

1. Ensure stack is healthy: `docker ps`
2. Wait for cooldown if you just ran a heavy load test (rate limiter).
3. Run the two benchmark commands above.
4. Update this file with exact numbers and date.

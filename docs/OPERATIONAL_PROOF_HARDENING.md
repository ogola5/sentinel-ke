# Operational Proof Hardening

This runbook closes the main proof-script weaknesses that remained after the
core app stabilized:

- demo seeding no longer stores raw partner API keys in DB metadata
- demo credentials are redacted by default unless explicitly requested
- PaySim benchmarking can now be rerun deterministically with `--reset-window`
- benchmark artifacts now record CSV identity and run configuration
- federation presenter script no longer prints unsupported impact claims
- operational readiness probe can now verify auth and RBAC flows, not only GET health checks

## 1. Safe Demo Agency Seeding

Default behavior:
- creates demo users
- creates demo federation partners
- refreshes cross-agency patterns and partner heartbeat metadata
- prints redacted account summary only

```bash
docker exec sentinel-ke-backend-1 python /app/scripts/seed_demo_agencies.py
```

Expected:
- `Users: ... created / already existed`
- `Partners: ... created / already existed`
- `Cross-agency patterns: ... created`
- usernames printed without passwords
- partner API key fingerprints printed without raw keys

If you explicitly need a rehearsal manifest:

```bash
docker exec sentinel-ke-backend-1 python /app/scripts/seed_demo_agencies.py \
  --write-credentials /app/artifacts/demo_credentials.json
```

If you explicitly need secrets printed for a controlled rehearsal:

```bash
docker exec sentinel-ke-backend-1 python /app/scripts/seed_demo_agencies.py \
  --show-secrets \
  --write-credentials /app/artifacts/demo_credentials_with_secrets.json
```

Use `--show-secrets` only in a private sandbox.

If old temporary validation partners are cluttering the federation view:

```bash
docker exec sentinel-ke-backend-1 python /app/scripts/seed_demo_agencies.py \
  --deactivate-stale-demo-partners
```

This deactivates old `TMP*` and `demo-edge-*` partner rows outside the canonical
demo partner set.

## 2. Clean PaySim Benchmark

The benchmark is only defensible if the run is reproducible. Use a fresh CSV
and reset the window before reseeding.

Copy the CSV into the backend container:

```bash
docker exec sentinel-ke-backend-1 mkdir -p /app/artifacts/paysim
docker cp /tmp/paysim/PS_20174392719_1491204439457_log.csv \
  sentinel-ke-backend-1:/app/artifacts/paysim/PS_20174392719_1491204439457_log.csv
```

Run a clean benchmark:

```bash
docker exec sentinel-ke-backend-1 python /app/scripts/run_paysim_gnn.py \
  --csv /app/artifacts/paysim/PS_20174392719_1491204439457_log.csv \
  --max-rows 200000 \
  --window-key Wpaysim \
  --reset-window \
  --require-csv \
  --out /app/artifacts/paysim_auc.json
```

Expected:
- existing `Wpaysim` snapshots are removed first
- CSV is reread
- snapshots are reseeded
- GNN trains
- `/app/artifacts/paysim_auc.json` is written

The output JSON now includes:
- `csv_name`
- `csv_sha256`
- `window_key`
- `max_rows`
- whether the window was reset
- snapshot seed summary

For an intentional reuse of existing snapshots:

```bash
docker exec sentinel-ke-backend-1 python /app/scripts/run_paysim_gnn.py \
  --window-key Wpaysim \
  --out /app/artifacts/paysim_auc_reuse.json
```

This mode now prints an explicit warning that the benchmark is reusing old snapshots.

## 3. Federation Demonstration

Terminal proof:

```bash
docker exec sentinel-ke-backend-1 python /app/scripts/demo_federation_show.py --live --table-only --no-delay
```

Expected:
- visible multi-agency table
- live partner count
- live cross-agency correlation rows
- only safe presenter talking points

Important:
- do not use this script to cite impact figures
- use benchmark artifacts and probe artifacts for numeric claims

## 4. Operational Readiness Probe

Base probe:

```bash
docker exec sentinel-ke-backend-1 python /app/scripts/verify_operational_scalability.py \
  --base-url http://localhost:8000 \
  --api-key "$FRONTEND_API_KEY" \
  --repeats 2 \
  --out /app/artifacts/operational_scalability_report.json
```

Extended probe with auth and RBAC:

```bash
docker exec sentinel-ke-backend-1 python /app/scripts/verify_operational_scalability.py \
  --base-url http://localhost:8000 \
  --api-key "$FRONTEND_API_KEY" \
  --section-username cbk_analyst \
  --section-password 'Demo@CBK2026!' \
  --central-username ncsc_supervisor \
  --central-password 'Demo@NCSC2026!' \
  --repeats 2 \
  --out /app/artifacts/operational_scalability_report.json
```

Expected extra checks:
- section login succeeds
- section `GET /v1/auth/me` succeeds
- section `GET /v1/auth/users?limit=1` returns `403`
- central login succeeds
- central `GET /v1/auth/me` succeeds
- central `GET /v1/auth/users?limit=1` returns `200`

This makes the probe useful for:
- auth sanity
- RBAC sanity
- central vs section access proof

## 4.1 Lightweight Operational Proof Package

For a broader live snapshot that stays conservative about claims, use the
new proof helper:

```bash
docker exec sentinel-ke-backend-1 python /app/scripts/collect_operational_proof.py \
  --base-url http://localhost:8000 \
  --api-key "$FRONTEND_API_KEY" \
  --section-username cbk_analyst \
  --section-password 'Demo@CBK2026!' \
  --central-username ncsc_supervisor \
  --central-password 'Demo@NCSC2026!' \
  --out /app/artifacts/operational_proof_report.json
```

Expected coverage:
- robustness: health, readiness, metrics, latency, schema contract, worker freshness
- trust: live platform trust summary plus section/central auth and RBAC checks
- integration: campaign-to-case-to-graph flow, federation signals, economy summaries

The helper records skipped optional evidence as skipped, not as success.

## 5. What Is Now Safe To Claim

You can now safely say:
- demo partner API keys are not persisted in partner metadata
- PaySim benchmark runs are reproducible when `--reset-window` is used
- benchmark artifacts record the exact CSV identity and run configuration
- readiness probe can verify both platform health and auth/RBAC basics
- the live proof helper summarizes observed robustness, trust, and integration evidence without overstating readiness

## 6. What Still Requires Rehearsal, Not Just Code

These are not code blockers anymore, but they still require live rehearsal:

- onboarding timing proof
- resilience / hub-down recovery proof
- containment loop before/after explanation
- refreshing a cyber artifact if the final story is cyber-first

## 7. Suggested Pre-Demo Order

1. `seed_demo_agencies.py`
2. `run_paysim_gnn.py --reset-window --require-csv`
3. `verify_operational_scalability.py` with section + central credentials
4. `demo_federation_show.py --live --table-only --no-delay`
5. manual rehearsal for onboarding, containment, and resilience

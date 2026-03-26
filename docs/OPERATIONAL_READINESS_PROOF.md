# Operational Readiness Proof

This is the lightweight live-proof companion for `backend/scripts/collect_operational_proof.py`.
It packages observed evidence from the running backend into a small JSON artifact and a short
console summary.

The helper is intentionally conservative:

- `healthy` means the observed required checks passed.
- `partial` means some optional evidence was skipped or the system had empty live data.
- `degraded` means a required live check failed.
- no output here should be treated as a claim about unrehearsed production readiness.

## Command

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

If you do not have section or central credentials, the helper still runs and marks those
blocks as skipped instead of pretending they were verified.

## What It Reports

The JSON artifact groups evidence into three live-system areas:

| Area | Observed evidence |
|---|---|
| Robustness | `/health`, `/ready`, `/v1/metrics`, `/metrics`, repeated latency samples, schema contract state, worker freshness |
| Trust | `/v1/ai/trust/summary`, section login + `/v1/auth/me`, central login + `/v1/auth/me`, section/central RBAC behavior |
| Integration | campaign list/detail, campaign events and evidence, case packet generation, graph evidence lookup, federation partners/correlations, economy leakage and guardrail summaries |

The artifact also records:

- passed, failed, and skipped checks
- a compact latency summary
- the latest campaign/event IDs observed, when present

## How To Read It

Use the report as evidence of what the running system actually exposed at the time of the probe.
Do not read empty lists as success. They only mean the endpoint responded and the current dataset
had no matching rows.

## Top-15 Rubric Coverage

This helper supports the live-checkable parts of the Top-15 rubric by producing evidence for:

| Rubric dimension | Proof signal |
|---|---|
| Reliability | health, readiness, and response latency samples |
| Observability | `/v1/metrics` counts and runtime metrics |
| Trust and access control | section vs central auth behavior, RBAC denial/allow paths |
| Provenance | campaign evidence, case packet integrity, graph evidence lookup |
| Cross-surface integration | campaign -> case -> graph flow, federation, and economy summaries |
| Governance and model trust | AI trust summary from the live system |

Anything outside those live signals still needs separate rehearsal or artifact-specific proof.

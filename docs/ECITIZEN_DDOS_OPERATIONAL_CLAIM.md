# eCitizen DDoS Operational Claim

This runbook proves the operational claim for a controlled DDoS-style scenario against `service_id:ecitizen`.

## Claim Standard

Sentinel-KE can make a real operational claim only when all of these are true in the same run:

- telemetry is ingested through the real ingest API
- DDoS pressure is detected through the live analytics path
- the graph relates the target to attacker infrastructure
- the GNN scores the target entity
- containment is dispatched through the defense workflow
- containment is written into the ledger as durable evidence

## What Was Implemented

The proof runner is in [run_operational_ddos_claim.py](/home/ogola/personal/sentinel-ke/backend/scripts/run_operational_ddos_claim.py).

It exercises the live stack end to end:

1. seeds the source registry
2. logs in as a central operator
3. ingests a controlled DDoS burst against a chosen service
4. runs anomaly, DDoS, graph feature, GNN inference, path-risk, fusion, campaign, and Neo4j projection workers
5. queries the public APIs for detection, graph, AI, campaign, case, and defense evidence
6. registers self-test containment webhooks
7. dispatches containment actions
8. validates ledger evidence and webhook delivery receipts

## Command

Run from the backend container:

```bash
python /app/scripts/run_operational_ddos_claim.py \
  --service-id ecitizen \
  --endpoint-path /login \
  --section-code ecitizen \
  --base-url http://localhost:8000 \
  --source-api-key ecitizen-secret-key \
  --central-username admin \
  --central-password 'Sentinel@Admin2025!' \
  --out /app/artifacts/operational_ddos_claim_ecitizen.json
```

## Current Passing Result

The latest verified run produced:

- `telemetry_ingested: true`
- `ddos_detected: true`
- `graph_related: true`
- `gnn_scored: true`
- `containment_dispatched: true`
- `containment_logged_in_ledger: true`
- `operational_claim_supported: true`

Headline values from the latest run:

- peak DDoS stage/risk: `active / 100.0`
- current DDoS stage/risk after the burst: `normal / 30.0`
- ledger-backed ingested DDoS events: `80`
- GNN score on `service_id:ecitizen`: `44.7162`
- path score: `99.86265`
- fusion score: `51.795383`
- graph path length from `service_id:ecitizen` to an attacker IP: `2`
- delivered containment receipts: `8`

## How To Explain This Honestly

Use this wording:

`Sentinel-KE ingested the attack through the live API, detected DDoS pressure, related the victim service to attacking infrastructure in the graph, scored the target with the GNN, and dispatched containment with signed delivery receipts and a ledger record.`

Do not use this wording:

- `The GNN alone detected the DDoS.`
- `The model alone proves attribution.`
- `A score of 44 means the service is safe.`

## What The Scores Mean

- `DDoS stage/risk` is the burst classifier from the DDoS analytics path.
- `GNN score` is the model risk indicator on the target entity.
- `Path score` shows structural support from connected attacker infrastructure.
- `Fusion score` combines GNN, path, and anomaly signals into the final decision layer.

In this scenario, the GNN is not the first detector. It is the correlation and prioritization layer above the raw telemetry.

## Why Current Fusion Still Says Monitor

That is expected and honest in this controlled run:

- the DDoS detector reaches `active / 100`
- the graph and path layers strongly support the case
- the target `service_id` still stays below the service containment threshold in the GNN/fusion logic

This means:

- the attack is real
- the system detected and related it correctly
- the automated risk posture remains conservative for service-level enforcement

That is acceptable for a national-security MVP because the platform still dispatches operator-driven containment and records the full audit trail.

## Evidence You Can Show

- detection APIs:
  - `/v1/anomalies`
  - `/v1/ddos/indicators`
  - `/v1/ddos/alerts`
- graph APIs:
  - `/v1/graph/neighbors/{entity_key}`
  - `/v1/graph/path`
- AI APIs:
  - `/v1/ai/predictions`
  - `/v1/ai/explanations/{id}`
  - `/v1/ai/trust/entity`
  - `/v1/ai/path-scores`
  - `/v1/ai/decision-fusions`
- defense APIs:
  - `/v1/defense/incidents/runs`
  - `/v1/defense/incidents/runs/{run_id}/actions`
  - `/v1/defense/webhooks/deliveries`

## Residual Caveats

- OpenSearch can lag the ledger; the ledger is the canonical truth.
- The current `fusion_decision` is still conservative for service-level auto-escalation.
- The global `/health` endpoint still includes unrelated background worker noise and should not be the primary judge artifact.

## Recommended Demo Sequence

1. Run the proof script.
2. Open the generated artifact and read the `summary.claim_checks`.
3. Show `ddos_indicators` and `peak_ddos_alert`.
4. Show the graph path from `service_id:ecitizen` to `ip:203.0.113.1`.
5. Show the GNN prediction, path score, and fusion score together.
6. Show the defense action execution and webhook delivery receipts.
7. Show the `CONTAINMENT_APPLIED` ledger evidence.

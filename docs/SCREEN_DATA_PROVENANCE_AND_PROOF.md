# Screen Data Provenance And Proof

Last updated: 2026-03-30

Use this when a judge asks:

- `Where does this data come from?`
- `Is this live or seeded?`
- `Can you show the data changing?`
- `How do I know these are not hard-coded values?`

## The safest high-level answer

Use this first:

> "The screens are not filled by hard-coded values. They are fed by API responses from the backend. Those responses come from three different sources: live external feeds, replayed demo scenarios through the same ingest path, and model outputs generated from graph snapshots and training runs."

Then break it into three buckets:

1. `Live feeds`
   - real external intelligence and system telemetry
   - example: Feodo, OTX, ThreatFox, MalwareBazaar style findings

2. `Scenario replay`
   - controlled attack or fraud stories pushed through the same canonical ingest path
   - used to make specific workflows visible on demand during a demo

3. `Model outputs`
   - predictions, explanations, trust summaries, and training runs
   - generated from graph snapshots and persisted in backend tables

## What to click if they want proof

The simplest proof path is:

1. open `Command`
2. use `Scenario launcher`
3. click `Launch now` on one scenario
4. move to the recommended next screen
5. click `Refresh`
6. point to the new or current records

If they want to see model refresh:

1. open `Command`
2. in `Scenario launcher`, click `Prepare data + refresh model`
3. then open `GNN Intelligence`
4. refresh until the latest run and prediction window update

These buttons are wired here:

- [ScenarioLauncher.tsx](/home/ogola/personal/sentinel-ke/frontend/src/components/ScenarioLauncher.tsx)
- [ai.ts](/home/ogola/personal/sentinel-ke/frontend/src/api/ai.ts)
- [demo.py](/home/ogola/personal/sentinel-ke/backend/app/api/demo.py)
- [scenario_controller.py](/home/ogola/personal/sentinel-ke/backend/app/demo/scenario_controller.py)

## What each important screen is showing

### `C1 Command`

What it shows:

- national posture
- trust summary
- readiness
- partner and user posture

Where it comes from:

- `operationsData` from [operations.ts](/home/ogola/personal/sentinel-ke/frontend/src/api/operations.ts)
- federation data from [federation.ts](/home/ogola/personal/sentinel-ke/frontend/src/api/federation.ts)
- trust and drift data from [ai.ts](/home/ogola/personal/sentinel-ke/frontend/src/api/ai.ts)

What to say:

> "This screen is an aggregate. It is not one table. It combines live metrics, AI trust posture, resilience records, federation posture, and user readiness from separate backend services."

How to prove it changes:

- click `Launch now` for `DDoS pressure` or `Combined pressure`
- refresh `Command`
- event and queue pressure will refresh from the backend

### `S7 Dashboard`

What it shows:

- event count
- anomaly count
- mitigation count
- graph delta count

Where it comes from:

- `GET /v1/metrics`
- `GET /v1/anomalies`
- `GET /v1/mitigations`
- `GET /v1/ai/predictions`

What to say:

> "This is the live operational heartbeat. The numbers here come directly from backend counters and active queues."

How to prove it changes:

- click `Launch now` for `DDoS pressure`
- refresh `Dashboard`
- anomaly and pressure views should reflect the new ingest

### `S1 Live Feed`

What it shows:

- recent event records
- DFIR and threat-intel findings
- recent scenario replay events

Where it comes from:

- `GET /v1/events/search`
- event rows ingested through the canonical ingestion service

Live feed source code path:

- [real_data_pipeline.py](/home/ogola/personal/sentinel-ke/backend/app/integrations/real_data_pipeline.py)
- [connectors.py](/home/ogola/personal/sentinel-ke/backend/app/integrations/connectors.py)
- [run_demo.py](/home/ogola/personal/sentinel-ke/backend/app/demo/run_demo.py)

What to say:

> "This screen mixes live feed intake and scenario replay intake. Both enter through the same event path, which is why the replay is useful for proving the workflow rather than bypassing it."

How to prove it changes:

- click `Launch now` for `Malware / IOC spread` or `SIM swap fraud chain`
- open `Live Feed`
- refresh
- point to the newest rows and timestamps

### `S2 Threat Graph`

What it shows:

- graph relationships between services, endpoints, IPs, clusters, and campaigns

Where it comes from:

- `GET /v1/graph/neighbors/...`
- graph data built from ingested events and graph workers

Code path:

- [graph.ts](/home/ogola/personal/sentinel-ke/frontend/src/api/graph.ts)
- [GraphExplorer.tsx](/home/ogola/personal/sentinel-ke/frontend/src/screens/GraphExplorer.tsx)
- [graph_feature_worker.py](/home/ogola/personal/sentinel-ke/backend/app/analytics/layer3/graph_feature_worker.py)

What to say:

> "The graph is downstream of ingest. It is not a hand-drawn diagram. Nodes and edges appear because the backend has linked entities from real or replayed events."

How to prove it changes:

- click `Launch now` for `VPN infrastructure reuse` or `DDoS + VPN pressure`
- open `Threat Graph`
- point to the target service and new linked infrastructure

### `S3 Investigate`

What it shows:

- prediction score
- confidence and uncertainty
- reason codes
- evidence hashes
- next actions

Where it comes from:

- `GET /v1/ai/predictions`
- `GET /v1/ai/explanations/{id}`
- `GET /v1/ai/trust/entity?...`

Code path:

- [gnn_backbone.py](/home/ogola/personal/sentinel-ke/backend/app/analytics/layer3/gnn_backbone.py)
- [gnn_model.py](/home/ogola/personal/sentinel-ke/backend/app/analytics/layer3/gnn_model.py)
- [gnn_train_worker.py](/home/ogola/personal/sentinel-ke/backend/app/analytics/layer3/gnn_train_worker.py)

What to say:

> "This screen is model output plus explanation. The visible score comes from a persisted prediction row, and the evidence and reason codes come from its explanation record."

How to prove it changes:

- click `Prepare data + refresh model`
- then open `GNN Intelligence` and wait for the latest run to update
- then return to `Investigate`
- the latest prediction window and score context will reflect the refreshed model state

### `S6 Defense`

What it shows:

- incident runs
- executed containment actions
- webhook delivery receipts
- backup attestations
- restore drills

Where it comes from:

- `GET /v1/defense/incidents/runs`
- `GET /v1/defense/incidents/actions`
- `GET /v1/defense/webhooks/deliveries`
- `GET /v1/defense/backups/attest`
- `GET /v1/defense/backups/restore-drills`

What to say:

> "This is not a mock response screen. It is backed by the containment ledger. Every action and every receipt is stored as a record."

How to prove it changes:

- use `DDoS pressure`
- refresh `Defense`
- point to the latest `enable_waf_challenge` or `block_ip` record and the webhook delivery row

### `S8 Reports`

What it shows:

- generated preview for one prediction, entity, campaign, or bundle

Where it comes from:

- `GET /v1/reports/catalog`
- `POST /v1/reports/generate`

What to say:

> "The report is generated from the current backend subject, not typed into the UI. That is why I can choose a real entity and generate a new preview on demand."

How to prove it changes:

- choose `entity_investigation`
- set `entity_key = ip:50.16.16.211`
- click `Preview`
- the report content is generated from the current live backend state

### `A3 GNN Intelligence`

What it shows:

- latest training runs
- trust posture
- governance
- readiness

Where it comes from:

- `GET /v1/ai/gnn/runs`
- `GET /v1/ai/gnn/latest-runs`
- `GET /v1/ai/gnn/domain-health`
- `GET /v1/ai/trust/summary`

What to say:

> "This screen proves the model state is persisted and queryable. It is not just a chart in the frontend. The run history, governance fields, and trust summary all come from backend run records."

How to prove it changes:

- click `Prepare data + refresh model`
- open `GNN Intelligence`
- refresh
- show the newest run timestamp and window

### `A5 Corruption Intelligence`

What it shows:

- procurement anomalies
- payment controls
- integrity alerts
- leakage summary when available

Where it comes from:

- `GET /v1/economy/procurement/anomalies`
- `GET /v1/economy/guardrail/decisions`
- `GET /v1/economy/integrity/alerts`
- `GET /v1/economy/leakage/summary`

What to say:

> "This screen is sourced from the economy and integrity APIs. The procurement, guardrail, and integrity rows are real backend records. Leakage is a separate detector summary, so if it is quiet the screen now falls back to flagged procurement exposure instead of pretending there is no work."

How to prove it changes:

- refresh the screen
- point to real tender IDs like `TND-KE-2026-0001`
- explain that this lane is more static than cyber during a short demo, because it is showing procurement and integrity records rather than minute-by-minute DFIR intake

### `A6 Federation`

What it shows:

- partner roster
- partner freshness
- edge vs hub posture
- correlation view when present

Where it comes from:

- `GET /v1/federation/partners`
- `GET /v1/federation/stream`
- `GET /v1/federation/correlations`
- `GET /v1/federation/edge-status`

What to say:

> "This screen is reading the federation registry and current partner state. It is strongest for proving deployment and sovereignty, not for fast-changing attack visuals."

## The cleanest answer if they say "this looks seeded"

Use this:

> "Some of the demo scenarios are intentionally replayed so we can show a specific attack chain on demand, but they still go through the same ingest, graph, scoring, and reporting path as live data. Other screens, especially Live Feed, Dashboard, and parts of Investigate, are already backed by live external feeds and current backend records."

Then add:

> "So the honest distinction is not real versus fake. It is live external feed versus controlled replay through the same system path."

## Best short explanation of training data

Use this:

> "The model does not train directly on what you see on the screen. Raw events are normalized, linked into entities, converted into graph feature snapshots, then the GNN trains on those snapshots and writes predictions and explanations back to the workflow."

Key code:

- [real_data_pipeline.py](/home/ogola/personal/sentinel-ke/backend/app/integrations/real_data_pipeline.py)
- [graph_feature_worker.py](/home/ogola/personal/sentinel-ke/backend/app/analytics/layer3/graph_feature_worker.py)
- [gnn_backbone.py](/home/ogola/personal/sentinel-ke/backend/app/analytics/layer3/gnn_backbone.py)
- [gnn_model.py](/home/ogola/personal/sentinel-ke/backend/app/analytics/layer3/gnn_model.py)
- [gnn_train_worker.py](/home/ogola/personal/sentinel-ke/backend/app/analytics/layer3/gnn_train_worker.py)

## Best honest line to close with

> "The proof I want you to take away is that these screens are backed by backend records and can be refreshed, replayed, trained, and regenerated on demand. The UI is only the last layer."

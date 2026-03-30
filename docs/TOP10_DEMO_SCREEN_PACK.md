# Top 10 Demo Screen Pack

Last updated: 2026-03-30

This is the strongest live demo sequence for Sentinel-KE right now.

Use these screens in this order:

1. `C1 Command`
2. `S7 Dashboard`
3. `S1 Live Feed`
4. `S2 Threat Graph`
5. `S3 Investigate`
6. `S6 Defense`
7. `S8 Reports`
8. `A3 GNN Intelligence`
9. `A5 Corruption Intelligence`
10. `A6 Federation`

## Verified live proof

These checks passed against the current local stack:

- `GET /v1/metrics`
- `GET /v1/events/search`
- `GET /v1/campaigns`
- `GET /v1/ddos/alerts`
- `GET /v1/infra/clusters`
- `GET /v1/ai/predictions`
- `GET /v1/ai/trust/summary`
- `GET /v1/defense/incidents/actions`
- `GET /v1/defense/webhooks/deliveries`
- `POST /v1/reports/generate`
- `GET /v1/economy/procurement/anomalies`
- `GET /v1/federation/partners`

Operational notes:

- latest defense `enable_waf_challenge` run is now fresh and delivered with `http_status 200`
- corruption headline now falls back to flagged procurement exposure when leakage is quiet, so the screen does not open on a misleading zero

## Screen guide

### 1. `C1 Command`

Use it for:

- national posture
- readiness
- multi-agency framing

What should be visible:

- non-zero event volume
- non-zero campaign count
- AI trust headline
- partner and user posture

Say:

> "This is the national posture screen. It combines live operations, AI readiness, resilience, and agency coordination in one command view."

### 2. `S7 Dashboard`

Use it for:

- proving the platform is alive

Current live values:

- `events 76,900`
- `anomalies 110`
- `mitigations 468`
- `graph deltas 46,453`

Say:

> "This is the operational heartbeat. It proves the platform is ingesting signals, building graph state, and maintaining live queues."

### 3. `S1 Live Feed`

Use this entity:

- `ip:50.16.16.211`

Current live proof:

- `Feodo` finding on `50.16.16.211`
- `OTX` domain findings

Say:

> "This is the intake layer. These are live signals entering the platform now, not manually staged screenshots."

### 4. `S2 Threat Graph`

Best visual anchor:

- `service_id:ecitizen`

Supporting live proof:

- `ecitizen` -> `/login`
- active `VPN_IP_REUSE` campaign on `ip:50.16.16.211`
- infra cluster example: `vpn_exit`, endpoint overlap on `portal:/login:POST`

Say:

> "The graph is where isolated signals become an operational picture. It shows who is being targeted, by what infrastructure, and how those observations connect."

### 5. `S3 Investigate`

Use this entity:

- `ip:50.16.16.211`

Current live proof:

- `score 57.3`
- `severity medium`
- `kill-chain stage reconnaissance`
- `20 evidence hashes`
- `18 evidence paths`

Say:

> "This is where the AI becomes useful. The score is not a verdict. It is a priority signal backed by reasons, evidence, and caveats."

### 6. `S6 Defense`

Use this run:

- `demo:ecitizen:waf-challenge:refresh`

Current live proof:

- latest `enable_waf_challenge` action `executed`
- webhook `delivered`
- `http_status 200`

Say:

> "Containment here means a bounded control with a receipt, not panic shutdown. The system can route the action and prove that it landed."

### 7. `S8 Reports`

Use this report:

- `entity_investigation`
- `entity_key = ip:50.16.16.211`

Current live proof:

- report preview generated successfully
- title: `Entity Investigation Report — ip:50.16.16.211`

Say:

> "This closes the loop. Sentinel-KE does not stop at a score; it produces a readable, auditable output for investigators and supervisors."

### 8. `A3 GNN Intelligence`

Use it for:

- AI questions
- metrics
- governance

Current live proof:

- trust headline: `AI trust posture is usable with caveats`
- cyber governance `pass`
- corruption governance `pass`

Say:

> "This is not where I start the demo. This is where I answer how the model was trained, governed, and bounded."

### 9. `A5 Corruption Intelligence`

Best lead case:

- `TND-KE-2026-0001`
- `vendor-axon`
- `KEMSA`

Current live proof:

- flagged procurement exposure now leads the hero card when leakage is quiet
- live procurement anomalies: `4`
- guardrail decisions: `1`
- integrity alerts: `1`

Say:

> "This is an investigative risk screen, not a guilt screen. It helps reviewers connect tender anomalies, supplier patterns, payment controls, and open integrity reviews."

### 10. `A6 Federation`

Best proof to show:

- partner roster
- online/offline state
- hub vs edge explanation

Current live proof:

- `8` registered partners
- `Safaricom PLC` online with `11,129` patterns

Say:

> "This is the sovereignty and deployment screen. Agencies keep raw telemetry locally, and the hub correlates warning patterns rather than forcing raw-data centralization."

## Screens to avoid leading with

- `S4 Campaigns`
- `S5 Cases`
- `A8 Crisis Brief`

Use them only if a judge explicitly asks for them.

## Best short sequence for the live 10-minute demo

1. `Command`
2. `Dashboard`
3. `Live Feed`
4. `Threat Graph`
5. `Investigate`
6. `Defense`
7. `Reports`

Then use:

- `GNN Intelligence` for AI questions
- `Corruption Intelligence` for third-lane breadth
- `Federation` for deployment and sovereignty

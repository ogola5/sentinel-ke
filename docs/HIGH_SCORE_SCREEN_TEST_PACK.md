# High-Score Screen Test Pack

Last updated: 2026-03-30

This pack starts with the screens most likely to score well with judges because they are:

- backed by live data right now
- easy to explain in plain English
- close to the real operational claim of the system
- less likely to collapse into caveats or ambiguous visuals

Use this order first:

1. `S7 Operational Dashboard`
2. `S1 Live Feed`
3. `S3 Entity Investigation`
4. `S6 Defense`
5. `S8 Reports`
6. `S2 Threat Graph`

Do not open first:

- `S4 Campaigns`
- `S5 Cases`
- `GNN Intelligence` unless it has already loaded cleanly
- any screen that depends on a slow first-load sync if you have not refreshed it before judges arrive

## One-Minute Preflight

Run these before the demo so you know the strongest screens are backed by live data.

```bash
API_KEY=$(grep '^FRONTEND_API_KEY=' .env | cut -d= -f2)

curl -sS 'http://localhost:8000/v1/metrics' -H "X-API-Key: $API_KEY"
curl -sS 'http://localhost:8000/v1/events/search?size=5' -H "X-API-Key: $API_KEY"
curl -sS 'http://localhost:8000/v1/ai/predictions?prediction_type=risk_gnn&limit=5' -H "X-API-Key: $API_KEY"
curl -sS 'http://localhost:8000/v1/defense/incidents/runs?limit=5' -H "X-API-Key: $API_KEY"
curl -sS 'http://localhost:8000/v1/ai/benchmarks' -H "X-API-Key: $API_KEY"
```

If these five work, your strongest live story is intact.

## Screen 1: S7 Operational Dashboard

**Why this scores well**

- It proves the platform is ingesting and organizing live operational data.
- It is simple for judges to understand.
- It shows the mission loop before you dive into deeper graph or AI explanation screens.

**Live data already present**

- `events`: `71,101`
- `anomalies`: `110`
- `mitigations`: `468`
- `graph_deltas`: `40,655`

Source:

- `GET /v1/metrics`

**How to test**

1. Log in.
2. Open `Operational Dashboard`.
3. Stay on `Overview`.

**What should appear**

- `Signals ingested` should be a large non-zero value.
- `Cyber queue` should not be zero.
- `Integrity pressure` may be low or limited depending on session.
- `Leakage monitor` may be quiet or access-limited, which is acceptable if explained honestly.

**What it means**

- The platform is not just storing records.
- It is actively running a queueing and triage workflow.
- This is the best first proof that Sentinel-KE is operational, not just analytical.

**Judge-safe narration**

> "This screen tells us whether the system is actually alive operationally. Right now it has processed over seventy-one thousand events, built over forty thousand graph updates, and is maintaining live anomaly and mitigation queues."

## Screen 2: S1 Live Feed

**Why this scores well**

- It proves real feeds are arriving now.
- It is the easiest place to show malware and threat-intel ingestion without overclaiming endpoint compromise.
- It visually feels alive.

**Live data already present**

Recent live feed items include:

- `ip:50.16.16.211` from `Feodo Tracker`
- MalwareBazaar malware sample rows
- OTX domain indicators

Source:

- `GET /v1/events/search?size=20&event_type=DFIR_FINDING_EVENT`

**Best entity to use**

- `ip:50.16.16.211`

**How to test**

1. Open `Live Feed`.
2. Look for a recent `DFIR_FINDING_EVENT`.
3. Prefer a row anchored on `ip:50.16.16.211`.
4. Click it if the UI supports drill-down.

**What should appear**

- Recent high-severity cards from:
  - `feodo_tracker`
  - `malwarebazaar`
  - `alienvault_otx`
- A clear source label
- A recent timestamp
- Non-zero evidence or reference context

**What it means**

- The cyber lane is ingesting real OSINT and threat-intel signals.
- This is detection and enrichment input, not yet final attribution.
- It proves the system is connected to live external cyber intelligence.

**Judge-safe narration**

> "This is the intake surface. It shows that Feodo, MalwareBazaar, and OTX style signals are entering the system now. We do not treat a single feed hit as proof. We treat it as a live signal that can be correlated in the graph and scored."

## Screen 3: S3 Entity Investigation

**Why this scores well**

- This is the strongest explanation screen in the product.
- It combines AI score, reason codes, evidence posture, and recommended actions in one place.
- It is the best screen for explaining what the GNN is actually doing.

**Best entity to use**

- `ip:50.16.16.211`

**Live data already present**

For `ip:50.16.16.211`:

- score: `68.2775`
- confidence: `0.8933`
- uncertainty: `0.1067`
- kill-chain stage: `reconnaissance`
- top reasons:
  - `ABOVE_ENTITY_THRESHOLD`
  - `CAMPAIGN_LINKED`
  - `EVENT_VOLUME_HIGH`
  - `GNN_RISK_ELEVATED`
  - `RISK_INDICATOR_ONLY_NOT_FINAL_PROOF`
- evidence hashes: at least `20`
- recommended controls:
  - `D3-AUDIT`
  - `D3-EVIDENCE`
  - `D3-INV`
  - `D3-TDS`
- top feature: `log_degree`

Sources:

- `GET /v1/ai/predictions?prediction_type=risk_gnn&limit=20`
- `GET /v1/ai/explanations/{prediction_id}`

**How to test**

1. Open `Investigate`.
2. Search `ip:50.16.16.211`.
3. Open the entity.

**What should appear**

- A non-zero risk score around `68`
- The entity marked as an investigative indicator, not final proof
- Reason codes
- Evidence counts or hashes
- Recommended controls
- Trust or explanation summary

**What it means**

- The GNN is not just outputting a raw score.
- It is using graph structure and event volume to prioritize the entity.
- The explanation layer is keeping the output auditable and bounded.

**How to explain the graph meaning here**

- `log_degree` means the entity is highly connected in the graph.
- `CAMPAIGN_LINKED` means the entity is structurally associated with an active campaign grouping.
- `EVENT_VOLUME_HIGH` means this node is supported by repeated observations, not a one-off hit.

**Judge-safe narration**

> "This is where the AI becomes operationally useful. The score is not a verdict. It is a priority signal. The model is saying this IP is risky because it is highly connected, repeatedly observed, and campaign-linked. We can trace that through reason codes and evidence hashes."

## Screen 4: S6 Defense

**Why this scores well**

- It proves the platform can move from analysis to bounded action.
- It is the strongest operational claim screen after Entity Investigation.
- It shows that containment is logged and not treated as magic.

**Best incidents to use**

- `service_id:ecitizen`
- `demo:ecitizen:waf-challenge`

**Live data already present**

Incident runs:

- `service_id:ecitizen` completed
- `demo:ecitizen:waf-challenge` completed

Containment actions already recorded:

- `enable_waf_challenge` on `service_id:ecitizen` -> `executed`
- `block_ip` on `203.0.113.1` -> `executed`
- external partner simulator route:
  - `http_status`: `200`
  - `webhook_status`: `delivered`

Recovery proof:

- backup attestation healthy for `sentinel-primary-db`
- restore drill success with `rto_actual_minutes: 180`

Sources:

- `GET /v1/defense/incidents/runs?limit=5`
- `GET /v1/defense/incidents/actions?limit=10`
- `GET /v1/defense/backups/attest?limit=3`
- `GET /v1/defense/backups/restore-drills?limit=3`

**How to test**

1. Open `Defense`.
2. Select the `ecitizen` run if visible.
3. Show the executed actions list.
4. Show backup attestation and restore drill if available in the same screen.

**What should appear**

- A completed incident run
- Executed action history
- One or more delivery or execution receipts
- Recovery evidence, not only blocking actions

**What it means**

- Sentinel-KE is not only detecting and explaining.
- It is routing bounded response actions with receipts.
- The platform also addresses recoverability, not just suppression.

**Judge-safe narration**

> "Containment does not mean shutting the internet off. It means using the least disruptive control that still protects the service. Here we can show a WAF challenge and IP block being dispatched and logged, and separately show that recovery evidence exists."

## Screen 5: S8 Reports

**Why this scores well**

- It closes the loop with a shareable, auditable output.
- It translates technical findings into human-readable reporting.
- It is useful for judges who care about supervision, audit, and public-sector workflow fit.

**Live data already present**

Report catalog includes:

- `incident_brief`
- `entity_investigation`
- `campaign_case`
- `ai_decision_explanation`
- `model_governance`

Source:

- `GET /v1/reports/catalog`

**Best report to use**

- `entity_investigation`
- entity key: `ip:50.16.16.211`

**How to test**

1. Open `Reports`.
2. Choose `Entity Investigation Report`.
3. Set entity key to `ip:50.16.16.211`.
4. Click preview first.

**What should appear**

- Executive summary
- findings
- governance section
- limitations or caveats
- download/export option

**What it means**

- The system can turn an AI-assisted investigation into an output a human can review or pass onward.
- This is important for command, oversight, and inter-agency handoff.

**Judge-safe narration**

> "This is how the platform leaves the analyst screen and becomes usable operationally. We can generate a human-readable investigation report with evidence, governance context, and caveats still attached."

## Screen 6: S2 Threat Graph

**Why this scores well**

- It proves the platform is not just alert-based.
- It shows correlation structure, which is the core reason for using a graph and GNN.
- It is especially good for explaining VPN reuse and clustered infrastructure.

**Best live data to use**

Campaign:

- `VPN_IP_REUSE`
- primary key: `ip:50.16.16.211`
- event count: `44`

Infra cluster:

- `vpn_exit`
- cluster id: `bbb8d7c2-ee52-4fd2-beea-a99e5c7213be`
- endpoint: `portal:/login:POST`
- `member_count`: `6`
- provider: `demo-vpn`

Sources:

- `GET /v1/campaigns?limit=3`
- `GET /v1/campaigns/{campaign_id}`
- `GET /v1/infra/clusters/{cluster_id}`

**How to test**

1. Open `Threat Graph`.
2. Use `Focus entity` if present.
3. Enter `50.16.16.211` or `ip:50.16.16.211`.
4. Click the selected node and inspect side panels.

**What should appear**

- Attack-infrastructure style nodes
- campaign grouping
- node or edge detail that links the IP to repeated observed events
- live neighbour or path detail if clicked

**What it means**

- The graph is how Sentinel-KE turns repeated indicators into structured relationships.
- The GNN then uses this structure to prioritize entities that are central, repeated, and connected.

**Judge-safe narration**

> "This screen shows why we are using a graph. We are not only collecting alerts. We are connecting entities, infrastructure, and campaigns into a structure the model can reason over."

## Bonus Screen: GNN Intelligence

Use this only if it loads cleanly before demo.

**Why it helps**

- It strengthens the scientific credibility of the AI story.
- It is useful if judges ask directly about model performance and baselines.

**What to point to**

- `PaySim fraud benchmark` from `GET /v1/ai/benchmarks`
- live `risk_gnn` predictions from `GET /v1/ai/predictions`
- health summary from `GET /health`

**Current live evidence**

- PaySim benchmark:
  - `AUC 0.9555`
  - `PR-AUC 0.9291`
  - `F1 0.2224`
- health:
  - `gnn_loaded: true`
  - current health model summary reflects the most recently loaded lane

**Do not use this as the opening screen**

- It is more technical than the dashboard and easier to over-explain.

## Screens To Treat As Secondary

These are not bad screens. They are just not the best opening proof screens right now.

- `S4 Campaigns`
  - useful after Threat Graph, not before it
- `S5 Cases`
  - useful as a handoff surface, not as opening operational proof
- `C1 Command / ExecBrief`
  - useful for leadership framing if it is already loaded cleanly
  - do not rely on it as your first technical proof if your session is cold

## Best 5-Screen Sequence

If you need the strongest possible proof path with minimum risk:

1. `Operational Dashboard`
2. `Live Feed`
3. `Entity Investigation`
4. `Defense`
5. `Reports`

That sequence proves:

- ingest
- live signal flow
- graph/GNN explanation
- bounded containment
- auditable output

That is the cleanest operational story in the product today.

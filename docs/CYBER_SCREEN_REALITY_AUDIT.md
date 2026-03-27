# Cyber Screen Reality Audit

Last updated: 2026-03-27

This document answers one question:

`If Sentinel-KE is presented as a national cyber operations MVP for Kenya, which screens already support a real claim for cyber / VPN / DDoS / malware, and what is still missing?`

The focus here is the cyber lane only:

- DDoS detection and response
- VPN-style login abuse and infrastructure reuse
- Malware / threat-intel correlation
- Blocking, isolation, and recovery proof

It does **not** treat fraud or corruption as the main story, except where they affect shared platform credibility.

## Live Smoke Summary

Stack status when this audit was written:

- `backend`: healthy
- `frontend`: running
- `neo4j`, `opensearch`, `postgres`, `redpanda`: running
- cyber workers: running
- OSINT workers:
  - `otx-ingest-worker`: active and ingesting
  - `feodo-ingest-worker`: active
  - `urlhaus-ingest-worker`: clean skip without auth key
  - `threatfox-ingest-worker`: clean skip without auth key
  - `malwarebazaar-ingest-worker`: clean skip without auth key

Live API / runtime evidence gathered during smoke:

- `/health` = `ok`
- `/v1/metrics` returned:
  - `events: 57837`
  - `graph_deltas: 27495`
  - `anomalies: 94`
  - `mitigations: 430`
- `/v1/anomalies?limit=3` returned live anomaly rows
- `/v1/ddos/alerts?limit=3` returned live DDoS alert rows
- `/v1/infra/clusters?limit=3` returned live infrastructure clusters
- `/v1/cases/recent?limit=3` returned recent case rows
- `/v1/campaigns?limit=3` returned campaign rows
- `/v1/ai/predictions?limit=3` returned prediction rows
- `/v1/defense/actions/catalog` includes:
  - `freeze_account`
  - `hold_cashout`
  - `suspend_sim_change`

Important cyber truth at the moment:

- the latest `risk_gnn` domain health is `warn`
- the current latest cyber run is operationally active but not scientifically clean enough to be your strongest “real data” proof
- current `/health` shows:
  - `real_data_gate_passed: false`
  - `real_ratio: 0.0`

That means:

- the cyber lane is useful and live
- but the newest `Wmid` window is currently OSINT-heavy, not sovereign partner telemetry heavy

So the strongest cyber claim today is:

- `real operational cyber graph intelligence is running`

Not:

- `the latest cyber GNN is already trained mainly on sovereign partner telemetry`

## Screen-by-Screen Audit

### C1 Command

Primary question it should answer:

- `What is the national cyber posture right now, and can I trust the platform enough to keep going?`

Primary backend dependencies:

- `/v1/ai/judge-readiness`
- `/v1/ai/gnn/domain-health`
- `/v1/federation/partners`
- `/v1/defense/incidents/runs`
- platform / trust APIs consumed by [ExecBrief.tsx](/home/ogola/personal/sentinel-ke/frontend/src/screens/command/ExecBrief.tsx)

What is real now:

- it already distinguishes operational truth from scientific truth
- it already shows live queue size versus benchmark evidence
- it already exposes caveats and guardrails

What is still missing:

- the cyber card needs to be treated as `ready with caveats`, not strongest-proof lane, whenever `real_data_gate_passed` is false
- if you demo this screen, you must verbally say the latest cyber window is OSINT-enriched

Verdict:

- `Strong judge screen`
- but only if presented honestly

### S1 Live Feed

Primary question it should answer:

- `What is arriving right now, and what needs review first?`

Primary backend dependencies:

- event / anomaly / indicator feeds used by [LiveFeed.tsx](/home/ogola/personal/sentinel-ke/frontend/src/screens/LiveFeed.tsx)
- live event and anomaly routes behind the app data layer

What is real now:

- good for showing DDoS pressure, suspicious login bursts, and threat-intel findings entering the system
- suitable to show:
  - `DDOS_SIGNAL_EVENT`
  - `LOGIN_EVENT`
  - `DFIR_FINDING_EVENT`

What is still missing:

- malware-specific language should be more explicit for operators
- the drawer should more visibly distinguish:
  - service pressure
  - login abuse
  - malware / IOC intelligence

Verdict:

- `Good demo screen`
- especially for DDoS burst + VPN-login stories

### S2 Threat Graph

Primary question it should answer:

- `Who is attacking whom, through what infrastructure, and under which campaign grouping?`

Primary backend dependencies:

- overview snapshot assembly from frontend backend client
- live graph APIs for path and neighbours
- graph projection from Neo4j / graph workers

What is real now:

- useful for visualizing:
  - target services / endpoints
  - attacking IPs / infra
  - grouped campaign nodes
- focus mode helps isolate one target such as `kplc`

What is still missing:

- malware story is not first-class here yet
- VPN cluster meaning is clearer in `Infra Correlation` than in this graph
- some campaign / component naming still remains more technical than operator-friendly

Best demo use:

- show DDoS or coordinated login abuse here
- do not use this as the first screen for malware unless you already have malware-linked infra in the graph

Verdict:

- `Good for cyber relationship proof`
- strongest when paired immediately with `Investigate`

### S3 Investigate

Primary question it should answer:

- `Why is this entity risky, what evidence supports it, and what should I do next?`

Primary backend dependencies:

- `/v1/ai/predictions`
- `/v1/ai/explanations/...`
- path / fusion / trust summary APIs
- containment action APIs

What is real now:

- strongest single-entity screen for cyber
- good for:
  - DDoS target service
  - suspicious IP
  - endpoint under pressure
  - VPN-linked node
- now supports more realistic fraud-response suggestions as well

What is still missing for cyber:

- malware evidence should be more explicit when the entity is an IOC or malware-linked IP/hash
- some entities still lack graph path support even when model score exists

Best demo use:

- DDoS target service investigation
- one attacker IP
- one suspicious VPN-linked IP

Verdict:

- `Best cyber explanation screen in the product right now`

### S4 Campaigns

Primary question it should answer:

- `How did multiple related alerts become one coordinated operation?`

Primary backend dependencies:

- `/v1/campaigns`
- `/v1/campaigns/{id}`
- `/v1/campaigns/{id}/events`
- `/v1/campaigns/{id}/risk`
- `/v1/campaigns/{id}/evidence`

What is real now:

- structurally good for GNN-component campaigns and grouped cyber operations
- can show:
  - shared infra
  - affected entities
  - blast radius

What is still missing:

- for cyber campaigns, evidence materialization is still thinner than the grouping logic
- malware campaigns are not yet as rich as DDoS/login-abuse campaigns

Best demo use:

- use after `Threat Graph` or `Investigate`
- frame it as “operation grouping,” not prosecution or attribution certainty

Verdict:

- `Good but still evidence-thin`

### S5 Cases

Primary question it should answer:

- `Can I package this operation into an evidence-backed handoff?`

Primary backend dependencies:

- `/v1/cases/recent`
- `/v1/cases/from-campaign/{id}`
- export flows

What is real now:

- case packet generation works
- integrity / hash story exists
- useful for legal / supervisor handoff

What is still missing:

- cyber cases need denser evidence rows and graph edge packaging
- for a powerful malware demo, the case should contain:
  - IOC list
  - linked hosts / services
  - reason codes
  - containment receipt

Verdict:

- `Export-ready concept is real`
- but cyber evidence density still needs improvement

### S6 Defense

Primary question it should answer:

- `Can the platform actually block, isolate, or recover, and can it prove what happened?`

Primary backend dependencies:

- `/v1/defense/incidents/runs`
- `/v1/defense/incidents/actions`
- `/v1/defense/actions/catalog`
- `/v1/defense/incidents/runs/{run_id}/actions`
- backup / restore / vulnerability routes

What is real now:

- real action surface exists
- DDoS / cyber actions are present:
  - `enable_waf_challenge`
  - `rate_limit_service`
  - `reroute_to_scrubber`
  - `block_ip`
  - `isolate_host`
- fraud actions are now present too:
  - `freeze_account`
  - `hold_cashout`
  - `suspend_sim_change`

What is still missing for national cyber proof:

- actual live success depends on matching registered webhooks
- without WAF / ISP / EDR integration, the action is recommendation or dry-run, not operational delivery
- recovery proof is still lighter than detection / containment proof

Best demo use:

- DDoS containment with WAF challenge or scrubber path
- host isolation for malware / beacon case

Verdict:

- `Operationally convincing if webhook integrations are real`
- otherwise it is `response orchestration with dry-run proof`

### S7 Dashboard

Primary question it should answer:

- `What is the current operational picture across predictions, anomalies, and mitigations?`

Primary backend dependencies:

- `/v1/metrics`
- `/v1/anomalies`
- `/v1/mitigations`
- `/v1/ai/predictions`

What is real now:

- this is a good operational triage dashboard
- it already has enough live rows to support a real demo

What is still missing:

- malware needs a more explicit operational tile
- VPN abuse could use a dedicated queue or badge instead of blending into generic predictions

Verdict:

- `Strong operations screen`
- especially for cyber pressure and queue management

### S8 Reports

Primary question it should answer:

- `Can the system explain itself clearly to operators, leadership, and oversight?`

Primary backend dependencies:

- `/v1/reports/catalog`
- `/v1/reports/generate`
- `/v1/reports/download`

What is real now:

- report types are real and well-structured
- operator-friendly language exists
- good support for:
  - incident brief
  - entity investigation
  - AI explanation
  - model governance

What is still missing:

- malware and DDoS-specific templates could be even sharper
- one dedicated `national cyber incident report` type would strengthen judge demos

Verdict:

- `Very useful and already convincing`

### A2 Infra Correlation

Primary question it should answer:

- `What shared infrastructure is being reused across multiple entities or attacks?`

Primary backend dependencies:

- `/v1/infra/clusters`
- `/v1/infra/clusters/{id}`

What is real now:

- strongest screen for VPN-style infra reuse
- useful for:
  - Tor / VPN exit reuse
  - shared provider patterns
  - endpoint overlap

What is still missing:

- malware / C2 cluster labeling should be more explicit
- cluster provenance should distinguish:
  - live telemetry
  - OSINT intelligence
  - benchmark-only grouping

Verdict:

- `Best current screen for VPN abuse demonstration`

### A3 GNN Intelligence

Primary question it should answer:

- `How does the graph model work, and how honest is the evidence?`

Primary backend dependencies:

- `/v1/ai/predictions`
- `/v1/ai/gnn/latest-runs`
- `/v1/ai/gnn/scientific-summary`
- training / review / rehearsal APIs

What is real now:

- this screen already separates operational truth from scientific truth
- that is exactly what you need in front of judges

What is still missing:

- the latest cyber lane should be treated carefully whenever:
  - `real_data_gate_passed` is false
  - `real_ratio` is near zero
- do not use this screen to pretend the newest cyber run is your cleanest scientific claim

Best demo use:

- use it to show:
  - how the GNN reasons
  - why some lanes are strong
  - why some lanes are still caveated

Verdict:

- `Excellent honesty screen`
- not your first wow screen, but one of your most credible ones

## Dataset and Practicality Assessment

### DDoS

Current practicality:

- `High`

What is already practical:

- synthetic / replay attack injection
- real DDoS telemetry schema
- alerting
- graph linking
- GNN prioritization
- containment orchestration

Best datasets / sources:

- your live DDoS signal schema and replay scenarios
- CICDDoS / CAIDA-style benchmark traces for external benchmark support
- real partner edge / WAF / CDN telemetry for strongest claim

Best current claim:

- `Sentinel-KE can detect DDoS pressure, correlate attack infrastructure, score affected entities, and route containment.`

### VPN Abuse

Current practicality:

- `Medium to high`

What is already practical:

- login-event ingestion
- infra clustering
- provider / ASN reuse
- graph correlation

Best datasets / sources:

- UNB ISCX VPN-nonVPN benchmark
- real VPN gateway or IdP logs
- real telco or enterprise access logs if available

Best current claim:

- `Sentinel-KE can detect and correlate suspicious VPN-style login reuse and shared masking infrastructure.`

### Malware Detection

Current practicality:

- `Medium`

What is already practical:

- OSINT threat-intel ingestion via OTX now
- abuse.ch feeds ready in code
- malware-intel entities can enrich graph and investigations
- host isolation action exists

What is still missing:

- live `ABUSECH_AUTH_KEY` to unlock URLhaus, ThreatFox, MalwareBazaar
- better malware-first UI language
- stronger endpoint / host telemetry if you want a true national EDR/XDR demo

Best datasets / sources:

- OTX
- ThreatFox
- MalwareBazaar
- URLhaus
- EMBER for labeled malware benchmark work

Best current claim:

- `Sentinel-KE can incorporate live malware threat intelligence into the graph and response workflow.`

Not yet:

- `Sentinel-KE is a full national malware sandbox/EDR platform`

## Blocking, Isolation, and Recovery Reality

### Blocking / Throttling

Already credible:

- `enable_waf_challenge`
- `rate_limit_service`
- `reroute_to_scrubber`
- `block_ip`

This becomes operationally real only when the corresponding webhook or partner control plane is active.

### Isolation

Already credible:

- `isolate_host`

This is strong for malware or beacon scenarios if you connect it to a real EDR / host agent / network quarantine path.

### Recovery

Partially credible:

- backup attestation
- restore drill evidence

Still missing:

- a stronger visible recovery storyline after containment
- example:
  - attacked service degraded
  - containment applied
  - recovery check / restore proof shown in UI

## What You Can Demo Convincingly Today

1. `DDoS on a public service`
- S1 Live Feed
- S2 Threat Graph
- S3 Investigate
- S6 Defense
- S7 Dashboard

2. `VPN-style suspicious login reuse`
- S1 Live Feed
- A2 Infra Correlation
- S2 Threat Graph
- S3 Investigate

3. `Malware-intel enrichment and response`
- S1 Live Feed
- S3 Investigate
- S6 Defense
- S8 Reports

This one gets much stronger the moment `ABUSECH_AUTH_KEY` is added.

## Biggest Missing Pieces Before a Top-Tier National Demo

1. Add `ABUSECH_AUTH_KEY` to `.env`
- this unlocks URLhaus, ThreatFox, and MalwareBazaar

2. Do not present the newest cyber `Wmid` run as sovereign-telemetry proof
- right now the latest run is useful, but OSINT-heavy

3. Add or connect one real containment integration
- WAF
- CDN
- ISP scrubber
- host isolation agent

4. Strengthen malware-first analyst flow
- IOC -> host/service impact -> isolate -> report

5. Strengthen recovery proof
- show service restoration or restore drill after containment

## Final Verdict

Sentinel-KE is already practical enough to deliver a powerful cyber demo if you stay inside the honest claim boundary.

The most convincing cyber path today is:

- DDoS detection
- graph correlation
- GNN-assisted prioritization
- operator explanation
- containment dispatch

The strongest near-term upgrade is:

- activate abuse.ch feeds with one shared `ABUSECH_AUTH_KEY`
- then use OTX + ThreatFox + MalwareBazaar + URLhaus together to enrich malware and IOC stories

That would tighten the cyber lane materially without pretending the platform is something it is not.

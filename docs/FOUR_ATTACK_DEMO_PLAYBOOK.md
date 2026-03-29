# Four-Attack Demo Playbook

Last updated: 2026-03-30

This playbook explains how to demonstrate these four attack families in Sentinel-KE:

- `DDoS`
- `Malware`
- `VPN abuse`
- `SIM swap / fraud chain`

The key rule is:

Do not try to prove all four in the same way.

Each attack family has a different strongest proof path in the current system.

## The Honest Demo Position

### Strongest end-to-end operational proof

- `DDoS`

### Strongest live cyber-intelligence proof

- `Malware`
- `VPN abuse`

### Strongest controlled fraud replay proof

- `SIM swap`

So the correct framing is:

- `DDoS` proves full mission loop
- `Malware` proves live intake + graph correlation + investigation
- `VPN` proves infrastructure reuse + clustering + graph reasoning
- `SIM swap` proves fraud-chain modeling + bounded fraud containment actions

## The Four Claims To Use

### DDoS

> `Sentinel-KE can ingest DDoS pressure, detect it, relate attacker infrastructure in the graph, score the target with the GNN, and route bounded containment with receipts.`

### Malware

> `Sentinel-KE can ingest live malware and IOC intelligence, relate it in the graph, score linked entities, and move the case into investigation and response.`

### VPN abuse

> `Sentinel-KE can detect and correlate suspicious VPN-style login reuse and shared masking infrastructure.`

### SIM swap

> `Sentinel-KE can model a SIM-swap fraud chain from SIM change to suspicious login to transfer to mule to cash-out controls.`

## Claims To Avoid

### DDoS

- `The GNN alone detected the DDoS.`

### Malware

- `One ThreatFox or MalwareBazaar hit proves a host is compromised.`
- `Sentinel-KE is already a full national EDR or malware sandbox.`

### VPN abuse

- `VPN traffic is automatically malicious.`
- `The system identifies the real legal owner from VPN logs alone.`

### SIM swap

- `This proves live Kenyan telco production fraud detection.`
- `This identifies the legal owner without subscriber or KYC systems.`

## Demo Order

If you have time for all four, use this order:

1. `DDoS`
2. `Malware`
3. `VPN abuse`
4. `SIM swap`

Reason:

- `DDoS` is the strongest operational claim
- `Malware` and `VPN` strengthen live cyber credibility
- `SIM swap` is powerful, but should be framed as a controlled fraud-chain replay unless you have partner feeds

## 1. DDoS Demonstration

### Best proof type

- full end-to-end operational proof

### Best entity

- `service_id:ecitizen`

### Best screens

1. `Operational Dashboard`
2. `Live Feed`
3. `Threat Graph`
4. `Entity Investigation`
5. `Defense`
6. `Reports`

### Best backend evidence

- `/v1/anomalies`
- `/v1/ddos/alerts`
- `/v1/ai/predictions`
- `/v1/graph/path`
- `/v1/defense/incidents/runs`
- `/v1/defense/incidents/actions`

### What to show

- DDoS alert on `ecitizen /login`
- anomaly reasons such as:
  - `ENDPOINT_CONVERGENCE`
  - `ERROR_RATE_UP`
  - `LATENCY_UP`
- a graph path from target service to attacker infrastructure
- a GNN prediction on the target or linked attacker entity
- executed response actions such as:
  - `enable_waf_challenge`
  - `block_ip`

### What it means

- telemetry entered the system
- detection happened
- graph correlation happened
- model prioritization happened
- containment happened
- the result was logged

### Best line to say

> `This is our strongest operational proof because the same run shows ingestion, detection, graph correlation, model scoring, containment, and audit evidence.`

## 2. Malware Demonstration

### Best proof type

- live cyber-intelligence enrichment and correlation

### Best live entity

- `ip:50.16.16.211`

### Best live feeds already present

- `Feodo`
- `ThreatFox`
- `MalwareBazaar`
- `OTX`

### Best screens

1. `Live Feed`
2. `Entity Investigation`
3. `Threat Graph`
4. `Reports`

### Best backend evidence

- `/v1/events/search?event_type=DFIR_FINDING_EVENT`
- `/v1/ai/predictions?prediction_type=risk_gnn`
- `/v1/ai/explanations/{prediction_id}`

### What to show

- a live IOC or malware-intel row from:
  - `feodo_tracker`
  - `malwarebazaar`
  - `threatfox`
- `ip:50.16.16.211` as the investigation target
- a real GNN score and reason codes
- evidence hashes on the explanation record

### What it means

- the system is ingesting live malware-related intelligence
- it is turning those indicators into graph-linked entities
- the GNN is prioritizing the riskiest linked entities
- the analyst can move into investigation and reporting

### What it does **not** mean

- that one IOC equals a confirmed infection
- that the platform has already performed deep sandbox malware detonation

### Best line to say

> `For malware, Sentinel-KE is strongest today as a live intelligence and correlation system. It turns IOC and malware-sample feeds into connected graph intelligence and explainable analyst queues.`

## 3. VPN Abuse Demonstration

### Best proof type

- infrastructure reuse and suspicious access correlation

### Best screens

1. `Threat Graph`
2. `Infra Correlation`
3. `Entity Investigation`

### Best current live examples

- campaign type: `VPN_IP_REUSE`
- example campaign primary key: `ip:50.16.16.211`
- example infra cluster kind: `vpn_exit`

### Best backend evidence

- `/v1/campaigns`
- `/v1/campaigns/{campaign_id}`
- `/v1/infra/clusters`
- `/v1/infra/clusters/{cluster_id}`

### What to show

- a `VPN_IP_REUSE` campaign
- a `vpn_exit` cluster
- repeated use of a provider or endpoint overlap
- linked attacker-side nodes in the graph

### What it means

- the system can see repeated login activity through shared masking infrastructure
- the graph lets you connect multiple observations into one infrastructure story
- the GNN can then prioritize the central or campaign-linked nodes

### What it does **not** mean

- that all VPN activity is malicious
- that the VPN itself proves attribution

### Best line to say

> `Here we are not proving that VPN use is malicious by itself. We are proving that Sentinel-KE can correlate repeated login activity through shared masking infrastructure and elevate that pattern for analyst review.`

## 4. SIM Swap Demonstration

### Best proof type

- controlled fraud-chain replay

### Best screens

1. `Live Feed`
2. `Threat Graph`
3. `Entity Investigation`
4. `Defense`

### Best event chain

1. `SIM_SWAP_EVENT`
2. `LOGIN_EVENT`
3. `TRANSACTION_EVENT`
4. second `TRANSACTION_EVENT` to another mule or agent

### Existing guidance

Use the controlled replay from:

- [FRONTEND_ATTACK_TEST_GUIDE.md](/home/ogola/personal/sentinel-ke/docs/FRONTEND_ATTACK_TEST_GUIDE.md)

That guide already contains the attack injection for:

- SIM swap
- suspicious login from Tor/VPN-like IP
- transfer to mule account
- second transfer / cash-out pattern

### Best defense actions to show

- `suspend_sim_change`
- `freeze_account`
- `hold_cashout`

These are already mapped in:

- [DefenseCenter.tsx](/home/ogola/personal/sentinel-ke/frontend/src/screens/respond/DefenseCenter.tsx)
- [EntityInvestigation.tsx](/home/ogola/personal/sentinel-ke/frontend/src/screens/EntityInvestigation.tsx)

### What it means

- the system can model a multi-step fraud chain
- different entity types can trigger different fraud controls
- this is where graph reasoning matters more than a single event classifier

### What it does **not** mean

- that you already have national telco production ground truth
- that you can identify the legal owner without subscriber or KYC data

### Best line to say

> `For SIM swap, the system is strongest as a fraud-chain reasoning workflow: SIM change, suspicious access, transfer, and cash-out can be connected and then matched to bounded fraud actions.`

## The Simple Story For Judges

If a judge asks how all four fit together, say this:

> `DDoS proves the full operational loop. Malware proves live threat-intel correlation. VPN proves infrastructure reuse detection. SIM swap proves fraud-chain reasoning and domain-specific response actions.`

That is the cleanest high-intelligence answer.

## Which Screen Fits Which Attack

| Attack | Best first screen | Best explanation screen | Best response screen |
|---|---|---|---|
| DDoS | `Operational Dashboard` | `Entity Investigation` | `Defense` |
| Malware | `Live Feed` | `Entity Investigation` | `Reports` or `Defense` |
| VPN abuse | `Threat Graph` or `Infra Correlation` | `Entity Investigation` | `Defense` if actionable |
| SIM swap | `Live Feed` | `Entity Investigation` | `Defense` |

## Recommended Practical Demo

If you want the strongest 10-minute cyber-heavy demo:

1. Lead with `DDoS`
2. Pivot briefly to `Malware`
3. Show `VPN` as graph correlation
4. Only show `SIM swap` if time allows or if asked

Reason:

- `DDoS` is the strongest operational claim
- `Malware` is the easiest live feed story
- `VPN` is the cleanest graph story
- `SIM swap` is powerful, but should be framed as a controlled fraud replay unless partner feeds are live

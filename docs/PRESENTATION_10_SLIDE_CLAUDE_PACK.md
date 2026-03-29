# Sentinel-KE 10-Slide Claude Pack

Last updated: 2026-03-29

This is the judge-safe 10-slide presentation pack for Sentinel-KE.

Use it for:

- Claude or Gamma slide generation
- 5-minute verbal delivery
- keeping slide claims aligned to the live system and the scoring rubric

This pack is built around the current strongest evidence:

- live cyber lane with matched benchmark evidence
- fresh PaySim fraud benchmark artifact
- real corruption risk lane with caveats
- signed external containment workflow demonstrated through a partner control plane
- strong governance, auditability, and sovereignty story

## Judge Positioning

The winning framing is:

> "Sentinel-KE is a sovereign intelligence workflow for Kenya. It ingests real signals, correlates them in a graph, scores them with GNNs, explains them with evidence, and routes bounded containment with audit receipts."

Do not frame it as:

- one model that detects everything
- legal proof engine
- finished national deployment
- benchmark metrics that equal live national ground truth

## Paste-Ready Claude / Gamma Prompt

```text
Create a 10-slide PowerPoint for Sentinel-KE, a sovereign Kenyan security intelligence platform. The deck must feel executive, operational, and evidence-led. The audience is judges evaluating execution maturity, deployment readiness, technical robustness, operational fit, national relevance, and trust/governance.

The deck must communicate one clear story:
Sentinel-KE ingests real signals, correlates them in a graph, scores them with GNNs and ML, explains the result with evidence, and routes bounded containment with audit receipts.

Tone:
- authoritative
- plain English
- technical but understandable
- Kenya-relevant
- judge-safe
- no hype

Visual style:
- premium national-security feel
- dark navy, green, gold, neutral gray
- high contrast
- structured data cards
- clean diagrams
- restrained motion or flourish
- no generic AI visuals
- no purple SaaS aesthetic

Hard constraints:
- Do not claim the GNN alone detects everything.
- Do not present corruption outputs as legal proof.
- Do not present PaySim as live sovereign fraud telemetry.
- Do not imply a public production deployment unless explicitly shown.
- Do not present partner simulator containment as if it were already a commercial CDN or EDR partner.
- Keep language evidence-led and operational.

Required live evidence themes:
- cyber lane is strongest and live
- latest matched cyber run includes AUC 0.9682, precision 0.7538, recall 0.6533, F1 0.7000
- recent cyber scientific evidence is strong across benchmarkable windows
- PaySim fraud benchmark is fresh: AUC 0.9555, PR-AUC 0.9291, precision 0.1251, recall 1.0, F1 0.2224
- corruption lane is real and useful: AUC 0.9158, precision 0.9759, recall 0.7297, F1 0.8351
- eCitizen-style DDoS operational proof shows telemetry ingested, graph related, GNN scored, containment dispatched, containment logged
- signed external containment workflow exists with receipt logging
- privacy, auditability, and governance are major differentiators

Required output format:
For each of 10 slides provide:
1. slide title
2. 3-5 concise bullets
3. 1 short speaker note paragraph
4. 1 recommended visual
5. 1 metric, screenshot, or proof item that must appear on the slide

Use this slide order:
1. Sentinel-KE in one sentence
2. Kenya’s national security problem
3. How Sentinel-KE works end to end
4. Cyber lane: live operational proof
5. Fraud lane: SIM swap, mule rings, VPN, and PaySim benchmark
6. Corruption lane: procurement and integrity intelligence
7. Technical architecture: graph, GNN, evidence, containment
8. Deployment and integration: agencies, legacy systems, sovereignty
9. Trust, governance, and auditability
10. Closing and concrete ask

Keep every slide defensible under questioning from cyber judges, AI judges, and public-sector judges.
```

## 10-Slide Structure

### Slide 1

**Title**

`Sentinel-KE: Sovereign security intelligence for Kenya`

**Bullets**

- One platform for cyber, fraud, and corruption intelligence
- Ingest -> graph -> GNN -> evidence -> containment -> report
- Built for Kenyan agencies, critical services, and federated response
- Strongest live proof today is cyber plus bounded containment

**Speaker note**

Open with the mission, not the UI. Say Sentinel-KE is an operational workflow, not a dashboard and not a standalone AI model.

**Recommended visual**

Hero slide with a simple six-stage workflow strip and a Kenya-facing command-center aesthetic.

**Proof to show**

- one evidence band with `cyber live`, `PaySim fresh`, `governance visible`

**What not to say**

- do not say the entire platform is fully proven equally across all lanes

### Slide 2

**Title**

`Why Kenya needs this now`

**Bullets**

- Critical public services and financial systems are increasingly digital
- Security teams still face fragmented telemetry, slow triage, and weak cross-system correlation
- Fraud and integrity risks move across identities, accounts, devices, contracts, and services
- In a digital state, response delay becomes a national resilience problem

**Speaker note**

Anchor the problem in operational consequences: service disruption, fraud movement, delayed response, and low coordination across agencies.

**Recommended visual**

Three-column problem slide: public services, financial abuse, procurement integrity.

**Proof to show**

- one Kenya-specific target strip: `eCitizen`, `KRA`, `M-Pesa-style fraud`, `PPRA/OCDS`

### Slide 3

**Title**

`How Sentinel-KE works end to end`

**Bullets**

- Connects live telemetry, OSINT feeds, legacy exports, and agency connectors
- Builds graph relationships between services, endpoints, IPs, accounts, suppliers, and campaigns
- Uses GNNs and ML to prioritize risk while preserving baselines and thresholds
- Explains every decision with reason codes, evidence links, and trust checks
- Routes bounded containment and exportable reports

**Speaker note**

Say the GNN is the correlation and prioritization brain, not the first detector. Detection begins with signals and rules; the graph and model help make sense of them.

**Recommended visual**

Clean left-to-right architecture diagram with five boxes and one emphasis color per stage.

**Proof to show**

- simplified dataflow screenshot or system diagram from the product

### Slide 4

**Title**

`Cyber lane: live operational proof`

**Bullets**

- Latest matched cyber run: `2,500` nodes and `6,424` edges
- Holdout `AUC 0.9682`
- Operating precision `0.7538`, recall `0.6533`, `F1 0.7000`
- Scientific evidence across recent benchmarkable windows is `strong`
- Live feeds include Feodo, OTX, ThreatFox, MalwareBazaar, and URLhaus-style cyber intelligence

**Speaker note**

This is the strongest technical proof slide. Say clearly that cyber is the lead live lane and that the evaluation is matched and evidence-backed, while still not equal to fully adjudicated national ground truth.

**Recommended visual**

One metric card row plus one screenshot from the judge-readiness or GNN view.

**Proof to show**

- `/v1/ai/judge-readiness` cyber evidence

**What not to say**

- do not say every cyber alert is ground-truth confirmed

### Slide 5

**Title**

`Fraud lane: SIM swap, mule rings, VPN abuse, and benchmark evidence`

**Bullets**

- The graph model supports SIM swap -> login -> transfer -> cashout reasoning
- Mule-ring and VPN-style infrastructure reuse can be mapped and prioritized
- Fresh PaySim fraud benchmark: `AUC 0.9555`, `PR-AUC 0.9291`
- Current thresholded precision and `F1` remain conservative: `0.1251` and `0.2224`
- PaySim is a separate benchmark lane, not live sovereign fraud telemetry

**Speaker note**

Explain that the fraud architecture is real and the benchmark artifact is fresh, but be explicit that this is benchmark evidence and not the same as live partner bank or telco data.

**Recommended visual**

Fraud chain diagram from SIM swap to cashout, with one separate benchmark badge card.

**Proof to show**

- PaySim benchmark card from `/v1/ai/benchmarks`

**What not to say**

- do not say PaySim proves live Kenyan fraud detection

### Slide 6

**Title**

`Corruption lane: procurement and integrity risk intelligence`

**Bullets**

- Uses Kenyan procurement and integrity structures to rank risky patterns
- Latest active-window metrics: `AUC 0.9158`, precision `0.9759`, recall `0.7297`, `F1 0.8351`
- Fairness passed on the active window
- Designed for prioritization, case support, and investigative review
- Not positioned as legal proof or adjudication

**Speaker note**

Keep this lane strong but disciplined. It proves the architecture generalizes, but it must stay framed as risk intelligence and investigator support.

**Recommended visual**

Procurement entity map or risk cards for supplier, official, contract, project.

**Proof to show**

- corruption lane metric card plus one caveat badge: `mixed supervision`

### Slide 7

**Title**

`Under the hood: graph, GNN, explanation, containment`

**Bullets**

- Telemetry and rules detect signals first
- Graph relationships connect targets, infrastructure, campaigns, accounts, and entities
- GNNs and ML rank what deserves analyst attention
- Trust checks show reason codes, evidence posture, graph support, and caveats
- Containment is bounded, signed, logged, and reversible

**Speaker note**

This slide should make the system feel technically serious but readable. Emphasize that containment is policy-aware and not automatic blanket disruption.

**Recommended visual**

Four-part technical panel: detector, graph, GNN, containment receipt.

**Proof to show**

- one investigate-screen crop showing reason codes and trust checks

### Slide 8

**Title**

`Deployment and integration: built for agencies and sovereignty`

**Bullets**

- Supports sovereign deployment, hub-and-edge federation, and modular services
- Legacy systems can stream data through secure connector APIs and export bridges
- Agencies do not need to rewrite everything to connect
- The same platform supports command, investigation, response, and reporting

**Speaker note**

This answers deployment readiness and operational fit. Say the system enhances existing infrastructure instead of forcing rip-and-replace.

**Recommended visual**

Hub-edge architecture with connectors from SIEM, WAF, telco, bank, and procurement systems.

**Proof to show**

- legacy connector bridge and signed partner control-plane path

**What not to say**

- do not say every agency connector is already in production

### Slide 9

**Title**

`Trust, governance, and auditability`

**Bullets**

- Pseudonymisation and section-scoped access reduce unnecessary exposure of sensitive data
- Every important decision can be traced through reason codes, evidence references, and reports
- Fairness gates, real-data gates, abstention, and human review reduce misuse risk
- The platform exposes honest caveats instead of hiding uncertainty

**Speaker note**

This is one of the strongest differentiators. Judges should leave believing the system is disciplined, not just clever.

**Recommended visual**

Three-column governance slide: `Data protection`, `Auditability`, `Misuse safeguards`.

**Proof to show**

- trust summary or judge-readiness caveat block

### Slide 10

**Title**

`Why Sentinel-KE matters now`

**Bullets**

- Kenya needs a security workflow that can detect, relate, explain, and respond
- Sentinel-KE is already strongest in live cyber operations and evidence-led readiness
- The fraud and corruption lanes prove the architecture generalizes beyond one use case
- The next step is pilot validation, partner integration, and deployment hardening

**Speaker note**

Close with controlled confidence. The ask should be concrete: pilot access, validation data, and one operational deployment path.

**Recommended visual**

Strong closing slide with one decisive statement and three concrete next steps.

**Proof to show**

- concrete ask: `pilot agency`, `validation data partner`, `operational deployment path`

## 5-Minute Timing

- Slide 1: `0:00-0:25`
- Slide 2: `0:25-0:55`
- Slide 3: `0:55-1:25`
- Slide 4: `1:25-2:10`
- Slide 5: `2:10-2:45`
- Slide 6: `2:45-3:15`
- Slide 7: `3:15-3:45`
- Slide 8: `3:45-4:15`
- Slide 9: `4:15-4:40`
- Slide 10: `4:40-5:00`

## Exact Claims To Use

- `Sentinel-KE is a sovereign intelligence workflow for Kenya.`
- `The platform ingests real signals, correlates them in a graph, scores them with GNNs, explains them with evidence, and routes bounded containment.`
- `Cyber is the strongest live lane today.`
- `PaySim is a separate fresh fraud benchmark artifact.`
- `Corruption is an investigative risk-intelligence lane, not legal proof.`
- `Containment is bounded, signed, and auditable.`

## Exact Claims To Avoid

- `The GNN alone detects everything.`
- `The system proves attribution.`
- `Corruption output is legal proof.`
- `PaySim validates cyber.`
- `Every lane is fully ground-truth supervised.`
- `The partner simulator is already a production commercial partner.`

## Final Rule

If you need to cut content, cut detail, not credibility.

Keep the slide story on this chain:

`problem -> workflow -> cyber proof -> fraud benchmark -> corruption lane -> governance -> deployment -> ask`

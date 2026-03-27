# Sentinel-KE 8-Slide Presentation Pack

Last updated: 2026-03-27

This is the paste-ready script for Gamma or Claude to generate the slide deck. It is written for an 8-slide, 5-minute presentation, followed by a 10-minute live demo and judge Q&A.

## Creative Brief For Gamma / Claude

Create a sharp, executive-grade, national-security presentation for Sentinel-KE. Visual style should feel sovereign, operational, and credible rather than futuristic. Use strong typography, high contrast, clear sectioning, and data-led cards. The deck must tell one story: Sentinel-KE ingests real signals, correlates them in a graph, scores them with GNNs, explains them with evidence, and routes bounded containment with audit receipts. Keep the language plain enough for judges, but technically defensible. Use 8 slides only. Avoid generic AI hype, avoid purple SaaS visuals, and avoid implying legal proof or overclaiming full ground-truth supervision. The deck should position Sentinel-KE as a Kenya-relevant, multi-lane sovereign security platform with live evidence for cyber, fraud benchmark evidence for PaySim, and transparent governance for corruption and response.

## Slide 1 - Title And Thesis

### On-slide title
`Sentinel-KE: sovereign intelligence for cyber, fraud, and corruption`

### Key bullets
- One platform for ingest, graph, GNN, explanation, containment, and reporting
- Built for Kenyan operational reality: agency workflows, critical services, and federation
- Separate lanes for cyber, fraud, and corruption
- Live judge-readiness surface is available and evidence-backed

### Speaker notes
- Open with the problem: national security systems need more than dashboards.
- Say this is not one model; it is a working operational stack.
- Keep the claim narrow: sovereign intelligence platform, not universal AI.

### Metrics / claims to use
- `judge-readiness: status ok`
- `cyber scientific evidence: strong`
- `fresh PaySim benchmark artifact present`

### Claims to avoid
- Do not say it proves every alert is correct.
- Do not say fraud results validate cyber results.
- Do not say the platform is fully ground-truth supervised.

## Slide 2 - Why It Matters

### On-slide title
`Kenya needs a system that sees attacks, fraud, and corruption as connected`

### Key bullets
- Cyber pressure hits citizen services, tax portals, and agency infrastructure
- Fraud moves through identity, phone, account, and transaction chains
- Corruption emerges in procurement, contracts, officials, and suppliers
- The platform is designed for multi-agency, multi-domain response

### Speaker notes
- Frame the platform as an operational response to real national risk.
- Explain that each lane has different data, graph topology, and response needs.
- Make it clear the platform is built for agency use, not a toy demo.

### Metrics / claims to use
- Kenya-specific operational fit
- Multi-agency federation
- Distinct cyber, fraud, and corruption lanes

### Claims to avoid
- Do not say one model solves all sectors.
- Do not say the system replaces agencies.

## Slide 3 - How It Works

### On-slide title
`Sense -> correlate -> score -> explain -> contain -> report`

### Key bullets
- Ingest live telemetry and legacy exports through connector APIs
- Project events into graph relationships and campaign structure
- Score risk with GraphSAGE-based GNNs and threshold layers
- Explain decisions with evidence hashes, paths, and reason codes
- Dispatch bounded containment through signed webhooks

### Speaker notes
- This is the architecture slide.
- Say GNN is the correlation and prioritization brain, not the only detector.
- Emphasize that containment is signed, logged, and reversible.

### Metrics / claims to use
- `signed containment workflow`
- `audit trail`
- `graph + GNN + evidence`

### Claims to avoid
- Do not say the GNN alone detects everything.
- Do not say containment means shutting down the internet.

## Slide 4 - Cyber Evidence

### On-slide title
`Cyber lane: live evidence, matched windows, strong scientific support`

### Key bullets
- Latest matched cyber run: `2,500` nodes, `6,424` edges
- Holdout `AUC 0.9682`
- Operating `precision 0.7538`
- Operating `recall 0.6533`
- Operating `F1 0.7000`
- Recent scientific evidence across windows is `strong`
- Live judge-readiness anchors the cyber lane to the latest benchmarked run

### Speaker notes
- This is the strongest technical proof for the cyber lane.
- Say the cyber lane is real and judged on matched windows, not cherry-picked screenshots.
- Keep the caveat honest: this is strong scientific evidence, not full national incident truth.

### Metrics / claims to use
- `AUC 0.9682`
- `mean AUC 0.9910`
- `mean PR-AUC 0.9566`
- `mean operating F1 0.8575`
- `scientific evidence strong`

### Claims to avoid
- Do not say cyber is fully adjudicated truth.
- Do not say the newer live window invalidates the benchmarked one.

## Slide 5 - Fraud And Corruption

### On-slide title
`Fraud benchmark and corruption lane prove the architecture generalizes`

### Key bullets
- PaySim fresh artifact:
  - `AUC 0.9555`
  - `PR-AUC 0.9291`
  - `precision 0.1251`
  - `recall 1.0`
  - `F1 0.2224`
- Corruption lane:
  - `AUC 0.9158`
  - `precision 0.9759`
  - `recall 0.7297`
  - `F1 0.8351`
- The fraud lane is a benchmark lane, not a cyber proof
- The corruption lane is a prioritization and evidence layer, not legal proof

### Speaker notes
- Explain that fraud and corruption validate the architecture beyond cyber.
- Be honest that PaySim is a benchmark and not live telco data.
- Say corruption helps investigators prioritize, but it is not adjudication.

### Metrics / claims to use
- `PaySim artifact fresh`
- `Corruption AUC 0.9158`
- `fraud benchmark separate from cyber`

### Claims to avoid
- Do not say PaySim proves live Kenyan fraud detection.
- Do not say corruption outputs are legal findings.

## Slide 6 - Operational Proof

### On-slide title
`The platform can demonstrate a real DDoS-style operational response`

### Key bullets
- eCitizen-style controlled proof exists end to end
- Telemetry ingested through the live API
- DDoS detected, related in graph, scored by GNN, and contained
- Latest proof values:
  - `telemetry_ingested: true`
  - `ddos_detected: true`
  - `graph_related: true`
  - `gnn_scored: true`
  - `containment_dispatched: true`
  - `containment_logged_in_ledger: true`

### Speaker notes
- Tell the judges this is not a screenshot-only demo.
- The platform can actually run through detection, correlation, and containment receipts.
- Make sure to say containment is bounded and signed, not blanket shutdown.

### Metrics / claims to use
- `GNN score on service_id:ecitizen: 44.7162`
- `path score: 99.86265`
- `fusion score: 51.795383`
- `delivery receipts: 8`

### Claims to avoid
- Do not say the GNN alone triggered the containment.
- Do not say the system automatically blocks the whole internet.

## Slide 7 - Integration And Containment

### On-slide title
`Sentinel-KE plugs into legacy systems and partner control planes`

### Key bullets
- Legacy systems can stream through `/v1/integrations/{connector_key}/batch`
- Supported paths include CSV, JSONL, JSON array, SIEM relay, and export bridges
- Containment uses signed webhooks to partner WAF, CDN, EDR, telco, or bank controls
- Demoable escalation ladder:
  - observe
  - challenge / rate limit
  - isolate
  - upstream scrub / block

### Speaker notes
- This slide answers integration-readiness and deployment-readiness.
- Explain that agencies do not need to rewrite their systems.
- Stress that containment is matched to evidence quality and operational risk.

### Metrics / claims to use
- `signed external containment workflow`
- `legacy connector API`
- `operator-driven escalation`

### Claims to avoid
- Do not say the self-test receiver is a production partner.
- Do not say every agency system must be rewritten.

## Slide 8 - Why We Win

### On-slide title
`Why Sentinel-KE is Top-3 credible`

### Key bullets
- Strong national relevance and agency fit
- Real live cyber evidence
- Fresh fraud benchmark evidence
- Honest governance and caveats
- Clear response workflow with receipts
- Built for sovereign deployment, not generic SaaS

### Speaker notes
- Close with confidence, not hype.
- Say the differentiator is the combination: sovereignty, federation, graph intelligence, evidence, and controlled response.
- End by inviting judges to inspect the evidence surfaces themselves.

### Metrics / claims to use
- `Top-3 credible`
- `judge-ready evidence surfaces`
- `operationally proven containment workflow`

### Claims to avoid
- Do not say the system is finished.
- Do not say public deployment is already fully solved if it is not.

## Exact Claims To Use

- `Sentinel-KE ingests real cyber events, builds a graph, scores risky entities with a GNN, and routes containment through signed workflows with audit evidence.`
- `Cyber has strong recent scientific evidence across multiple matched windows.`
- `PaySim is a separate fraud benchmark lane with a fresh reproducible artifact.`
- `Corruption is a live prioritization and evidence lane, not a legal adjudication engine.`
- `Containment is bounded, signed, and reversible.`
- `The platform is sovereign and multi-agency by design.`

## Exact Claims To Avoid

- `The GNN alone detects everything.`
- `The platform proves legal guilt.`
- `Fraud metrics validate cyber performance.`
- `The self-test receiver is a production partner.`
- `Containment means shutting down the whole internet.`
- `Everything is ground-truth supervised.`

## 5-Minute Delivery Target

- Slide 1: 25 seconds
- Slide 2: 30 seconds
- Slide 3: 40 seconds
- Slide 4: 55 seconds
- Slide 5: 50 seconds
- Slide 6: 55 seconds
- Slide 7: 45 seconds
- Slide 8: 40 seconds

## Final One-Liner

> Sentinel-KE is a sovereign intelligence workflow: ingest, correlate, score, explain, contain, and report.

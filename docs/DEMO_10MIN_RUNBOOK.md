# Sentinel-KE 10-Minute Demo Runbook

Last updated: 2026-03-27

This is the live demo script for a 15-minute judging slot:

- 5 minutes for the pitch / framing
- 10 minutes for the live product demo

This runbook covers the 10-minute live demo only. It is built for the strongest current proof chain:

- judge readiness
- cyber graph / GNN evidence
- live event stream
- threat graph
- entity investigation
- bounded containment
- delivery receipts
- report export

## Demo Thesis

Use this sentence at the start and keep returning to it:

> "Sentinel-KE ingests real events, correlates them in a graph, scores them with a GNN, and routes bounded containment with signed audit evidence."

Do not start with corruption, and do not deep-dive into fraud unless a judge asks. The strongest live story is cyber plus containment.

## Pre-Demo Checklist

Before the judges arrive, confirm all of these are open and ready:

- `Command` screen loaded at `http://localhost:3000`
- `Live Feed` screen responsive
- `Threat Graph` screen responsive
- `Investigate` screen responsive
- `Defense` screen responsive
- `Reports` screen responsive
- terminal tab with `GET /v1/ai/judge-readiness`
- terminal tab with `GET /v1/ai/benchmarks`
- terminal tab with `GET /v1/defense/webhooks/deliveries`
- terminal tab with `GET http://sentinel-ke-notebook-1:18102/receipts`
- local proof artifacts ready:
  - `/app/artifacts/gnn/multiwindow_cyber_eval.json`
  - `/app/artifacts/paysim_auc.json`
  - `/app/artifacts/operational_ddos_claim_ecitizen.json`

If something is stale, refresh before the room goes live.

## Non-Negotiable Claims

Only say the following:

- cyber is live and strongly evidenced
- PaySim is a separate fresh fraud benchmark lane
- external containment is a signed cross-system workflow
- the platform is sovereign / evidence-led / operator-friendly

Do not say:

- the model alone proves attribution
- the GNN alone detects everything
- containment means shutting down the internet
- the self-test receiver is a production partner
- the cyber lane is fully adjudicated national ground truth

## Minute-by-Minute Timeline

| Time | Screen | Clicks | Exact words to say | What the judge should see |
|---|---|---|---|---|
| 0:00-0:45 | `Command` | Open the app, land on `Command` | "Sentinel-KE is a sovereign intelligence workflow. It ingests events, correlates them in a graph, scores them with a GNN, and routes bounded containment with audit evidence." | Readiness surface, cyber lane, fraud benchmark card, no blank screen |
| 0:45-1:30 | `Command` | Click `Open GNN Intelligence` | "This top fold separates operational truth from scientific truth. Cyber is the live lane, and PaySim is a separate benchmark lane." | Judge-ready summary, lane separation, benchmark evidence visible |
| 1:30-2:45 | `Live Feed` | Click `Live Feed` | "This is the operator queue. It shows what arrived first and what needs review, not the final legal conclusion." | Event cards, one event selected, no confusion about priority |
| 2:45-4:15 | `Threat Graph` | Click `Threat Graph`; use `Focus entity` with `service_id:ecitizen` if available, otherwise `kplc` | "This screen answers one question: who is attacking whom, through what infrastructure, and under which grouping." | Target side, attacker infra, campaign grouping, dimmed unrelated nodes |
| 4:15-5:45 | `Investigate` | Click the strongest entity from the graph or search `service_id:ecitizen`; open `Investigate in depth` | "This is the evidence view. It shows the risk score, the graph support, the reasons, and the next move. We keep it as an investigative indicator, not legal proof." | Risk score, uncertainty, reason codes, graph reasoning, trust checks |
| 5:45-7:15 | `Defense` | Click `Defense`; select the incident run; choose `enable_waf_challenge` | "Containment is bounded and signed. We do not jump straight to broad blocking. We start with friction, then isolate or suppress only when the evidence justifies it." | Action composer, action history, execution status, webhook path |
| 7:15-8:30 | `Defense` receipts | Open `Webhook deliveries`; show partner receipt endpoint if available | "This is the operational proof. Sentinel signs the request, the partner accepts it, and both sides keep receipts." | Delivered receipt, partner receipt, signed verification |
| 8:30-9:30 | `Reports` | Click `Reports`; open the latest operational report | "Everything is traceable. The report packages the event chain, the model signal, the containment action, and the caveats in one handoff." | Exportable report, human-readable summary, limitations, evidence trail |
| 9:30-10:00 | Return to `Command` | Back to the judge brief | "That is the full loop: ingest, correlate, explain, contain, and report. The system is not a model demo; it is an operational workflow." | Judge-ready top fold as a closing frame |

## Screen Sequence And Exact Clicks

Use this exact order.

1. `Command`
2. `Open GNN Intelligence`
3. `Live Feed`
4. `Threat Graph`
5. `Investigate`
6. `Defense`
7. `Reports`
8. Back to `Command`

If you show any other screen, make sure it is only because a judge asked a direct question.

## What To Say Word For Word

### Opening

Say:

> "Sentinel-KE is a sovereign security workflow, not a slideware demo. The platform already ingests live events, builds graph relationships, scores them with a GNN, and dispatches signed containment with receipts."

### On `Command`

Say:

> "This is the judge-facing surface. Cyber is the live operational lane. PaySim is a separate fraud benchmark lane. Corruption exists, but it is not the lead story today."

### On `Live Feed`

Say:

> "This screen is the operator queue. It tells the team what arrived first and what needs attention. It does not pretend to be the final decision engine."

### On `Threat Graph`

Say:

> "This is the relationship view. It answers who is attacking whom, through what infrastructure, and under which campaign grouping."

### On `Investigate`

Say:

> "This is where the score becomes an explanation. We show the model signal, the graph support, the trust checks, and the next move. The system is deliberately conservative and does not overclaim proof."

### On `Defense`

Say:

> "Containment is bounded. We start with challenge or throttling, and we only escalate to isolation or upstream suppression when the evidence and policy justify it."

### On `Reports`

Say:

> "The same evidence can be packaged into a report for leadership or audit. That keeps the workflow usable for operators and defensible for reviewers."

### Closing

Say:

> "The value here is not one model. It is the full chain: ingest, correlate, score, explain, contain, and report."

## Judge-Safe Evidence To Mention

Use these facts if asked for numbers:

- cyber judge readiness is `ok`
- cyber scientific evidence is `strong`
- latest cyber run includes `AUC 0.9682`
- multi-window cyber evidence has strong aggregate metrics
- PaySim has a fresh artifact with `AUC 0.9555`
- the external containment demo has a signed delivery receipt and an accepted partner receipt
- the eCitizen claim includes graph, GNN, and containment evidence in one run

## Fallback Path If A Screen Misbehaves

If the screen blanks, freezes, or opens the wrong entity:

1. Return to `Command`
2. Open `Investigate`
3. Search `service_id:ecitizen`
4. If that is not visible, search `kplc`
5. If `Threat Graph` is slow, skip straight to `Investigate`
6. If `Defense` is slow, show webhook deliveries off-screen instead of waiting

If `Defense` fails to execute live:

- show `GET /v1/defense/webhooks`
- show `GET /v1/defense/webhooks/deliveries`
- show the partner receipt endpoint

Do not spend the 10-minute demo waiting on a broken screen.

## Off-Screen Commands And Artifacts

Have these ready in another terminal tab:

```bash
curl -sS http://localhost:8000/v1/ai/judge-readiness
curl -sS http://localhost:8000/v1/ai/benchmarks
curl -sS "http://localhost:8000/v1/defense/webhooks/deliveries?section_code=ecitizen&limit=5"
curl -sS http://sentinel-ke-notebook-1:18102/receipts
```

If you need the evidence files instead of live APIs, open:

- `/app/artifacts/gnn/multiwindow_cyber_eval.json`
- `/app/artifacts/paysim_auc.json`
- `/app/artifacts/operational_ddos_claim_ecitizen.json`

## Do-Not-Click List

Avoid these during the 10-minute live demo unless a judge explicitly asks:

- `Corruption Intelligence`
- `Campaigns` unless you need a grouping explanation
- `Cases` unless you are proving handoff
- `Infra Correlation` unless the judge asks about VPN clustering
- any screen with stale or thin evidence where the explanation is more technical than operational

Do not open screens just because they exist. Open screens because they strengthen the claim.

## Final Rule

If the room gets tight on time, cut depth, not credibility.

Keep the demo on this chain:

`Command -> Live Feed -> Threat Graph -> Investigate -> Defense -> Reports`

That is the strongest live story in the current system.

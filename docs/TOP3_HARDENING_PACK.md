# Sentinel-KE Top-3 Hardening Pack

Last updated: 2026-03-27

This pack is the practical answer to the final Top-3 gap:

1. keep the judge documents aligned to the live system
2. use one stable, judge-verifiable backend access path
3. show one containment route honestly
4. use only the strongest claims and screens

---

## 1. Stable Judge-Verifiable Backend Access

The only clean public path already designed in the repo is:

- frontend on Vercel
- backend on Render
- Render Postgres as the shared ledger
- local ML/GNN workers pointing at the same Render Postgres

This is already the intended operating model in:

- [render.yaml](/home/ogola/personal/sentinel-ke/render.yaml)
- [RENDER_VERCEL_DEPLOY.md](/home/ogola/personal/sentinel-ke/docs/RENDER_VERCEL_DEPLOY.md)

### Judge-safe claim

Say:

> "The public backend is the same API surface the local workers write into. The web app is not a mock shell over a different demo database."

Do not say:

> "Every worker is running in Render right now."

That is not required for the MVP claim. The stronger and more honest claim is:

- public API is stable and judge-verifiable
- the ML workers can write into that same backend ledger
- the evidence surface is the same one the judges see

### Minimal deployment checklist

1. Deploy [render.yaml](/home/ogola/personal/sentinel-ke/render.yaml).
2. Set the public frontend origin in `CORS_ALLOW_ORIGINS`.
3. Keep `GNN_EDGE_BACKEND=postgres` for the public backend.
4. Point local ML workers to the external Render Postgres connection string.
5. Verify:
   - `/health`
   - `/v1/ai/judge-readiness`
   - `/v1/ai/benchmarks`

### Status right now

- architecturally ready
- operationally local-first
- not yet proven as a public stable judge URL inside this repo session

That means this remains a deployment task, not a code gap.

---

## 2. One Real Containment Route

The repo proves the containment loop in two honest ways:

1. built-in self-test receiver
2. external partner simulator on a separate service

The self-test route remains useful for engineering proof. The stronger demo route is now the external partner simulator described in [EXTERNAL_CONTAINMENT_DEMO.md](/home/ogola/personal/sentinel-ke/docs/EXTERNAL_CONTAINMENT_DEMO.md).

- [defense.py](/home/ogola/personal/sentinel-ke/backend/app/api/defense.py)
- [ECITIZEN_DDOS_OPERATIONAL_CLAIM.md](/home/ogola/personal/sentinel-ke/docs/ECITIZEN_DDOS_OPERATIONAL_CLAIM.md)

What that proves:

- signed dispatch works
- delivery receipts are recorded
- containment actions are written into the ledger

What it does not prove:

- a third-party WAF/CDN/EDR accepted the command

### Judge-safe claim

Say:

> "The containment pipeline is operationally proven end to end with signed delivery receipts. For production, the same route points to a partner WAF, CDN, EDR, telco, or banking control plane."

Do not say:

> "A live external partner already applied the control in this environment."

unless that partner webhook is actually connected.

### External route that is already supported

The hub already supports partner webhook registration:

- `POST /v1/defense/webhooks`
- `GET /v1/defense/webhooks`
- `GET /v1/defense/webhooks/deliveries`

Supported external action families already include:

- `block_ip`
- `rate_limit_service`
- `enable_waf_challenge`
- `reroute_to_scrubber`
- `isolate_host`
- `freeze_account`
- `hold_cashout`
- `suspend_sim_change`

So the practical next step is not new architecture. It is one real partner endpoint.

---

## 3. Exact Claims To Say

### Safe cyber claim

> "Sentinel-KE ingests real cyber events, builds a graph, scores risky entities with a GNN, and routes containment through a signed workflow with audit evidence."

### Safe fraud claim

> "Sentinel-KE has a separate fraud benchmark lane on PaySim with a fresh reproducible artifact. We use that to prove fraud-ranking capability, not to overstate the cyber or corruption lanes."

### Safe corruption claim

> "Sentinel-KE ranks procurement risk and graph relationships for investigators. It is not a legal finding engine."

### Safe national claim

> "The differentiator is not just AI. It is sovereign deployment fit, multi-agency federation, graph correlation, evidence traceability, and controlled response in one platform."

---

## 4. Exact Claims Not To Say

- Do not say the cyber lane is fully ground-truth supervised.
- Do not say fraud results validate cyber.
- Do not say corruption output is legal proof.
- Do not say the self-test webhook is a third-party production partner.
- Do not say every public endpoint is already deployed unless the Render path is actually live.

---

## 5. Strict 5-Minute Demo

Use only these screens:

1. `ExecBrief`
2. `Live Feed`
3. `Threat Graph`
4. `Investigate`
5. `Defense`
6. `Reports`

### Demo flow

1. Start on `ExecBrief`.
   - show readiness `ok`
   - show cyber lane
   - show corruption lane
   - show PaySim fraud benchmark card

2. Move to `Live Feed`.
   - show active service pressure or attack queue
   - explain this is the operator queue, not the final legal decision

3. Open `Threat Graph`.
   - answer: who is attacking whom, through what infrastructure, under which grouping

4. Open `Investigate`.
   - show entity risk, reasons, trust checks, evidence posture

5. Open `Defense`.
   - show containment action path
   - show receipts / delivery history

6. Close in `Reports`.
   - show that the same evidence can be exported as an operational report

### Best final line

> "What you are seeing is not one isolated model demo. It is a sovereign intelligence workflow: ingest, correlate, score, explain, contain, and report."

---

## 6. Remaining Top-3 Risks

The biggest remaining risks are now presentation and deployment, not core architecture:

- stale docs or stale numbers being quoted in front of judges
- no public judge-verifiable backend URL
- no commercial or agency production partner endpoint connected yet
- external partner simulator route is proven and judge-safe
- too many screens shown in one demo

If those are controlled, the project has a credible Top-3 case.

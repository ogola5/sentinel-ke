# Sentinel-KE Mission Loop Demo

Last updated: 2026-03-02 (Africa/Nairobi)

## Purpose

This is the single executive mission loop:

`Sense -> Analyze -> Explain -> Respond -> Rollback -> Govern`

Use this for judge demos and crisis briefings.

## Preconditions

- Backend running and healthy (`GET /health`)
- At least one section registered in `source_registry`
- API key configured in client (`X-API-Key`)
- Optional: federation partners online for cross-org correlation

## 1) Sense (ingest + live posture)

- Ingest event(s): `POST /v1/ingest/event` or connector flow via `/v1/integrations/*`
- Verify live state:
  - `GET /v1/events/search`
  - `GET /v1/metrics`
  - `GET /v1/defense/threat-alerts`

Expected:

- events are accepted and indexed
- baseline/alert counters move

## 2) Analyze (GNN + thresholds + fairness)

- Run/observe latest GNN outputs:
  - `GET /v1/ai/gnn/runs`
  - `GET /v1/ai/predictions?prediction_type=risk_gnn`

What to show:

- calibrated risk score
- uncertainty
- fairness block status and disparity in run metrics
- evaluation protocol metadata (`holdout_policy`, calibration metrics)

## 3) Explain (model attribution)

- Fetch explanation:
  - `GET /v1/ai/explanations/{prediction_id}`

What to show:

- `explanation_method` (`gradient_x_input`)
- `top_feature`
- attribution vector/group scores
- counterfactual guidance + recommended controls

## 4) Respond (containment)

- Create incident run:
  - `POST /v1/defense/incidents/runs`
- Execute bounded actions:
  - `POST /v1/defense/incidents/runs/{run_id}/actions`

Supported action examples:

- `block_ip`
- `isolate_host`
- `disable_source_key`
- `revoke_user`

Expected:

- `containment_action` rows created
- webhook receipts visible in `GET /v1/defense/webhooks/deliveries`

## 5) Rollback (safe undo path)

If an IP block was overly broad:

- execute action type: `rollback_block_ip` (same run or follow-up run)

Guardrails enforced:

- requires prior executed `block_ip`
- rollback must be inside bounded window (`DEFENSE_ROLLBACK_WINDOW_MINUTES`)
- duplicate rollback for same original action is rejected
- webhook dispatch uses `unblock_ip` (signed, auditable)

## 6) Govern (audit + posture)

- `GET /v1/defense/webhooks/deliveries`
- `GET /v1/audit/*` (via operational audit views)
- `GET /v1/defense/crypto/posture`

What to show:

- who did what, when, and outcome
- legal + operational traceability
- current crypto baseline posture

## Demo success criteria

- one high-risk prediction with explanation shown
- one containment action executed
- one rollback action executed or rejected by guardrail (both acceptable)
- full audit trail visible end-to-end

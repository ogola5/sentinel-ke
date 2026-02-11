# MVP Add-On Execution Plan (No Rewrite)

Date: 2026-02-11
Scope: Build a cross-platform desktop product and unique national-value features by extending existing Sentinel-KE modules.

## 1) Constraints

- Do not rewrite current ingestion/ledger/graph pipelines.
- Reuse existing Postgres + OpenSearch + Neo4j + worker architecture.
- Add new models/workers/APIs as incremental modules.
- Keep features deterministic and explainable.

## 2) Add-On MVP Features

1. Economic Blast Radius (KES impact per service/sector/county)
2. Counterfactual Response Simulator (action -> predicted risk/economic delta)
3. Court-Ready Dossier Export (chain-of-custody + timeline + graph + STIX)
4. Cross-Agency Privacy Clean Room (pseudonymized matching, no raw PII exchange)
5. National Trust Index + Command Briefing
6. Cross-platform Desktop App installer (Windows/macOS/Linux)

## 3) Build Phases (12 Weeks)

### Phase A (Week 1-2): Foundation and Productization
- Decide desktop stack: Tauri + current React frontend.
- Define new DB schemas for impact/simulation/clean-room/trust-index.
- Add router placeholders and typed schemas.
- Add initial migration/DDL scripts.

Acceptance criteria:
- New API routes present and mounted.
- New tables created and visible in DB.
- Desktop shell can launch and call `/health`.

### Phase B (Week 3-6): Core Feature Pack
- Implement Economic Blast Radius scoring service + API.
- Implement Counterfactual Simulator service + API.
- Extend case pipeline for court-ready dossier export.

Acceptance criteria:
- One DDoS/campaign event chain returns KES impact estimate.
- One simulation request returns deterministic action outcomes.
- One campaign can generate downloadable dossier payload.

### Phase C (Week 7-10): Cross-Agency and Trust Layer
- Implement clean-room job model and pseudonymized join engine.
- Implement trust index computation and briefing generator.
- Add explainability fields to outputs.

Acceptance criteria:
- Two synthetic agencies can correlate by pseudonymized keys only.
- Trust index endpoint returns score + reason codes + evidence refs.

### Phase D (Week 11-12): Desktop Packaging and Demo Hardening
- Build installers for Windows/macOS/Linux.
- Add desktop onboarding flow (API target, auth key, mode).
- Prepare final demo scenarios and runbook.

Acceptance criteria:
- Installers run on all three OS targets.
- End-to-end demo: ingest -> alerts -> impact -> action sim -> dossier.

## 4) Exact Coding Start Point

Start with Feature 1 first (Economic Blast Radius), because it gives immediate national/economic value and is low-risk to integrate.

Create/modify in this exact order:

1. Create models
- `backend/app/analytics/impact_models.py`
- Tables: `impact_estimate`, `impact_factor`

2. Register models
- `backend/app/db/registry.py`

3. Create scoring/service module
- `backend/app/economy/impact.py`
- Input sources: `ddos_alert`, `campaign`, `economic_signal`

4. Create API router
- `backend/app/api/impact.py`
- Endpoints:
  - `POST /v1/impact/estimate`
  - `GET /v1/impact/estimates`
  - `GET /v1/impact/summary`

5. Mount router
- `backend/app/main.py`

6. Add tests
- `backend/tests/test_impact.py`

7. Update runbook
- `docs/RUNBOOK.md` with sample requests

## 5) First Sprint Backlog (Next 3-4 Days)

Day 1:
- Add DB models and registry wiring.
- Add Pydantic schemas for impact requests/responses.

Day 2:
- Implement deterministic impact scoring logic and persistence.
- Add API endpoints + pagination/filtering.

Day 3:
- Add tests and seed demo inputs.
- Add runbook examples and validate endpoint outputs.

Day 4:
- Refine scoring calibration and reason codes.
- Freeze v1 contract for frontend/desktop integration.

## 6) Competition KPI Targets

- Mean detection-to-impact report time < 2 minutes.
- Every high-severity alert has explainability + evidence references.
- Economic estimate includes confidence bands and sector breakdown.
- Dossier generation time < 30 seconds per campaign.

## 7) Risk Controls

- No silent failures on core write paths (log and metric on failure).
- Keep idempotent writes on workers and APIs.
- Preserve append-only evidence ledger model.
- Add integration tests for each new endpoint.

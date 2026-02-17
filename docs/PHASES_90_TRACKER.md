# Sentinel-KE 90% Delivery Tracker (4-Week Hackathon Mode)

This document is the execution board for reaching national-grade quality fast.

## Current baseline

- Overall readiness: ~35%
- Target: 90%
- Delivery mode: aggressive, evidence-driven, weekly checkpoints

## Phase 1: Hardening Foundation (Week 1)

Objective: remove demo-grade security risks and create stable delivery controls.

- [x] Remove hardcoded compose credentials (`NEO4J_AUTH` now env-driven).
- [x] Enforce strict API auth defaults (`API_AUTH_OPTIONAL_DEV=false` by default).
- [x] Remove insecure API key fallback (`dev-secret-key` fallback removed).
- [x] Limit legal token exposure (execution token only at grant issuance).
- [x] Replace hardcoded `demo-salt` in ingestion APIs with `PSEUDONYM_SALT`.
- [x] Add ingest failure telemetry logs (OpenSearch/Graph/Kafka best-effort paths).
- [x] Add Alembic migration scaffold (`backend/alembic*`).
- [x] Clean and normalize `.env.example`.
- [x] Update `.gitignore` for heavy ML/notebook artifacts.

Exit criteria:

- No default secrets in compose/env examples.
- All APIs require keys unless explicitly disabled.
- Schema changes are migration-first.
- Failure paths are observable in logs.

## Phase 2: Evidence + Legal Defensibility (Week 2)

Objective: make outputs legally reliable and auditable.

- [ ] Enable non-stub MinIO/immudb in staging profile.
- [ ] Add anchor verification job + API status dashboard.
- [ ] Add legal bundle integrity regression tests.
- [ ] Add signed evidence export with replay verification steps.

Exit criteria:

- 100% evidence bundles anchored and verifiable.
- Chain integrity checks pass after replay.

## Phase 3: AI/GNN Operational Maturity (Week 3)

Objective: move from promising model behavior to defensible intelligence quality.

- [ ] Build temporal train/validation/test split workflow.
- [ ] Add per-entity threshold calibration quality checks.
- [ ] Add drift + data quality checks for feature windows.
- [ ] Add analyst feedback capture for label improvement.

Exit criteria:

- Model quality is stable across windows, not one-off runs.
- Drift alerts exist and are test-covered.

## Phase 4: National Ops Workflow (Week 4, Part A)

Objective: make the platform actionable for SOC + anti-corruption operations.

- [ ] Campaign-level triage screen backed by APIs.
- [ ] Priority queues by risk, sector, and legal status.
- [ ] Standard analyst runbooks for top 5 incident classes.
- [ ] Decision audit trail for every analyst action.

Exit criteria:

- End-to-end analyst workflow demo in under 10 minutes.

## Phase 5: Competition-Grade Demonstration (Week 4, Part B)

Objective: prove sovereign advantage over outsourced black-box tools.

- [ ] Build one scripted live scenario per domain:
  - cyber attack correlation
  - economic leakage detection
  - legal evidence export
- [ ] Capture measurable KPIs (precision@K, MTTD, chain verification, time-to-report).
- [ ] Prepare governance narrative (risk indicator vs legal proof boundary).

Exit criteria:

- Judges can reproduce results from runbook commands.
- KPIs are concrete and repeatable on demand.

## Weekly control loop

- Monday: lock sprint scope + acceptance tests.
- Wednesday: mid-sprint verification demo.
- Friday: scorecard update and blocker burn-down.


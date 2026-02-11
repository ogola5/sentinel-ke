# Sentinel-KE Roadmap Tracker

Last updated: 2026-02-11
Source docs:
- `README.md`
- `docs/ROADMAP_MVP_2025.txt`
- `docs/MVP_ADDON_EXECUTION_PLAN.md`

## 1) Current Position (from source docs)

- Original MVP target date: 2025-03-15
- Today: 2026-02-11
- Status: MVP timeline is overdue (target date passed)
- Reported baseline coverage: ~25%

Implemented or partially implemented (as stated in `README.md`):
- Canonical ingestion with validation + pseudonymization
- Postgres ledger and OpenSearch indexing/search
- Graph delta logging and Neo4j projection
- Campaign correlation (fraud/mule demo)
- DDoS analytics and infra clustering
- Mitigation/IOC bundles
- AI feature snapshots + lightweight predictions
- Metrics + readiness endpoints

Stated gaps (from `README.md` + roadmap):
- Cross-agency governance and policy compliance
- Economic leakage/corruption workflows
- Multi-tenant data sharing gateway/marketplace
- National SOC workflows + incident reporting portal
- Export/compliance pack and monetization layers

## 2) Roadmap Track Status

Legend: `DONE`, `PARTIAL`, `NOT STARTED`, `UNKNOWN`

1. MVP scope + success metrics alignment: `PARTIAL`
2. Data governance + data trust policy + onboarding plan: `NOT STARTED`
3. Canonical schema + data contracts hardening: `PARTIAL`
4. Connector specs + ingestion hardening: `PARTIAL`
5. Provenance ledger + chain-of-custody workflow: `PARTIAL`
6. Zero-trust + RBAC + tenant boundaries: `PARTIAL`
7. Observability + audit + tamper-evident trails: `PARTIAL`
8. Search/graph stability + replay + performance tuning: `PARTIAL`
9. Core analytics v1 (campaigns/DDoS/infra): `PARTIAL`
10. Economic integrity v1 (procurement/leakage): `PARTIAL`
11. Cross-agency correlation + case mgmt + evidence export: `PARTIAL`
12. Early warning risk scoring + explainability: `PARTIAL`
13. National SOC frontend + sector dashboards: `PARTIAL`
14. Executive reporting + KPI dashboards + briefings: `NOT STARTED`
15. Pilot integration for one sector: `NOT STARTED`
16. Security/load/data-quality testing: `PARTIAL`
17. MVP readiness docs + demo prep: `PARTIAL`

## 3) What We Should Do Next (Execution Track)

### Phase A (Week 1-2): Re-baseline and lock scope
- Define a new target date and updated MVP scope (strictly what can ship)
- Convert each of the 17 roadmap items into acceptance criteria
- Mark each item with owner, ETA, and dependency
- Decide first pilot sector (telco or finance)

Exit criteria:
- Signed scope document
- Tracker fields populated (owner, ETA, status, blockers)
- Pilot sector selected

### Phase B (Week 3-6): Close core MVP gaps
- Governance pack: data trust policy, retention, compliance controls
- Economic integrity v1: procurement anomaly + leakage signals (minimum viable detectors)
- SOC workflow: incident triage, assignment, status tracking
- Reporting: executive KPI dashboard + briefing export

Exit criteria:
- End-to-end demo for one real workflow per gap area
- Evidence and explainability attached to each alert type

### Phase C (Week 7-8): Pilot readiness
- Sector pilot connectors and data contracts finalized
- Security + load + quality validation with fixed thresholds
- Runbook, incident playbooks, and demo script finalized

Exit criteria:
- Pilot dry-run completed
- Go/no-go checklist passed

## 4) Weekly Tracker Template (copy per week)

- Week of: `YYYY-MM-DD`
- Objective:
- Planned deliverables:
- Completed:
- Blockers:
- Risk level: `Low/Medium/High`
- Decisions needed:
- Next week focus:

## 5) Immediate Action List (this week)

1. Create a single issue board from the 17 roadmap items.
2. Add acceptance criteria for items 10, 14, 15 first (largest visible gaps).
3. Set owners and ETAs for all `NOT STARTED` items.
4. Run a readiness review against one pilot-sector workflow.

## 6) Desktop Add-On MVP Track (No Rewrite)

Goal:
- Deliver an installable Windows/macOS/Linux desktop product on top of existing backend capabilities.
- Add unique national-security + economic-impact features without rewriting current ingestion/ledger/graph/worker architecture.

Current readiness for this add-on goal:
- Platform backend foundation: `55-65%`
- Economic integrity analytics: `20-30%`
- Desktop packaging/productization: `0-10%`
- Combined competition-ready add-on MVP: `15-25%`

Status legend: `DONE`, `PARTIAL`, `NOT STARTED`, `BLOCKED`

1. Desktop shell (cross-platform installer + secure config): `NOT STARTED`
2. Economic Blast Radius engine (KES impact estimation): `NOT STARTED`
3. Counterfactual response simulator (what-if actions): `NOT STARTED`
4. Court-ready dossier generation pipeline: `PARTIAL`
5. Cross-agency privacy clean-room correlation: `NOT STARTED`
6. National trust index + command briefing: `NOT STARTED`
7. Procurement guardrail decisioning (allow/review/block): `PARTIAL`
8. External-system tamper/deletion integrity detection: `PARTIAL`
9. Economic leakage detection worker + APIs: `PARTIAL`

Execution reference:
- `docs/MVP_ADDON_EXECUTION_PLAN.md`

## 7) Where To Begin Coding (Exact Order)

Step 1 (start here): Economic Blast Radius backend slice
- Create models: `backend/app/analytics/impact_models.py`
- Register models: `backend/app/db/registry.py`
- Create scoring/service: `backend/app/economy/impact.py`
- Add API router: `backend/app/api/impact.py`
- Wire router: `backend/app/main.py`
- Add tests: `backend/tests/test_impact.py`

Step 2: Counterfactual simulator slice
- Service: `backend/app/analytics/simulation.py`
- API: `backend/app/api/simulation.py`
- Router wiring: `backend/app/main.py`
- Tests: `backend/tests/test_simulation.py`

Step 3: Court-ready dossier export slice
- Extend builders/exporters: `backend/app/cases/builders.py`, `backend/app/stix/exporter.py`
- New API endpoint: `backend/app/cases/api.py`
- Tests: `backend/tests/test_cases_dossier.py`

Step 4: Desktop packaging slice
- Create desktop shell with Tauri under: `desktop/`
- Keep web UI in `frontend/`; desktop calls existing backend APIs
- Add packaging docs/scripts: `docs/RUNBOOK.md` (desktop section), `desktop/README.md`

Step 5: Privacy clean-room + trust index
- Create modules: `backend/app/analytics/cleanroom.py`, `backend/app/analytics/trust_index.py`
- APIs: `backend/app/api/cleanroom.py`, `backend/app/api/trust.py`
- Tests: `backend/tests/test_cleanroom.py`, `backend/tests/test_trust_index.py`

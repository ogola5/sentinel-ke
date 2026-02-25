# Sentinel-KE Backend Documentation

This document is the backend engineering reference for Sentinel-KE. It is focused on architecture, security boundaries, API access controls, data flow, and operations.

For command-heavy day-to-day usage, see `docs/RUNBOOK.md`.

## 1) System Overview

Sentinel-KE backend has three deterministic layers:

- Layer 1 (Canonical Data): ingestion into Postgres ledger (`event_log`) + indexed search in OpenSearch.
- Layer 2 (Derived Graph): graph deltas in Postgres and projection into Neo4j.
- Layer 3 (Analytics): workers and APIs for alerts, campaigns, risk, explainability, legal workflows, and defense automation.

Trust model:

- Postgres is the source of truth.
- OpenSearch and Neo4j are derived views.
- Analytics outputs must persist to Postgres.

## 2) Runtime Components

Primary services:

- `backend` (FastAPI)
- `postgres` (canonical storage)
- `opensearch` (event search/timeline)
- `neo4j` (graph projection)
- `redpanda` (internal streaming)

Optional/services:

- `notebook` (ML and notebook workflows)
- `redpanda-consumer` (stream ingestion path)
- background workers (campaign, ddos, gnn, leakage, etc.)

## 3) Authentication and Authorization

### 3.1 Principal resolution model

Authentication is resolved in `app.api.deps.require_request_principal` with these behaviors:

- If `API_AUTH_DISABLED=true`: bypass as privileged service principal (`scopes=["*"]`).
- If auth is disabled (`AUTH_ENABLED=false`): only API key mode is used.
- With auth enabled:
  - Valid `X-API-Key` creates a service principal (`central`, `scopes=["*"]`).
  - Otherwise valid Bearer access token creates a user principal.

Important behavior:

- Section-level principals must have `section_code`; requests are rejected otherwise.
- For sensitive central routes, MFA step-up is enforced when enabled.

### 3.2 RBAC model

Built-in user access levels:

- `section`: limited to one section via `section_code`.
- `central`: nationwide/control-plane access.

Built-in default roles:

- `analyst`
- `section_commander`
- `central_operator`
- `admin`

Role policies are stored in `auth_role_policy` and are bootstrapped at startup.

### 3.3 Scope matrix (router level)

This is enforced from `app.api.router_registry`:

- `/v1/ingest/*`: API key required.
- `/v1/events/*`: `events.read` + section or central access.
- `/v1/graph/*`: `graph.read` + central access.
- `/v1/campaigns*`: `campaigns.read` + section or central.
- `/v1/infra*`: `infra.read` (+ central for infra graph projection routes).
- `/v1/ddos/*`: `ddos.read`.
- `/v1/cases/*`: `cases.read`.
- `/v1/stix/*`: `intel.read`.
- `/v1/anomalies/*`: `anomalies.read`.
- `/v1/mitigations/*`: `mitigations.read`.
- `/v1/metrics/*`: `metrics.read`.
- `/v1/ai/*` (if enabled): `ai.read`.
- `/v1/integrations/*`: `integrations.write`.
- `/v1/legal/*`: `legal.write` + central + step-up MFA.
- `/v1/economy/*`: `economy.write` + central + step-up MFA.
- `/v1/defense/*`: section/central access; each endpoint requires `defense.read` or `defense.write`.

### 3.4 MFA and step-up

MFA implementation includes:

- TOTP enrollment start: `POST /v1/auth/mfa/enroll/start`
- TOTP enrollment verify: `POST /v1/auth/mfa/enroll/verify`
- TOTP disable: `POST /v1/auth/mfa/disable`

Login behavior:

- If user has MFA enabled and no OTP is provided, login returns `401 mfa_code_required`.
- Access token and principal include MFA state (`mfa_authenticated`, `mfa_at`).

Step-up behavior:

- Enforced by `require_step_up`.
- Max age is `AUTH_STEP_UP_MINUTES`.
- Can be globally toggled with `AUTH_CENTRAL_MFA_REQUIRED`.

## 4) Section Tenancy Model

Section tenancy is propagated end-to-end:

- Source registration: `source_registry.section_code`
- Ledger events: `event_log.section_code`
- Audit trail: `audit_log.section_code`
- Search index docs: `section_code`
- Streaming envelopes: `source.section_code`

Enforcement:

- Section users can only query rows/docs for their own `section_code`.
- Central users can query across sections.

## 5) Ingestion Pipeline

Main entry points:

- `POST /v1/ingest/event`
- `POST /v1/ingest/batch`
- `GET /v1/ingest/schema`

Pipeline stages (`IngestionService.ingest_event`):

1. Validate source API key against source registry and active status.
2. Normalize + validate canonical event.
3. Pseudonymize sensitive anchors/payload fields.
4. Resolve classification and optional signature verification.
5. Compute deterministic `event_hash`.
6. Append-only insert into ledger (`accepted` or `duplicate`).
7. Always write audit entry.
8. Best-effort fan-out on `accepted`:
   - OpenSearch index
   - graph delta generation/logging
   - Kafka event + graph topics

Extended event types supported include:

- `WEB_ATTACK_EVENT`
- `VULNERABILITY_EVENT`
- `BACKUP_ATTESTATION_EVENT`
- `INCIDENT_RESPONSE_EVENT`

## 6) Integrations Connectors

Connector APIs:

- `GET /v1/integrations/connectors`
- `POST /v1/integrations/{connector_key}/event`
- `POST /v1/integrations/{connector_key}/batch`

Implemented connector families include:

- identity/login (`splunk_login_v1`)
- banking (`core_banking_tx_v1`)
- edge/ddos (`cloudflare_ddos_v1`)
- telco sim swap (`telco_sim_swap_v1`)
- local network probe (`local_network_probe_v1`)
- db audit (`pgaudit_event_v1`)
- file integrity (`wazuh_fim_v1`)
- dfir artifacts (`velociraptor_artifact_v1`)
- BEC mail (`m365_bec_mail_v1`)
- WAF/API attacks (`waf_api_attack_v1`)
- KEV vulnerabilities (`kev_vuln_feed_v1`)
- backup attestations (`backup_attestation_v1`)

## 7) Defense Domain

Defense APIs are under `/v1/defense` and provide:

- Vulnerability intake + listing + patch SLA scoring.
- Backup immutability attestations.
- Restore drill evidence and risk signaling.
- Incident playbook runs + containment actions.
- Threat alert querying and refresh.
- Crypto posture read + signed snapshots.

Threat alert types currently emitted:

- `bec_risk`
- `web_attack_surge`
- `vuln_overdue`
- `backup_risk`

Threat pattern worker:

- module: `app.analytics.layer3.threat_pattern_worker`
- supports optional section-scoped execution.

## 8) Data Model Additions (Security/Defense)

Recent model extensions include:

- `auth_user` MFA fields (`mfa_enabled`, encrypted secrets, enrollment timestamp).
- tenancy columns on source/event/audit tables (`section_code`).
- `threat_alert` table for normalized risk alerts.
- defense tables:
  - `vulnerability_finding`
  - `patch_sla_decision`
  - `backup_attestation`
  - `restore_drill`
  - `incident_playbook_run`
  - `containment_action`
  - `crypto_posture_snapshot`

Migration chain:

- `20260224_0002` (AI/legal expansion)
- `20260224_0003` (auth foundation)
- `20260224_0004` (tenancy + MFA + threat alert + defense tables)

## 9) Environment Configuration (Critical)

Minimum required production configuration:

- database and storage:
  - `DATABASE_URL`
  - `OPENSEARCH_HOST`
  - `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`
- API auth:
  - `API_AUTH_DISABLED=false`
  - `FRONTEND_API_KEY` and `INGEST_API_KEY` set to strong values
- user auth and token security:
  - `AUTH_ENABLED=true`
  - `AUTH_TOKEN_SECRET` strong random value
  - `AUTH_PASSWORD_PEPPER` strong random value
  - `AUTH_MFA_SECRET_KEY` strong random value
  - `AUTH_CENTRAL_MFA_REQUIRED=true`
- privacy:
  - `PSEUDONYM_SALT` strong random value
- crypto posture policy:
  - `CRYPTO_TLS_MODE`
  - `CRYPTO_PQC_MODE`
  - `CRYPTO_KMS_PROVIDER`
  - `CRYPTO_KEY_ROTATION_DAYS`

Do not commit `.env`. Use `.env.example` as template only.

Runtime guard:

- Startup runs `app.core.runtime_hardening.enforce_runtime_hardening`.
- In strict environments (`APP_ENV` outside development/test), insecure flags and weak secrets fail startup.
- In development, the same issues are logged as warnings.

## 10) Operations and Release

### 10.1 Startup and migration order

1. Start infrastructure services.
2. Run migrations to `head`.
3. Start backend.
4. Seed ingestion sources if environment is new.
5. Verify `/health` and `/ready`.

### 10.2 Repository quality gate

Run before push:

```bash
./scripts/repo_health_check.sh
```

This checks:

- `.env` not tracked
- suspicious default tokens not committed
- no oversized tracked files
- no empty Python source files
- baseline test inventory threshold
- Python syntax compilation
- mounted route conflict detection
- API endpoint inventory doc freshness (`docs/API_ENDPOINT_INVENTORY.md`)

### 10.3 Health endpoints

- `GET /health`: API and DB liveness.
- `GET /ready`: component readiness (postgres/opensearch/neo4j).

## 11) Troubleshooting

### Auth failures

- `401 invalid_api_key`: verify `X-API-Key` and env config.
- `401 mfa_code_required`: submit OTP in login payload.
- `403 mfa_step_up_required` or `403 mfa_step_up_expired`: re-authenticate with MFA and retry.

### Missing data in APIs

- check `event_log` row count
- check OpenSearch index health and docs
- check graph delta generation and worker execution

### No threat alerts

- ensure relevant event types are ingested
- run threat pattern worker manually
- verify section filter (section user only sees own section)

## 12) Documentation Index

- Quick start + commands: `docs/RUNBOOK.md`
- Cloud backend deployment: `docs/RENDER_BACKEND_ONLY.md`
- API consumer examples: `docs/API_CONSUMER_GUIDE.md`
- Generated endpoint inventory: `docs/API_ENDPOINT_INVENTORY.md`
- Phase 2 hardening baseline: `docs/QUALITY_HARDENING_PHASE2.md`
- Delivery tracker: `docs/PHASES_90_TRACKER.md`
- This backend reference: `docs/BACKEND_DOCUMENTATION.md`

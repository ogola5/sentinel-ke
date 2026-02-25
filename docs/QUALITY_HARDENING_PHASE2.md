# Phase 2 Quality Hardening

This document defines the Phase 2 backend hardening baseline for Sentinel-KE.
It focuses on reliability, security-by-default, code organization, and documentation hygiene.

## Scope

Phase 2 includes:

- Runtime startup hardening checks (fail-fast in strict environments).
- Centralized router registration and route dependency policy.
- Standardized API error contract and request tracing.
- HTTP response hardening headers and request logging controls.
- Route conflict detection and endpoint inventory synchronization.
- Repository quality gates for secrets/defaults, source hygiene, syntax, and docs sync.

## Implemented Controls

### 1) Startup hardening guard

`backend/app/core/runtime_hardening.py` enforces environment policy:

- strict environments (`APP_ENV` not in development/test/local) reject:
  - `API_AUTH_DISABLED=true`
  - `INGEST_ALLOW_UNAUTH=true`
  - `DB_AUTO_CREATE=true`
  - disabled security headers
  - weak/missing critical secrets
  - wildcard CORS
- development environments log warnings instead of blocking startup.

### 2) API wiring organization

`backend/app/main.py` now uses a factory pattern:

- `create_application()`
- `_register_routers()`
- `_register_operational_routes()`
- `_register_lifecycle()`

This keeps router wiring, lifecycle behavior, and operational endpoints explicit and testable.

### 3) Router policy registry

`backend/app/api/router_registry.py` is the single source for mounted routers and policy dependencies.
This reduces drift between declared routes and authorization requirements.

### 4) Error contract

`backend/app/api/error_contract.py` provides a consistent error envelope:

- legacy `detail` for compatibility
- structured `error` object (`code`, `message`, `status`, `request_id`, `path`)

### 5) HTTP hardening middleware

`backend/app/core/http_hardening.py` standardizes:

- request ID generation/propagation
- baseline anti-cache and anti-sniff headers
- HSTS on HTTPS requests
- optional structured request logging

### 6) Quality scripts and documentation synchronization

- `scripts/check_route_conflicts.py`: detects duplicate method+path routes for mounted routers only.
- `scripts/generate_api_inventory.py`: generates/validates `docs/API_ENDPOINT_INVENTORY.md`.
- `scripts/repo_health_check.sh`: now includes:
  - empty Python file detection
  - route conflict check
  - API inventory freshness check

## Canonical/UCIC-style Alignment

This is not a formal compliance certificate. It is a practical alignment to common Ubuntu/Canonical hardening expectations:

- least privilege and explicit access control boundaries
- secure defaults and production fail-fast behavior
- traceability through request IDs and structured logs
- deterministic, reproducible quality checks in CI-friendly scripts
- documented controls and operational runbooks

## Required Pre-Push Checks

Run from repository root:

```bash
./scripts/repo_health_check.sh
```

Regenerate endpoint inventory when backend routes change:

```bash
python3 scripts/generate_api_inventory.py --write
```

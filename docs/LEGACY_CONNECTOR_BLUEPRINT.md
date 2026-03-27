# Legacy Connector Blueprint

This guide explains how to connect agency legacy systems to Sentinel-KE without forcing every partner to adopt a brand-new stack.

The core design rule is:

`Legacy system -> export/forward -> Sentinel connector API -> canonical event ledger -> graph + GNN + response`

Do not bypass the connector API if you want auditability and repeatable mappings.

## 1) Canonical Ingestion Seam

Sentinel-KE already exposes the right seam:

- `GET /v1/integrations/connectors`
- `POST /v1/integrations/{connector_key}/event`
- `POST /v1/integrations/{connector_key}/batch`

These routes:

- map legacy payloads into canonical events
- preserve source identity with `source_api_key`
- keep all ingestion inside the same evidence and audit path

See:

- [integrations.py](/home/ogola/personal/sentinel-ke/backend/app/api/integrations.py)
- [connectors.py](/home/ogola/personal/sentinel-ke/backend/app/integrations/connectors.py)

## 2) What Counts as a Legacy Source

In real agencies, "legacy" usually means one of these:

- flat-file CSV export from a SOC or NOC tool
- syslog/SIEM forwarder
- periodic database extract
- HTTP relay from an existing appliance
- message queue mirror

The practical MVP answer is:

- if the system can export rows or JSON, it can feed Sentinel-KE

## 3) Recommended Connector Patterns

### A. File export bridge

Best for:

- core banking
- telco SIM-swap logs
- billing or fraud reports
- WAF/CDN daily or minute-level exports

Use the bridge script:

```bash
python3 backend/scripts/legacy_connector_bridge.py \
  --base-url http://localhost:8000 \
  --connector-key vpn_gateway_session_v1 \
  --api-key <sentinel_api_key> \
  --source-api-key <registered_source_key> \
  --input /path/to/export.jsonl \
  --mode watch \
  --cursor-file /tmp/vpn_bridge_cursor.json
```

Supported file formats:

- CSV
- JSONL / NDJSON
- JSON array

### B. Existing product relay

Best for:

- Splunk
- SIEM appliances
- WAFs
- EDR/NDR products

Pattern:

- use the product webhook or export function
- POST mapped batches to `/v1/integrations/{connector_key}/batch`

### C. DB mirror or view

Best for:

- old internal systems that write to Oracle, SQL Server, or Postgres

Pattern:

- read from a replicated reporting view
- write changed rows to JSONL/CSV
- let the bridge script forward them

This is often safer than direct production DB coupling.

## 4) Strong Demo Examples

### VPN gateway logs

Use connector:

- `vpn_gateway_session_v1`

Typical exported fields:

- `timestamp`
- `client_ip`
- `device_id`
- `username`
- `result`
- `provider`
- `country`

### Telco SIM-swap events

Use connector:

- `telco_sim_swap_v1`

Typical exported fields:

- `timestamp`
- `phone_number`
- `subscriber_id`
- `device_id`
- `provider_id`
- `reason`

### Core banking transactions

Use connector:

- `core_banking_tx_v1`

Typical exported fields:

- `timestamp`
- `src_account`
- `dest_account`
- `amount`
- `channel`
- `device_id`
- `ip`

### WAF / DDoS / web attacks

Use connectors:

- `waf_api_attack_v1`
- `suricata_eve_v1`

## 5) What This Enables

Once the data crosses the connector API, the rest of Sentinel-KE can work:

1. canonical ingestion
2. graph projection
3. graph feature snapshots
4. GNN inference
5. explanations
6. campaign grouping
7. containment and reporting

That is why the connector API is the right answer to "how do you ingest from legacy systems?"

## 6) When To Build a New Connector

Build a new connector when:

- the payload shape is repeated and operationally important
- you need stable required fields
- the mapping logic is specific enough that generic JSON passthrough is too loose

The connector lives in:

- [connectors.py](/home/ogola/personal/sentinel-ke/backend/app/integrations/connectors.py)

Each new connector should define:

- required fields
- mapper function
- canonical event type
- anchor derivation
- normalization of statuses and severities

## 7) Judge-Safe Answer

If asked how Sentinel-KE connects to legacy agency systems, say:

> "We do not force partners to replace their tools. We provide a connector API with stable schemas, and we can bridge file exports, SIEM relays, or mirrored reporting views into that API. Once data lands there, it goes through the same audited graph, GNN, and response pipeline as native events."

## 8) What To Avoid Saying

Do not say:

- `We need every agency to rewrite their systems.`
- `We ingest by manually loading data into the database.`
- `Legacy integration is future work only.`

The stronger truthful answer is:

- the ingestion seam already exists
- the mapping layer already exists
- the new bridge script makes file-export integration practical today

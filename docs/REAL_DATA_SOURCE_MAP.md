# Sentinel-KE Real Data Source Map

Last reviewed: 2026-03-01 (Africa/Nairobi)

## Goal

Use real-world data wherever possible for backend ingestion and GNN training/inference validation.  
Use synthetic data only for event classes where public, legal, or privacy-safe datasets are not available.

## What Your Backend Already Supports

Current ingestion paths in codebase:

- Canonical ingest API: `POST /v1/ingest/event`, `POST /v1/ingest/batch`
- Connector ingest API: `GET /v1/integrations/connectors`, `POST /v1/integrations/{connector_key}/event`, `POST /v1/integrations/{connector_key}/batch`
- Existing connector mappings in `backend/app/integrations/connectors.py`:
  - `splunk_login_v1` -> `LOGIN_EVENT`
  - `core_banking_tx_v1` -> `TRANSACTION_EVENT`
  - `cloudflare_ddos_v1` -> `DDOS_SIGNAL_EVENT`
  - `telco_sim_swap_v1` -> `SIM_SWAP_EVENT`
  - `local_network_probe_v1` -> `SERVICE_HEALTH_EVENT`
  - `pgaudit_event_v1` -> `DB_AUDIT_EVENT`
  - `wazuh_fim_v1` -> `FILE_INTEGRITY_EVENT`
  - `velociraptor_artifact_v1` -> `DFIR_FINDING_EVENT`
  - `m365_bec_mail_v1` -> `PHISHING_MESSAGE_EVENT`
  - `waf_api_attack_v1` -> `WEB_ATTACK_EVENT`
  - `kev_vuln_feed_v1` -> `VULNERABILITY_EVENT`
  - `backup_attestation_v1` -> `BACKUP_ATTESTATION_EVENT`

## Kenya Threat Priority (For Data Collection Order)

From CA Kenya Q2 2025-2026 report:

- System vulnerabilities: 34.7%
- System attacks: 27.2%
- Web attacks: 25.3%
- Within web attacks, DDoS is dominant (48.2%)
- Social engineering incidents are phishing-heavy (70.4%)

Implication: prioritize vulnerability + DDoS/web + phishing datasets first.

## Event-to-Source Mapping

| Sentinel Event Type | Real Data Sources (Primary) | Integration Status | Data Readiness |
|---|---|---|---|
| `VULNERABILITY_EVENT` | CISA KEV, NVD feeds, FIRST EPSS API | Connector exists (`kev_vuln_feed_v1`) | High |
| `DDOS_SIGNAL_EVENT` | CSE-CIC-IDS2018, CIC-DDoS2019, CAIDA DDoS traces, partner edge telemetry | Connector exists (`cloudflare_ddos_v1`) | High |
| `WEB_ATTACK_EVENT` | CSE-CIC-IDS2018 web attack traffic, WAF logs | Connector exists (`waf_api_attack_v1`) | High |
| `PHISHING_MESSAGE_EVENT` | URLhaus, PhishTank, OpenPhish, enterprise mail telemetry | Connector exists (`m365_bec_mail_v1`) | Medium-High |
| `LOGIN_EVENT` | LANL auth dataset, enterprise IdP/SIEM auth logs | Connector exists (`splunk_login_v1`) | Medium-High |
| `TRANSACTION_EVENT` | PaySim (public simulation), partner core banking/mobile money events | Connector exists (`core_banking_tx_v1`) | Medium |
| `SIM_SWAP_EVENT` | Telco internal feeds (not publicly open) | Connector exists (`telco_sim_swap_v1`) | Low public, High private |
| `AIRTIME_TRANSFER_EVENT` | Telco billing internal records | No dedicated connector yet | Low public, High private |
| `BILLING_FRAUD_EVENT` | Telco billing/roaming fraud internal records | No dedicated connector yet | Low public, High private |
| `DOMAIN_REG_EVENT` | RDAP/WHOIS/newly-registered-domain feeds | No dedicated connector yet | Medium |
| `DNS_RESOLUTION_EVENT` | Enterprise resolver logs, passive DNS feeds | No dedicated connector yet | Medium |
| `SERVICE_HEALTH_EVENT` | Local/edge probe telemetry | Connector exists (`local_network_probe_v1`) | High |
| `DB_AUDIT_EVENT` | pgAudit logs | Connector exists (`pgaudit_event_v1`) | High |
| `FILE_INTEGRITY_EVENT` | Wazuh/syscheck logs | Connector exists (`wazuh_fim_v1`) | High |
| `DFIR_FINDING_EVENT` | Velociraptor hunt/artifact results | Connector exists (`velociraptor_artifact_v1`) | High |
| `BACKUP_ATTESTATION_EVENT` | Backup platform attestations (object lock, retention) | Connector exists (`backup_attestation_v1`) | High |
| `INCIDENT_RESPONSE_EVENT` | SOAR/ticketing/IR orchestration logs | No dedicated connector yet | Medium private |

## Real vs Synthetic Policy

Use real data now:

- `VULNERABILITY_EVENT`
- `DDOS_SIGNAL_EVENT`
- `WEB_ATTACK_EVENT`
- `PHISHING_MESSAGE_EVENT`
- `LOGIN_EVENT`
- `SERVICE_HEALTH_EVENT`
- `DB_AUDIT_EVENT`
- `FILE_INTEGRITY_EVENT`
- `DFIR_FINDING_EVENT`
- `BACKUP_ATTESTATION_EVENT`

Use synthetic fallback now (until private partner data is connected):

- `SIM_SWAP_EVENT`
- `AIRTIME_TRANSFER_EVENT`
- `BILLING_FRAUD_EVENT`
- `TRANSACTION_EVENT` (if no partner transaction feed yet)
- `DOMAIN_REG_EVENT` (if no feed contract yet)
- `DNS_RESOLUTION_EVENT` (if no resolver export yet)
- `INCIDENT_RESPONSE_EVENT` (if no SOAR integration yet)

Current synthetic generators already available:

- `backend/app/demo/synthetic_ke_gnn_data.py`
- `backend/app/demo/synthetic_corruption_data.py`
- `simulator/scenarios/*.json`

## Practical Ingestion Order (No Backend Refactor Needed)

1. Start with `VULNERABILITY_EVENT` using `kev_vuln_feed_v1` plus EPSS enrichment.
2. Ingest `WEB_ATTACK_EVENT` and `DDOS_SIGNAL_EVENT` from public datasets + edge telemetry through existing connectors.
3. Add phishing threat-intel feed transformation into canonical `PHISHING_MESSAGE_EVENT` through `/v1/ingest/event`.
4. Keep SIM-swap and telco fraud families synthetic until partner APIs are available.
5. Validate GNN on mixed data windows: real cyber telemetry + synthetic telco-only classes.

## Data Governance Minimums

- Keep only pseudonymized anchors (`phone_h`, `account_h`, `person_h`) for sensitive identities.
- Store source provenance (dataset name, version, retrieval date) with each import job.
- Respect per-source license terms before redistribution.
- Separate training/evaluation by time-window to avoid leakage.
- Follow hybrid split policy in `docs/GNN_HYBRID_SPLIT_PLAN.md`.

## Source Registry (Verified Links)

- Kenya CA reports portal: https://www.ca.go.ke/reports-and-studies
- Kenya CA Q2 2025-2026 cyber report PDF: https://www.ca.go.ke/sites/default/files/2026-01/Cyber%20Security%20Report%20Q2%202025-2026.pdf
- CISA KEV dataset repo: https://github.com/cisagov/kev-data
- NVD data feeds: https://nvd.nist.gov/vuln/data-feeds
- FIRST EPSS API: https://api.first.org/data/v1/epss
- URLhaus API docs: https://urlhaus.abuse.ch/api/
- PhishTank API docs: https://dev.phishtank.com/api_info.php
- OpenPhish feeds: https://openphish.com/phishing_feeds.html
- Tranco benign domain list: https://tranco-list.eu/
- CSE-CIC-IDS2018 (AWS Open Data): https://registry.opendata.aws/cse-cic-ids2018/
- CIC IDS2018 dataset page: https://www.unb.ca/cic/datasets/ids-2018.html
- CIC-DDoS2019 dataset (Mendeley): https://data.mendeley.com/datasets/ssnc74xm6r/1
- CAIDA DDoS dataset: https://www.caida.org/catalog/datasets/ddos-20070804_dataset/
- LANL auth dataset: https://csr.lanl.gov/data/auth/
- LANL multi-source cyber dataset: https://csr.lanl.gov/data/cyber1/
- PaySim reference simulator: https://github.com/EdgarLopezPhD/PaySim
- PaySim Kaggle mirror: https://www.kaggle.com/datasets/ealaxi/paysim1

# Sentinel-KE Real Data Source Map

Last reviewed: 2026-03-25 (Africa/Nairobi)

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
  - `crowdsec_alert_v1` -> `DFIR_FINDING_EVENT`
  - `falco_runtime_v1` -> `DFIR_FINDING_EVENT`
  - `tetragon_runtime_v1` -> `DFIR_FINDING_EVENT`
  - `coraza_waf_v1` -> `WEB_ATTACK_EVENT`
  - `suricata_eve_v1` -> `DDOS_SIGNAL_EVENT | WEB_ATTACK_EVENT | DFIR_FINDING_EVENT`
  - `zeek_notice_v1` -> `DFIR_FINDING_EVENT`
  - `feodo_c2_v1` -> `DFIR_FINDING_EVENT`
  - `urlhaus_ioc_v1` -> `DFIR_FINDING_EVENT`
  - `threatfox_ioc_v1` -> `DFIR_FINDING_EVENT`
  - `malwarebazaar_sample_v1` -> `DFIR_FINDING_EVENT`
  - `vpn_gateway_session_v1` -> `LOGIN_EVENT`
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
| `DDOS_SIGNAL_EVENT` | CSE-CIC-IDS2018, CIC-DDoS2019, CAIDA DDoS traces, partner edge telemetry, Suricata EVE alerts | Connectors exist (`cloudflare_ddos_v1`, `suricata_eve_v1`) | High |
| `LOGIN_EVENT` (VPN benchmark rows) | ISCX VPN-nonVPN 2016, enterprise VPN gateway logs | Connectors exist (`splunk_login_v1`, `vpn_gateway_session_v1`) | Medium |
| `WEB_ATTACK_EVENT` | CSE-CIC-IDS2018 web attack traffic, WAF logs, Suricata EVE HTTP alerts, Coraza/OWASP CRS alerts | Connectors exist (`waf_api_attack_v1`, `suricata_eve_v1`, `coraza_waf_v1`) | High |
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
| `DFIR_FINDING_EVENT` | Velociraptor hunt/artifact results, Zeek notices, Suricata non-web alerts, CrowdSec alerts, Falco runtime alerts, Tetragon runtime telemetry, URLhaus, ThreatFox, MalwareBazaar, Feodo, OTX | Connectors exist (`velociraptor_artifact_v1`, `zeek_notice_v1`, `suricata_eve_v1`, `crowdsec_alert_v1`, `falco_runtime_v1`, `tetragon_runtime_v1`, `urlhaus_ioc_v1`, `threatfox_ioc_v1`, `malwarebazaar_sample_v1`, `feodo_c2_v1`, `otx_indicator_v1`) | High |
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
6. Use the dedicated corruption loaders for public procurement and case outcomes instead of ad hoc snapshots.

## Implemented Real-Source Commands

Corruption:

- `python -m app.analytics.corruption.ppra_awards_ingest --input-file data/ppra_awards.csv`
- `python -m app.analytics.corruption.ppra_arb_ingest --input-file data/ppra_arb.csv`
- `python -m app.analytics.corruption.public_case_outcome_ingest --source kenyalaw --input-file data/kenyalaw_cases.jsonl`
- `python -m app.analytics.corruption.public_case_outcome_ingest --source eacc --input-file data/eacc_cases.jsonl`

Cyber:

- `python -m app.integrations.real_data_pipeline urlhaus --source-api-key ... --urlhaus-file data/urlhaus.csv`
- `python -m app.integrations.real_data_pipeline threatfox --source-api-key ... --threatfox-file data/threatfox.json`
- `python -m app.integrations.real_data_pipeline malwarebazaar --source-api-key ... --malwarebazaar-file data/malwarebazaar.json`
- `python -m app.integrations.real_data_pipeline vpn-benchmark --source-api-key ... --input-file data/iscx_vpn2016.csv`
- `python -m app.integrations.real_data_pipeline ddos-benchmark --source-api-key ... --dataset cic --input-file data/cic_ddos2019.csv`
- `python -m app.integrations.real_data_pipeline ddos-benchmark --source-api-key ... --dataset caida --input-file data/caida_ddos.json`

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
- ThreatFox docs: https://threatfox.abuse.ch/
- MalwareBazaar API docs: https://bazaar.abuse.ch/api/
- PhishTank API docs: https://dev.phishtank.com/api_info.php
- OpenPhish feeds: https://openphish.com/phishing_feeds.html
- Tranco benign domain list: https://tranco-list.eu/
- CSE-CIC-IDS2018 (AWS Open Data): https://registry.opendata.aws/cse-cic-ids2018/
- CIC IDS2018 dataset page: https://www.unb.ca/cic/datasets/ids-2018.html
- CIC-DDoS2019 dataset (Mendeley): https://data.mendeley.com/datasets/ssnc74xm6r/1
- CAIDA DDoS dataset: https://www.caida.org/catalog/datasets/ddos-20070804_dataset/
- ISCX VPN-nonVPN 2016 dataset: https://www.unb.ca/cic/datasets/vpn.html
- LANL auth dataset: https://csr.lanl.gov/data/auth/
- LANL multi-source cyber dataset: https://csr.lanl.gov/data/cyber1/
- PaySim reference simulator: https://github.com/EdgarLopezPhD/PaySim
- PaySim Kaggle mirror: https://www.kaggle.com/datasets/ealaxi/paysim1
- PPRA contract awards portal: https://ppra.go.ke/contract-awards/
- PPRA ARB decisions: https://ppra.go.ke/arb-decisions/
- Kenya Law judgments: https://new.kenyalaw.org/judgments/
- EACC anti-corruption judgments/rulings: https://eacc.go.ke/en/default/anti-corruption-judgements-rulings/

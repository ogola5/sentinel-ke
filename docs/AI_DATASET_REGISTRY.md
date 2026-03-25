# Sentinel-KE AI Dataset Registry

Last reviewed: 2026-03-25 (Africa/Nairobi)

## Purpose

This registry tracks the real datasets and public feeds used for GNN/ML ingestion, training, and evaluation.

Principles:
- prefer real public or partner data over synthetic data
- keep benchmark corpora separate from live operational feeds
- land cyber data through the existing connector and canonical ingest path
- land corruption data through the existing procurement/outcome loaders so it still reaches `event_log`, `event_entity_index`, and `graph_feature_snapshot`

## Registered Sources

| Source Key | Domain | Class | Format(s) | Current Entry Point | Label Quality | Status |
|---|---|---|---|---|---|---|
| `ppra_awards` | corruption | public_gov_source | CSV, JSON, JSONL | `python -m app.analytics.corruption.ppra_awards_ingest --input-file ...` | silver | implemented |
| `ppra_arb` | corruption | public_gov_source | CSV, JSON, JSONL | `python -m app.analytics.corruption.ppra_arb_ingest --input-file ...` | gold/silver | implemented |
| `kenyalaw_outcomes` | corruption | public_gov_source | CSV, JSON, JSONL | `python -m app.analytics.corruption.public_case_outcome_ingest --source kenyalaw --input-file ...` | gold | implemented |
| `eacc_outcomes` | corruption | public_gov_source | CSV, JSON, JSONL | `python -m app.analytics.corruption.public_case_outcome_ingest --source eacc --input-file ...` | gold/silver | implemented |
| `urlhaus` | cyber | operational_feed | CSV, JSON | `python -m app.integrations.real_data_pipeline urlhaus ...` | silver | implemented |
| `threatfox` | cyber | operational_feed | JSON, CSV | `python -m app.integrations.real_data_pipeline threatfox ...` | silver | implemented |
| `malwarebazaar` | cyber | operational_feed | JSON, CSV | `python -m app.integrations.real_data_pipeline malwarebazaar ...` | silver | implemented |
| `vpn_benchmark` | cyber | benchmark | CSV, JSON, JSONL | `python -m app.integrations.real_data_pipeline vpn-benchmark ...` | benchmark | implemented |
| `ddos_benchmark_cic` | cyber | benchmark | CSV, JSON, JSONL | `python -m app.integrations.real_data_pipeline ddos-benchmark --dataset cic ...` | benchmark | implemented |
| `ddos_benchmark_caida` | cyber | benchmark | CSV, JSON, JSONL | `python -m app.integrations.real_data_pipeline ddos-benchmark --dataset caida ...` | benchmark | implemented |
| `paysim` | fraud | benchmark | CSV | `python -m app.integrations.real_data_pipeline paysim ...` and `python scripts/run_paysim_gnn.py ...` | benchmark | implemented |

## Source-to-Code Map

| Source Key | Main Code |
|---|---|
| `ppra_awards` | `backend/app/analytics/corruption/ppra_awards_ingest.py` |
| `ppra_arb` | `backend/app/analytics/corruption/ppra_arb_ingest.py` |
| `kenyalaw_outcomes`, `eacc_outcomes` | `backend/app/analytics/corruption/public_case_outcome_ingest.py` |
| `urlhaus`, `threatfox`, `malwarebazaar`, `vpn_benchmark`, `ddos_benchmark_*` | `backend/app/integrations/real_data_pipeline.py`, `backend/app/integrations/connectors.py` |

## Notes

- `ppra_awards` is a procurement graph source, not a final corruption verdict.
- `ppra_arb`, `kenyalaw_outcomes`, and `eacc_outcomes` are stronger supervision than weak heuristic flags.
- `vpn_benchmark` identifies VPN-like sessions. It must not be presented as direct maliciousness labeling.
- `ddos_benchmark_*` is for attack-shape learning and evaluation, not a replacement for live edge telemetry.
- `urlhaus`, `threatfox`, and `malwarebazaar` expand malware and IOC relationships. They do not by themselves prove endpoint compromise.

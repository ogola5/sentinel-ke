# Top-15 KPI / Evidence Sheet

Last updated: 2026-03-26

This sheet is intentionally narrow: each row ties a metric or evidence artifact to an existing repo fact. If a value is pending, it is marked pending instead of being approximated.

| # | KPI or evidence item | Current repo fact | Source(s) |
|---|---|---|---|
| 1 | Cyber AUC | `0.8928` | `docs/BENCHMARK_SUMMARY.md`, `docs/THREE_LANE_AI_STORY.md` |
| 2 | Cyber graph size | `97` nodes, `237` edges | `docs/BENCHMARK_SUMMARY.md`, `docs/THREE_LANE_AI_STORY.md` |
| 3 | Cyber holdout | Temporal holdout on `Wmid` | `docs/BENCHMARK_SUMMARY.md`, `docs/THREE_LANE_AI_STORY.md`, `backend/scripts/train_cyber_gnn.py` |
| 4 | Fraud benchmark identity | PaySim, 6.3M M-Pesa-style transactions, 8,213 fraud accounts | `docs/BENCHMARK_SUMMARY.md`, `docs/THREE_LANE_AI_STORY.md`, `docs/FRAUD_BENCHMARK_POSITIONING.md` |
| 5 | Fraud benchmark status | Fresh PaySim artifact still required before quoting a judge-safe AUC | `docs/BENCHMARK_SUMMARY.md`, `docs/THREE_LANE_AI_STORY.md`, `backend/scripts/run_paysim_gnn.py` |
| 6 | Corruption graph size | `1,982` nodes, `4,158` edges | `docs/THREE_LANE_AI_STORY.md`, `docs/BENCHMARK_SUMMARY.md` |
| 7 | Corruption model status | Fairness hardening in progress; classifier AUC is not yet judge-safe | `docs/THREE_LANE_AI_STORY.md`, `docs/BENCHMARK_SUMMARY.md`, `backend/app/analytics/corruption/train_worker.py` |
| 8 | `/health` benchmark | `120` complete, `0` failed, p50 `98 ms`, p95 `193 ms`, p99 `203 ms`, `86.05` req/s | `docs/PERFORMANCE_SLO_EVIDENCE.md` |
| 9 | `/v1/metrics` benchmark | `180` complete, `178` length mismatches reported by the tool, p50 `187 ms`, p95 `245 ms`, p99 `268 ms`, `101.14` req/s | `docs/PERFORMANCE_SLO_EVIDENCE.md` |
| 10 | Controlled replay benchmark | `200` loaded, `72` schema-valid, `72` accepted, `0` failures, effective replay RPS `49.75`, latency p50/p95/p99 `35.39 / 67.9 / 108.51 ms` | `docs/PERFORMANCE_SLO_EVIDENCE.md` |
| 11 | Rate-limit guardrail | Burst tests crossed policy thresholds and returned non-2xx responses instead of crashing the backend | `docs/PERFORMANCE_SLO_EVIDENCE.md` |
| 12 | Baseline API | `GET /v1/ai/baselines` with filters for `window_key` and `entity_key` | `backend/app/api/ai.py` |
| 13 | Baseline fields | `baseline_score`, `baseline_std`, `sample_count`, `last_window_end` | `backend/app/api/ai.py`, `backend/app/analytics/layer3/baseline_worker.py`, `backend/app/analytics/ai_models.py` |
| 14 | Model run fields | `auc`, `precision`, `recall`, `f1`, `artifact_path`, plus `metrics_json` | `backend/app/analytics/ai_models.py`, `backend/app/analytics/layer3/gnn_train_worker.py` |
| 15 | Evidence surfaces | `AIExplanation` evidence hashes/paths, legal evidence export/list/anchor/refresh endpoints, and the real data source map | `backend/app/analytics/ai_models.py`, `backend/app/analytics/layer3/trust_service.py`, `backend/app/api/legal.py`, `docs/REAL_DATA_SOURCE_MAP.md` |

## How To Use This Sheet

- Use rows 1 to 7 for lane-specific benchmark claims.
- Use rows 8 to 11 for runtime and operational proof.
- Use rows 12 to 15 when a judge asks how the model, baseline, and evidence chain are separated.

## Notes

- Fraud AUC is intentionally not quoted here because the repo still needs a fresh PaySim artifact.
- Corruption AUC is not claimed because the repo explicitly says fairness hardening is still in progress.
- The `/v1/metrics` benchmark row keeps the original tool caveat: the failure count is a body-length mismatch, not a transport or status-code failure.

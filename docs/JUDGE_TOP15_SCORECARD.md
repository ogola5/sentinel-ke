# Sentinel-KE Top-15 Judge Scorecard

Last updated: 2026-03-26

This scorecard is a judge-facing evidence pack, not a marketing summary. It fixes three gaps directly:

- KPI/evidence sheet
- baseline-vs-model clarity
- honest lane-separated AI claims

Only repo facts are used here. Anything pending is labeled as such.

## Top 15

| # | Judge-safe claim | Repo evidence | Status |
|---|---|---|---|
| 1 | Sentinel-KE evaluates three separate AI lanes, not one mixed benchmark. | `docs/THREE_LANE_AI_STORY.md`, `docs/AI_BENCHMARK_STRATEGY.md`, `docs/BENCHMARK_SUMMARY.md` | Ready |
| 2 | The cyber lane has a documented AUC of 0.8928 on a real Kenyan cyber event graph. | `docs/BENCHMARK_SUMMARY.md`, `docs/THREE_LANE_AI_STORY.md`, `docs/REAL_DATA_TRAINING_RUNS.md` | Ready |
| 3 | The cyber benchmark is temporal and uses a small observed graph of 97 nodes and 237 edges. | `docs/BENCHMARK_SUMMARY.md`, `docs/THREE_LANE_AI_STORY.md` | Ready |
| 4 | The fraud lane uses PaySim as a separate benchmark and is not used to claim cyber or corruption performance. | `docs/FRAUD_BENCHMARK_POSITIONING.md`, `docs/AI_BENCHMARK_STRATEGY.md`, `docs/BENCHMARK_SUMMARY.md` | Ready |
| 5 | The fraud lane is a separate benchmark lane, but the repo does not quote a fresh AUC until the PaySim artifact is regenerated. | `docs/BENCHMARK_SUMMARY.md`, `docs/THREE_LANE_AI_STORY.md`, `docs/FRAUD_BENCHMARK_POSITIONING.md` | Ready with caveat |
| 6 | The corruption lane is not presented as a legal finding engine. It is presented as a risk-ranking and graph-visualization lane. | `docs/THREE_LANE_AI_STORY.md`, `backend/app/analytics/corruption/train_worker.py` | Ready |
| 7 | The corruption lane is still blocked by fairness hardening, so classifier AUC is not yet a judge-safe claim. | `docs/THREE_LANE_AI_STORY.md`, `docs/BENCHMARK_SUMMARY.md`, `backend/app/analytics/corruption/train_worker.py` | Ready |
| 8 | The repo has an explicit baseline API, separate from model inference. | `backend/app/api/ai.py` (`GET /v1/ai/baselines`) | Ready |
| 9 | The baseline rows are derived from prior `AIPrediction` rows and store `baseline_score`, `baseline_std`, `sample_count`, and `last_window_end`. | `backend/app/analytics/layer3/baseline_worker.py`, `backend/app/analytics/ai_models.py`, `backend/app/api/ai.py` | Ready |
| 10 | The model side stores its own run metadata, including `auc`, `precision`, `recall`, `f1`, and `artifact_path`. | `backend/app/analytics/ai_models.py`, `backend/app/analytics/layer3/gnn_train_worker.py` | Ready |
| 11 | The inference path is explicit about GNN-first execution and deterministic heuristic fallback. | `backend/app/analytics/layer3/ai_inference_worker.py` | Ready |
| 12 | Predictions store `decision_source`, so model output and fallback output are distinguishable. | `backend/app/analytics/ai_models.py`, `backend/app/analytics/layer3/ai_inference_worker.py` | Ready |
| 13 | Explanations can carry evidence hashes, evidence paths, recommended controls, and counterfactuals. | `backend/app/analytics/ai_models.py`, `backend/app/analytics/layer3/trust_service.py` | Ready |
| 14 | The repo has legal evidence export, listing, anchor, and refresh endpoints. | `backend/app/api/legal.py`, `docs/RUNBOOK.md` | Ready |
| 15 | The repo also documents runtime KPIs and controlled-load evidence for judging. | `docs/PERFORMANCE_SLO_EVIDENCE.md` | Ready |

## Judge Reading Order

1. Start with `docs/BENCHMARK_SUMMARY.md` for the lane split and headline numbers.
2. Read `docs/TOP15_KPI_EVIDENCE.md` for the concrete KPI/evidence sheet.
3. Read `docs/TOP15_BASELINE_STORY.md` for baseline-vs-model clarity and the lane-safe claim language.

## What This Pack Does Not Claim

- It does not claim fraud results validate cyber or corruption.
- It does not claim corruption scores are legal proof.
- It does not claim the baseline is the same thing as a trained model.
- It does not add new benchmark numbers beyond the repo record.

# Sentinel-KE Hybrid GNN Train/Eval Split Plan

Last reviewed: 2026-03-01 (Africa/Nairobi)

## Objective

Train one cyber GNN that uses:

- real telemetry for cyber classes where public/partner data exists, and
- synthetic data only for telco-private classes (`SIM_SWAP_EVENT`, `AIRTIME_TRANSFER_EVENT`, `BILLING_FRAUD_EVENT`).

The split policy must prevent optimistic leakage from synthetic-only patterns.

## Data Buckets

- `REAL_CORE`: entities/windows driven by real events:
  - `DDOS_SIGNAL_EVENT`, `WEB_ATTACK_EVENT`, `PHISHING_MESSAGE_EVENT`,
  - `LOGIN_EVENT`, `VULNERABILITY_EVENT`, `DB_AUDIT_EVENT`,
  - `FILE_INTEGRITY_EVENT`, `DFIR_FINDING_EVENT`, `SERVICE_HEALTH_EVENT`
- `SYNTH_TELCO`: entities/windows where the dominant suspicious signal comes from:
  - `SIM_SWAP_EVENT`, `AIRTIME_TRANSFER_EVENT`, `BILLING_FRAUD_EVENT`
- `MIXED`: windows with both real-core and telco-synthetic signals.

## Split Policy (Time-Ordered)

1. Sort by `window_end` ascending.
2. Use chronological slices:
   - train: oldest 70%
   - validation: next 15%
   - test: newest 15%
3. Never random-shuffle across windows.

Reason: attack behavior is non-stationary; time ordering gives realistic forward performance.

## Evaluation Tracks

Use two explicit tracks each run:

- `TRACK_A_REAL_CORE` (primary gate):
  - evaluation rows from validation/test where origin is real or mixed with real-core dominance
  - this is the score shown for production readiness
- `TRACK_B_TELCO_EXTENSION` (secondary gate):
  - evaluation rows containing telco-synthetic dominant patterns
  - used to monitor telco-family quality until real telco feeds are integrated

## Promotion Gates

Promote model only if all pass:

- `TRACK_A_REAL_CORE`:
  - AUC >= 0.85
  - precision >= 0.75
  - recall >= 0.70
- uncertainty:
  - abstention rate <= 0.25 on `TRACK_A_REAL_CORE`
- drift:
  - no critical drift report in latest cycle
- calibration:
  - risk-threshold metrics stable vs previous promoted run (+/- 10% tolerance)

`TRACK_B_TELCO_EXTENSION` is monitored but cannot override a failed `TRACK_A_REAL_CORE`.

## Leakage Controls

- Keep temporal split strict (`window_end` boundaries).
- Do not allow same `entity_key` in both train and test when windows overlap near cutoff.
- Record split manifest hash with `dataset_hash` in `GNNTrainingRun`.
- Persist source provenance (`real` vs `synthetic`) in run metadata.

## Practical Run Sequence

1. Ingest real feeds first:
   - KEV + EPSS
   - CIC/CAIDA normalized DDoS/Web rows
2. Ingest synthetic telco rows only for missing telco-private classes.
3. Run feature worker for target window.
4. Build split manifests (train/val/test + track labels).
5. Train + evaluate using both tracks.
6. Persist metrics and gate decision.

## Enforced in Code (current)

- `train_graphsage()` now records:
  - `split_policy` (`entity_hash_holdout` default)
  - `train_count`, `val_count`, `val_ratio_actual`
  - calibration metrics: `calibration_ece`, `calibration_mce`, `brier_score`
- `gnn_train_worker.run_once()` persists an `evaluation_protocol` block in
  `GNNTrainingRun.metrics_json` with:
  - temporal policy marker
  - holdout policy used
  - calibration summary
- `graph_feature_worker.run_once()` persists source provenance features:
  - `source_type_counts`
  - `provenance_tag` (`real|synthetic|mixed|unknown`)
  - `real_signal_ratio`
- `gnn_train_worker.run_once()` now stores:
  - `metrics_json.provenance` (dataset real/synthetic mix + high-risk breakdown)
  - `metrics_json.real_data_gate` with pass/fail against `GNN_MIN_REAL_RATIO`
- `drift_worker.run_once()` already adds live fairness disparity and status into
  `AIDriftReport.metrics_json["fairness_live"]`.

## Runtime Knobs

Set in environment for reproducible evaluation:

```
GNN_SPLIT_POLICY=entity_hash_holdout
GNN_VAL_RATIO=0.2
GNN_MIN_REAL_RATIO=0.3
FAIRNESS_DISPARITY_THRESHOLD=0.4
```

CLI override (one-off):

```
python -m app.analytics.layer3.gnn_train_worker \
  --window-key Wmid \
  --split-policy entity_hash_holdout \
  --val-ratio 0.2
```

## Exit Criteria to Remove Synthetic Telco

Once partner SIM-swap/billing feeds are live and stable for >= 30 days:

- reduce synthetic telco sampling weight each retrain cycle,
- switch `TRACK_B_TELCO_EXTENSION` from synthetic-heavy to real-heavy,
- retire synthetic telco from gating once real coverage exceeds 90% of telco-positive windows.

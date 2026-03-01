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

## Exit Criteria to Remove Synthetic Telco

Once partner SIM-swap/billing feeds are live and stable for >= 30 days:

- reduce synthetic telco sampling weight each retrain cycle,
- switch `TRACK_B_TELCO_EXTENSION` from synthetic-heavy to real-heavy,
- retire synthetic telco from gating once real coverage exceeds 90% of telco-positive windows.


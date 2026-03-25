# Sentinel-KE AI Benchmark Strategy

## Positioning

Sentinel-KE should present AI as graph-based pattern learning over connected entities, not as a generic claim that one model explains the whole platform.

The project has three separate evaluation lanes:

- `Fraud`: PaySim is the benchmark lane.
- `Cyber`: live cyber GNN runs on `Wmid` are the operational lane.
- `Corruption`: procurement / registry / payment / outcome graphs are the governance lane.

That separation matters. It keeps the presentation honest and prevents the fraud benchmark from being used to overstate cyber or corruption performance.

## What PaySim Proves

PaySim is the clean fraud benchmark because it gives a controlled, reproducible benchmark for ranking mobile-money fraud patterns.

Use PaySim to show:

- `AUC-ROC`
- `AUPRC` if available
- `precision`
- `recall`
- `calibration` or `ECE`
- `Brier score`
- reproducible artifact identity

Do not use PaySim to claim:

- cyber detection performance
- corruption detection performance
- end-to-end national deployment readiness
- perfect precision at an arbitrary threshold

The strongest honest statement is:

“PaySim proves the fraud GNN can rank risky mobile-money patterns strongly; threshold tuning and calibration still need operational work.”

## What Cyber Should Prove

Cyber should be shown as a separate graph-intelligence lane over operational telemetry.

Use cyber runs to show:

- graph feature freshness
- real-data ratio
- label-source mix
- attack family coverage
- path score and decision fusion behavior
- whether the latest run used a real GNN artifact or fallback

Do not use cyber runs to overstate the fraud benchmark.

The strongest honest statement is:

“Cyber GNN is the operational pattern learner for DDoS, VPN, phishing, malware, and infrastructure telemetry.”

## What Corruption Should Prove

Corruption should be shown as a procurement and integrity-risk graph, not as automatic proof of wrongdoing.

Use corruption runs to show:

- procurement chain coverage
- supplier-network linkage
- payment and milestone mismatch
- outcome or sanction labels when available
- provenance mix between real and synthetic records
- weak-label versus outcome-backed supervision

Do not use corruption runs to claim final adjudication.

The strongest honest statement is:

“Corruption GNN prioritizes connected procurement risk and outcome-linked evidence for review.”

## Recommended Metrics By Lane

Fraud:

- `AUC-ROC`
- `AUPRC`
- `precision`
- `recall`
- `ECE`
- `Brier score`

Cyber:

- `AUC-ROC`
- `precision@k`
- `real_data_ratio`
- `label_source_counts`
- `freshness`
- `path score` and `decision fusion` coverage

Corruption:

- `AUC-ROC`
- `precision@k`
- `outcome_label_rate`
- `real_vs_synthetic mix`
- `weak_label vs outcome-backed split`
- `explanation coverage`

## What Not To Overstate

- Do not say PaySim validates the whole AI stack.
- Do not say one cyber run proves national cyber readiness.
- Do not say corruption predictions are final legal findings.
- Do not hide calibration problems behind a single AUC number.
- Do not present weak-label runs as ground truth.

## Suggested Demo Order

1. Show the platform shell and the operational workflow.
2. Show the fraud benchmark result from PaySim.
3. Show the cyber operational lane on `Wmid`.
4. Show the corruption governance lane on `Wcorruption`.
5. Close with the message that the AI is graph-based, domain-informed, and evaluation-separated.

## Benchmark Summary Helper

Use the read-only helper to summarize benchmark artifacts without mixing the lanes:

```bash
python backend/scripts/summarize_benchmarks.py \
  --artifact backend/artifacts/paysim_auc.json
```

If you also have cyber or corruption artifact exports, pass them as extra `--artifact` values.

## Data Discipline

The repo should keep these distinctions visible in docs, scripts, and UI:

- benchmark artifacts for PaySim
- operational artifacts for cyber
- governance artifacts for corruption
- separate label-source metadata for each lane
- separate claims for each lane

That keeps the system credible and prevents the fraud benchmark from becoming the whole story.

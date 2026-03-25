# PaySim Fraud Benchmark Positioning

PaySim is Sentinel-KE’s fraud benchmark lane.

It is useful because it gives a reproducible, public, mobile-money-style fraud corpus that can validate graph-based ranking on a controlled dataset.

What PaySim should support:

- `AUC-ROC` for ranking quality
- `AUPRC` if reported
- `precision`, `recall`, and calibration metrics
- a reproducible benchmark artifact

What PaySim should not be used to claim:

- cyber model performance
- corruption model performance
- national deployment readiness
- perfect production precision
- end-to-end detection across all Sentinel-KE domains

The correct phrasing is:

“PaySim validates the fraud GNN lane. Cyber and corruption use their own data and evaluation stories.”

The wrong phrasing is:

“PaySim proves the whole AI platform.”

## Presentation Rules

- Show the PaySim result as one benchmark card.
- Keep cyber and corruption in separate cards or sections.
- Use PaySim to justify fraud ranking quality, not every AI claim.
- If precision is low but AUC is high, explain it as threshold/calibration work on an imbalanced fraud task.

## Metrics To Show

- `AUC-ROC`
- `AUPRC`
- `precision`
- `recall`
- `ECE`
- `Brier score`
- dataset identity
- run configuration

## Metrics To Avoid Overstating

- do not say “excellent precision” unless the artifact actually supports it
- do not say “production-ready fraud detection” unless thresholding and calibration are explicitly validated
- do not cite PaySim as evidence for cyber or corruption claims

## Recommended Command

```bash
docker exec sentinel-ke-backend-1 python /app/scripts/run_paysim_gnn.py \
  --csv /app/artifacts/paysim/PS_20174392719_1491204439457_log.csv \
  --max-rows 200000 \
  --window-key Wpaysim \
  --reset-window \
  --require-csv \
  --out /app/artifacts/paysim_auc.json
```

## Recommended Summary Line

“PaySim is the fraud benchmark; cyber and corruption are separate graph-intelligence lanes.”

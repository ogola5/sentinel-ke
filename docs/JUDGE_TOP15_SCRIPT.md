# Final Judge Script

Last updated: 2026-03-27

This script is aligned to the live `GET /v1/ai/judge-readiness` response, not to a static benchmark summary. Use it as the presentation path for Top 15 judging.

## Opening

Start with the executive brief and one sentence:

"Sentinel-KE is a sovereign intelligence platform with separate cyber, corruption, and fraud lanes. The judge-facing readiness view is live, but we keep the claims lane-separated and evidence-backed."

## What To Show

1. Open the judge brief in the UI.
2. Show the readiness state first, not the detailed model views.
3. Then show the per-lane evidence blocks.
4. End on the caveats so the judges see discipline, not overclaiming.

## Live Readiness

The live judge-readiness API currently returns `status: ok`.

Use that as the top-line claim:

"The readiness surface is green. The platform is not a demo shell; it has live baseline evidence, live threshold evidence, and live domain-health evidence."

## Cyber Lane

What the live API shows:

- `status: ok`
- latest run anchored to `Wmid`
- latest benchmarked run window: `2026-03-27T12:38:23.070268+00:00`
- latest run size: `2,500` nodes, `6,424` edges
- latest live prediction window matches the benchmarked run window
- `prediction_count: 2,500`
- `high_risk_count: 1,037`
- operating `f1: 0.7000`
- operating `precision: 0.7538`
- operating `recall: 0.6533`
- holdout `auc: 0.9682`
- baselines are present with `coverage_count: 2143`
- thresholds are present
- scientific evidence is `strong`

Say this:

"The cyber lane is ready and internally aligned. The judge-safe point is that the live predictions, thresholds, baselines, and run window now match, and the lane has strong recent scientific support across multiple benchmarkable windows. We still do not overclaim this as fully adjudicated national incident truth."

If asked about the caveat, say:

"There is a newer live prediction window in the background, but the judge view is anchored to the latest benchmarked run for like-for-like comparison. That keeps the presentation honest."

## Fraud Benchmark

What the live API shows:

- benchmark lane: `PaySim fraud benchmark`
- dataset: `PaySim (Kaggle ealaxi/paysim1)`
- fresh artifact timestamp: `2026-03-27T12:59:29.241868+00:00`
- holdout `AUC: 0.9555`
- holdout `PR-AUC: 0.9291`
- holdout `precision: 0.1251`
- holdout `recall: 1.0`
- holdout `f1: 0.2224`
- holdout sample count: `10,000`
- benchmark snapshots seeded: `528,809`

Say this:

"The fraud lane is a separate public benchmark lane. The ranking quality is strong on PaySim, and the fresh artifact is now present in the judge view. We also show the honest caveat that the current operating threshold is still conservative, so the AUC is stronger than the thresholded F1."

## Corruption Lane

What the live API shows:

- `status: ok`
- latest run anchored to `Wcorruption`
- latest run size: `2026` nodes, `3900` edges
- `AUC: 0.9135`
- `AUC: 0.9158`
- `precision: 0.975904`
- `recall: 0.72973`
- `f1: 0.835052`
- latest live prediction window matches the benchmarked run window
- `prediction_count: 2026`
- `high_risk_count: 249`
- thresholds are present
- baselines are present with `coverage_count: 1982`

Say this:

"The corruption lane is now a live graph-risk lane with thresholds and baselines. It is not presented as legal proof. It is presented as a prioritization and evidence layer over procurement and outcome data."

If asked about the caveat, say:

"The model is still partially weakly supervised, so the metrics are strong operational evidence, not fully adjudicated national ground truth."

## Baseline / Model Separation

Say this once:

"The baseline is a rolling statistical reference, not a second model. The model and the baseline are separate layers, and the UI shows both."

## Close

Close with one sentence:

"Sentinel-KE is judge-ready because it exposes live readiness, separate baseline evidence, live thresholds, a fresh fraud benchmark artifact, and clear caveats without collapsing the lanes into one mixed claim."

## Do Not Say

- Do not say the corruption lane is legal proof.
- Do not say the cyber lane proves every alert is correct.
- Do not say the cyber lane is equivalent to fully adjudicated national ground truth.
- Do not say fraud results validate cyber.
- Do not say the baseline is the model.
- Do not say the platform is fully ground-truth supervised.

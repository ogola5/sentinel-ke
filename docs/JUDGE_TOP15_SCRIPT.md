# Final Judge Script

Last updated: 2026-03-26

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
- latest benchmarked run window: `2026-03-24T19:04:48.663643+00:00`
- latest run size: `97` nodes, `237` edges
- latest live prediction window matches the benchmarked run window
- `prediction_count: 97`
- `high_risk_count: 37`
- operating `f1: 0.941176`
- operating `precision: 1.0`
- operating `recall: 0.888889`
- holdout `auc: 0.0`
- baselines are present with `coverage_count: 2143`
- thresholds are present

Say this:

"The cyber lane is ready and internally aligned. The judge-safe point is that the live predictions, thresholds, baselines, and run window now match, and the operating point is strong. We do not overclaim the ranking AUC because the current holdout still has thin negative support."

If asked about the caveat, say:

"There is a newer live prediction window in the background, but the judge view is anchored to the latest benchmarked run for like-for-like comparison. That keeps the presentation honest."

## Corruption Lane

What the live API shows:

- `status: ok`
- latest run anchored to `Wcorruption`
- latest run size: `2026` nodes, `3900` edges
- `AUC: 0.9135`
- `precision: 0.971888`
- `recall: 0.726727`
- `f1: 0.831615`
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

"Sentinel-KE is judge-ready because it exposes live readiness, separate baseline evidence, live thresholds, and clear caveats without collapsing the lanes into one mixed claim."

## Do Not Say

- Do not say the corruption lane is legal proof.
- Do not say the cyber lane proves every alert is correct.
- Do not say the cyber AUC is strong on the current live holdout.
- Do not say fraud results validate cyber.
- Do not say the baseline is the model.
- Do not say the platform is fully ground-truth supervised.

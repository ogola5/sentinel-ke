# Top-15 Baseline Story

Last updated: 2026-03-26

This is the plain-language version of the baseline story judges need to hear:

- the model is not the baseline
- the baseline is not the model
- each lane is evaluated separately
- no lane gets to borrow another lane's result

## Model Versus Baseline

### The model

The model side is the trained SentinelGNN or, when the artifact is missing or invalid, the deterministic heuristic fallback.

Repo facts that support that:

- `backend/app/analytics/layer3/ai_inference_worker.py` says the preferred path loads the latest trained `GNNTrainingRun.artifact_path`.
- The same file says the fallback path is deterministic and sets `decision_source = "heuristic"`.
- `backend/app/analytics/ai_models.py` stores `AIPrediction.decision_source` so the two paths can be distinguished after the fact.
- `backend/app/analytics/ai_models.py` stores training-run metadata such as `auc`, `precision`, `recall`, `f1`, and `artifact_path`.

### The baseline

The baseline side is a rolling statistical reference computed from prior `AIPrediction` rows.

Repo facts that support that:

- `backend/app/analytics/layer3/baseline_worker.py` pulls recent `AIPrediction` rows by `prediction_type` and `window_key`.
- It computes `baseline_score` as the mean of the prior scores.
- It computes `baseline_std` from the same score series.
- `backend/app/api/ai.py` exposes the result at `GET /v1/ai/baselines`.
- The API returns `baseline_score`, `baseline_std`, `sample_count`, and `last_window_end`.

### What judges should compare

Compare the model score against the baseline score. Do not present the baseline as a second model.

The clean distinction is:

- model: "What did the trained GNN or heuristic say for this entity?"
- baseline: "What does this entity usually look like in recent windows?"

That is the point of the baseline API. It is a reference frame, not a competitor model.

## Lane-Separated Claims

| Lane | Judge-safe claim | What it is not |
|---|---|---|
| Cyber | Strong thresholded operating metrics on a real Kenyan cyber event graph, with a temporal holdout and a small observed graph of `97` nodes / `237` edges. | It is not a strong ranking-AUC claim on the current live holdout, and it is not fraud performance or corruption proof. |
| Fraud | PaySim is the fraud benchmark lane; the repo keeps it separate and requires a fresh artifact before quoting a judge-safe AUC. | It is not cyber performance and not corruption proof. |
| Corruption | The corruption lane is a risk-ranking and graph-visualization lane over PPRA, Kenya Law, and EACC sources, with live holdout AUC `0.9135` and fairness passed on the active window. | It is not legal adjudication and not fully adjudicated national ground truth. |

## Why The Separation Matters

`docs/THREE_LANE_AI_STORY.md` already states that cross-lane correlation is a separate inference step and does not inherit the AUC of any standalone model. That is the correct judge framing.

The platform should therefore say:

- cyber has its own model and its own benchmark
- fraud has its own model and its own benchmark
- corruption has its own model status and its own governance limits

## Safe Wording

Use:

- "Sentinel-KE evaluates separate AI lanes."
- "The cyber lane has strong live operating metrics, but its current holdout AUC is scientifically weak because the holdout is class-thin."
- "The fraud lane is benchmarked separately and requires a fresh artifact before quoting its AUC."
- "The fraud lane uses PaySim as its benchmark corpus."
- "The corruption lane currently provides strong risk ranking, not legal proof."
- "The baseline is a rolling statistical reference."

Avoid:

- "One model proves the whole platform."
- "PaySim validates cyber or corruption."
- "The baseline is the model."
- "Corruption scores are final findings."
- "AUC alone proves production readiness."

## Judge Close

If you need one sentence, use this:

"Sentinel-KE has separate benchmark stories for cyber, fraud, and corruption; the baseline is a reference layer, not the model, and the repo keeps the claims separated by lane."

For the live presentation order, use `docs/JUDGE_TOP15_SCRIPT.md` first, then this baseline story to answer follow-up questions.

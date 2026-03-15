# Forecasting Method

Sentinel-KE forecasts the **daily average `risk_gnn` score**, not the guaranteed occurrence or exact timing of a specific future attack.

## What It Does

- Builds a daily history of average cyber-risk scores from `ai_prediction`
- Compares several small-sample statistical models with rolling-origin backtesting
- Selects the best model, or averages a few near-best models when the errors are close
- Produces 80% and 95% forecast intervals
- Returns a near-term dashboard forecast and a fuller analyst-facing forecast payload

## Candidate Models

- Mean level
- Naive last value
- Drift
- Simple exponential smoothing
- Holt linear trend
- Damped Holt trend
- Seasonal naive when there is enough weekly history
- Additive Holt-Winters with damped trend when there is enough weekly history

## Why This Is Better For MVP Data

With short or irregular histories, simple statistical models are usually more stable than deep forecasting models. Sentinel-KE therefore uses:

- **rolling-origin cross-validation** instead of choosing a model by intuition
- **damped trends** to reduce runaway extrapolation
- **small ensembles** only when several models perform similarly
- **intervals derived from backtest errors** when enough folds are available

## Scientific Caveat

This forecast is an extrapolation of a learned cyber-risk signal. It is useful for:

- operational posture
- monitoring intensity
- pre-positioning responders
- explaining whether the risk picture is rising, stable, or falling

It should **not** be described as deterministic proof that a specific attack will occur on a specific day.

from __future__ import annotations

from datetime import date, datetime, timezone, timedelta
from typing import Dict, List, Sequence


def _clamp_score(value: float) -> float:
    return min(100.0, max(0.0, float(value)))


def _mean_abs(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    return sum(abs(float(v)) for v in values) / max(1, len(values))


def _initial_seasonals(scores: Sequence[float], season_length: int) -> List[float]:
    season_averages: List[float] = []
    for start in range(0, len(scores), season_length):
        chunk = list(scores[start:start + season_length])
        if len(chunk) < season_length:
            break
        season_averages.append(sum(chunk) / float(season_length))

    if not season_averages:
        return [0.0 for _ in range(season_length)]

    seasonals = [0.0 for _ in range(season_length)]
    full_cycles = min(len(season_averages), len(scores) // season_length)
    for i in range(season_length):
        vals: List[float] = []
        for cycle in range(full_cycles):
            idx = cycle * season_length + i
            if idx < len(scores):
                vals.append(float(scores[idx]) - float(season_averages[cycle]))
        seasonals[i] = sum(vals) / max(1, len(vals))
    return seasonals


def build_risk_forecast(
    *,
    history: Sequence[Dict[str, object]],
    horizon: int,
    alpha: float,
    beta: float,
    gamma: float = 0.2,
    season_length: int = 7,
) -> Dict[str, object]:
    if len(history) < 3:
        return {
            "status": "insufficient_data",
            "message": f"Need at least 3 daily GNN data points, got {len(history)}.",
            "history": [],
            "forecast": [],
        }

    scores = [_clamp_score(float(row.get("avg_score") or 0.0)) for row in history]
    dates = [row.get("date") for row in history]

    seasonal_mode = len(scores) >= (season_length * 2)
    residuals: List[float] = []
    smoothed: List[float] = []

    if seasonal_mode:
        seasonals = _initial_seasonals(scores, season_length)
        level = scores[0] - seasonals[0]
        trend = ((scores[season_length] - seasonals[0]) - level) / float(season_length)
        for i, score in enumerate(scores):
            season_idx = i % season_length
            if i == 0:
                fitted = level + seasonals[season_idx]
                smoothed.append(round(_clamp_score(fitted), 2))
                continue
            prev_level = level
            prev_season = seasonals[season_idx]
            level = alpha * (score - prev_season) + (1.0 - alpha) * (prev_level + trend)
            trend = beta * (level - prev_level) + (1.0 - beta) * trend
            seasonals[season_idx] = gamma * (score - level) + (1.0 - gamma) * prev_season
            fitted = level + trend + seasonals[season_idx]
            smoothed.append(round(_clamp_score(fitted), 2))
            residuals.append(score - fitted)

        forecast_points: List[Dict[str, object]] = []
        last_date = dates[-1]
        if isinstance(last_date, str):
            last_date_obj = date.fromisoformat(last_date)
        elif isinstance(last_date, date):
            last_date_obj = last_date
        else:
            last_date_obj = datetime.now(timezone.utc).date()
        sigma = _mean_abs(residuals) * 1.28
        for step in range(1, horizon + 1):
            season_idx = (len(scores) + step - 1) % season_length
            point = _clamp_score(level + step * trend + seasonals[season_idx])
            margin = sigma * (step ** 0.5)
            forecast_points.append(
                {
                    "date": str(last_date_obj + timedelta(days=step)),
                    "forecast_score": round(point, 2),
                    "upper_80": round(_clamp_score(point + margin), 2),
                    "lower_80": round(_clamp_score(point - margin), 2),
                    "horizon_day": step,
                }
            )
        model_name = "holt_winters_additive"
    else:
        level = scores[0]
        trend = scores[1] - scores[0]
        smoothed = [round(level, 2)]
        for i in range(1, len(scores)):
            prev_level = level
            level = alpha * scores[i] + (1.0 - alpha) * (prev_level + trend)
            trend = beta * (level - prev_level) + (1.0 - beta) * trend
            fitted = level
            smoothed.append(round(_clamp_score(fitted), 2))
            residuals.append(scores[i] - fitted)

        forecast_points = []
        last_date = dates[-1]
        if isinstance(last_date, str):
            last_date_obj = date.fromisoformat(last_date)
        elif isinstance(last_date, date):
            last_date_obj = last_date
        else:
            last_date_obj = datetime.now(timezone.utc).date()
        sigma = _mean_abs(residuals) * 1.28
        for step in range(1, horizon + 1):
            point = _clamp_score(level + step * trend)
            margin = sigma * (step ** 0.5)
            forecast_points.append(
                {
                    "date": str(last_date_obj + timedelta(days=step)),
                    "forecast_score": round(point, 2),
                    "upper_80": round(_clamp_score(point + margin), 2),
                    "lower_80": round(_clamp_score(point - margin), 2),
                    "horizon_day": step,
                }
            )
        model_name = "holt_linear_double_exponential"

    peak_forecast = max(p["forecast_score"] for p in forecast_points)
    net_change = forecast_points[-1]["forecast_score"] - scores[-1]
    if net_change > 3.0:
        trend_direction = "rising"
    elif net_change < -3.0:
        trend_direction = "falling"
    else:
        trend_direction = "stable"

    if peak_forecast >= 85:
        alert_level = "CRITICAL"
        alert_msg = "Forecast peak risk >=85. Recommend activating national incident response."
    elif peak_forecast >= 70:
        alert_level = "HIGH"
        alert_msg = "Forecast peak risk >=70. Recommend heightened monitoring and pre-positioning of response teams."
    elif peak_forecast >= 55:
        alert_level = "ELEVATED"
        alert_msg = "Forecast risk elevated. Continue active monitoring."
    else:
        alert_level = "NORMAL"
        alert_msg = "Forecast risk within normal range."

    out_history = []
    for i, row in enumerate(history):
        item = dict(row)
        item["smoothed_score"] = smoothed[i]
        out_history.append(item)

    methodology = (
        "Seasonal additive Holt-Winters on daily GNN avg_score with 80% confidence bands."
        if seasonal_mode
        else "Holt linear double-exponential smoothing on daily GNN avg_score with 80% confidence bands."
    )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "history_days": len(history),
        "horizon_days": horizon,
        "alpha": alpha,
        "beta": beta,
        "gamma": gamma if seasonal_mode else None,
        "season_length": season_length if seasonal_mode else None,
        "model": model_name,
        "history": out_history,
        "forecast": forecast_points,
        "trend_direction": trend_direction,
        "net_change_forecast": round(float(net_change), 2),
        "volatility": round(float(_mean_abs(residuals)), 2),
        "alert_recommendation": {
            "level": alert_level,
            "message": alert_msg,
            "peak_forecast_score": round(float(peak_forecast), 2),
        },
        "methodology_note": (
            methodology
            + " This is statistical extrapolation of learned risk signals, not a causal prediction of a specific attack."
        ),
    }

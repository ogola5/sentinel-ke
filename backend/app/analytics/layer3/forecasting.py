from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from math import sqrt
from typing import Any, Callable, Dict, List, Sequence


def _clamp_score(value: float) -> float:
    return min(100.0, max(0.0, float(value)))


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_date(value: object) -> date:
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value:
        return date.fromisoformat(value)
    return datetime.now(timezone.utc).date()


def _to_datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=timezone.utc)
    if isinstance(value, str) and value:
        try:
            if len(value) == 10:
                return datetime.combine(date.fromisoformat(value), datetime.min.time(), tzinfo=timezone.utc)
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def _mean(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    return sum(float(v) for v in values) / float(len(values))


def _median(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(v) for v in values)
    mid = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def _mean_abs(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    return sum(abs(float(v)) for v in values) / float(len(values))


def _quantile(values: Sequence[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(v) for v in values)
    if len(ordered) == 1:
        return ordered[0]
    q = min(1.0, max(0.0, float(q)))
    pos = (len(ordered) - 1) * q
    low = int(pos)
    high = min(len(ordered) - 1, low + 1)
    if low == high:
        return ordered[low]
    weight = pos - low
    return ordered[low] * (1.0 - weight) + ordered[high] * weight


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


def _damped_multiplier(phi: float, step: int) -> float:
    if step <= 0:
        return 0.0
    if abs(phi - 1.0) < 1e-9:
        return float(step)
    return phi * (1.0 - (phi ** step)) / (1.0 - phi)


def _mad_sigma(errors: Sequence[float]) -> float:
    if not errors:
        return 2.0
    median = _median(errors)
    deviations = [abs(float(err) - median) for err in errors]
    sigma = 1.4826 * _median(deviations)
    if sigma <= 0.0:
        sigma = max(0.5, _mean_abs(errors) * 1.25)
    return sigma


@dataclass
class ForecastModelResult:
    name: str
    fitted: List[float]
    forecast: List[float]
    warmup: int


ModelBuilder = Callable[[Sequence[float], int, float, float, float, int, float], ForecastModelResult | None]


def _fit_mean_level(
    scores: Sequence[float],
    horizon: int,
    alpha: float,
    beta: float,
    gamma: float,
    season_length: int,
    phi: float,
) -> ForecastModelResult:
    fitted = [_clamp_score(scores[0])]
    for i in range(1, len(scores)):
        fitted.append(_clamp_score(_mean(scores[:i])))
    level = _clamp_score(_mean(scores))
    return ForecastModelResult(
        name="mean_level",
        fitted=fitted,
        forecast=[level for _ in range(horizon)],
        warmup=1,
    )


def _fit_naive_last(
    scores: Sequence[float],
    horizon: int,
    alpha: float,
    beta: float,
    gamma: float,
    season_length: int,
    phi: float,
) -> ForecastModelResult:
    fitted = [_clamp_score(scores[0])]
    for i in range(1, len(scores)):
        fitted.append(_clamp_score(scores[i - 1]))
    level = _clamp_score(scores[-1])
    return ForecastModelResult(
        name="naive_last",
        fitted=fitted,
        forecast=[level for _ in range(horizon)],
        warmup=1,
    )


def _fit_drift(
    scores: Sequence[float],
    horizon: int,
    alpha: float,
    beta: float,
    gamma: float,
    season_length: int,
    phi: float,
) -> ForecastModelResult | None:
    if len(scores) < 2:
        return None
    fitted = [_clamp_score(scores[0])]
    for i in range(1, len(scores)):
        if i == 1:
            fitted.append(_clamp_score(scores[0]))
            continue
        slope = (float(scores[i - 1]) - float(scores[0])) / float(i - 1)
        fitted.append(_clamp_score(float(scores[i - 1]) + slope))
    last = float(scores[-1])
    slope = (last - float(scores[0])) / float(max(1, len(scores) - 1))
    forecast = [_clamp_score(last + slope * step) for step in range(1, horizon + 1)]
    return ForecastModelResult(
        name="drift",
        fitted=fitted,
        forecast=forecast,
        warmup=2,
    )


def _fit_ses(
    scores: Sequence[float],
    horizon: int,
    alpha: float,
    beta: float,
    gamma: float,
    season_length: int,
    phi: float,
) -> ForecastModelResult:
    level = float(scores[0])
    fitted = [_clamp_score(level)]
    for i in range(1, len(scores)):
        fitted.append(_clamp_score(level))
        level = alpha * float(scores[i]) + (1.0 - alpha) * level
    point = _clamp_score(level)
    return ForecastModelResult(
        name="ses",
        fitted=fitted,
        forecast=[point for _ in range(horizon)],
        warmup=1,
    )


def _fit_holt_linear(
    scores: Sequence[float],
    horizon: int,
    alpha: float,
    beta: float,
    gamma: float,
    season_length: int,
    phi: float,
) -> ForecastModelResult | None:
    if len(scores) < 2:
        return None
    level = float(scores[0])
    trend = float(scores[1]) - float(scores[0])
    fitted = [_clamp_score(level)]
    for i in range(1, len(scores)):
        fitted.append(_clamp_score(level + trend))
        prev_level = level
        level = alpha * float(scores[i]) + (1.0 - alpha) * (level + trend)
        trend = beta * (level - prev_level) + (1.0 - beta) * trend
    forecast = [_clamp_score(level + step * trend) for step in range(1, horizon + 1)]
    return ForecastModelResult(
        name="holt_linear",
        fitted=fitted,
        forecast=forecast,
        warmup=2,
    )


def _fit_holt_damped(
    scores: Sequence[float],
    horizon: int,
    alpha: float,
    beta: float,
    gamma: float,
    season_length: int,
    phi: float,
) -> ForecastModelResult | None:
    if len(scores) < 2:
        return None
    level = float(scores[0])
    trend = float(scores[1]) - float(scores[0])
    fitted = [_clamp_score(level)]
    for i in range(1, len(scores)):
        fitted.append(_clamp_score(level + phi * trend))
        prev_level = level
        prev_trend = trend
        level = alpha * float(scores[i]) + (1.0 - alpha) * (level + phi * trend)
        trend = beta * (level - prev_level) + (1.0 - beta) * phi * prev_trend
    forecast = [
        _clamp_score(level + _damped_multiplier(phi, step) * trend)
        for step in range(1, horizon + 1)
    ]
    return ForecastModelResult(
        name="holt_damped",
        fitted=fitted,
        forecast=forecast,
        warmup=2,
    )


def _fit_seasonal_naive(
    scores: Sequence[float],
    horizon: int,
    alpha: float,
    beta: float,
    gamma: float,
    season_length: int,
    phi: float,
) -> ForecastModelResult | None:
    if len(scores) < season_length * 2:
        return None
    fitted = []
    for i in range(len(scores)):
        if i < season_length:
            fitted.append(_clamp_score(scores[i]))
        else:
            fitted.append(_clamp_score(scores[i - season_length]))
    forecast = []
    recent_cycle = list(scores[-season_length:])
    for step in range(1, horizon + 1):
        forecast.append(_clamp_score(recent_cycle[(step - 1) % season_length]))
    return ForecastModelResult(
        name="seasonal_naive",
        fitted=fitted,
        forecast=forecast,
        warmup=season_length,
    )


def _fit_holt_winters_additive_damped(
    scores: Sequence[float],
    horizon: int,
    alpha: float,
    beta: float,
    gamma: float,
    season_length: int,
    phi: float,
) -> ForecastModelResult | None:
    if len(scores) < season_length * 2:
        return None
    seasonals = _initial_seasonals(scores, season_length)
    level = float(scores[0]) - seasonals[0]
    trend = (
        (float(scores[season_length]) - seasonals[0]) - level
    ) / float(season_length)
    fitted = [_clamp_score(level + seasonals[0])]
    for i in range(1, len(scores)):
        season_idx = i % season_length
        prev_level = level
        prev_trend = trend
        prev_season = seasonals[season_idx]
        fitted.append(_clamp_score(prev_level + phi * prev_trend + prev_season))
        level = alpha * (float(scores[i]) - prev_season) + (1.0 - alpha) * (prev_level + phi * prev_trend)
        trend = beta * (level - prev_level) + (1.0 - beta) * phi * prev_trend
        seasonals[season_idx] = gamma * (float(scores[i]) - level) + (1.0 - gamma) * prev_season
    forecast = []
    for step in range(1, horizon + 1):
        season_idx = (len(scores) + step - 1) % season_length
        point = level + _damped_multiplier(phi, step) * trend + seasonals[season_idx]
        forecast.append(_clamp_score(point))
    return ForecastModelResult(
        name="holt_winters_additive_damped",
        fitted=fitted,
        forecast=forecast,
        warmup=max(2, season_length),
    )


MODEL_BUILDERS: tuple[ModelBuilder, ...] = (
    _fit_mean_level,
    _fit_naive_last,
    _fit_drift,
    _fit_ses,
    _fit_holt_linear,
    _fit_holt_damped,
    _fit_seasonal_naive,
    _fit_holt_winters_additive_damped,
)


def _fit_candidate_models(
    scores: Sequence[float],
    horizon: int,
    alpha: float,
    beta: float,
    gamma: float,
    season_length: int,
    phi: float,
) -> dict[str, ForecastModelResult]:
    out: dict[str, ForecastModelResult] = {}
    for builder in MODEL_BUILDERS:
        result = builder(scores, horizon, alpha, beta, gamma, season_length, phi)
        if result is not None:
            out[result.name] = result
    return out


def _rolling_origin_backtest(
    scores: Sequence[float],
    eval_horizon: int,
    alpha: float,
    beta: float,
    gamma: float,
    season_length: int,
    phi: float,
) -> dict[str, dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}
    min_train_size = 3
    for origin in range(min_train_size, len(scores)):
        train = list(scores[:origin])
        max_h = min(eval_horizon, len(scores) - origin)
        models = _fit_candidate_models(train, max_h, alpha, beta, gamma, season_length, phi)
        if not models:
            continue
        for name, model in models.items():
            record = results.setdefault(
                name,
                {
                    "abs_errors": [],
                    "sq_errors": [],
                    "signed_errors_by_horizon": {step: [] for step in range(1, eval_horizon + 1)},
                    "origins": 0,
                    "predictions": 0,
                },
            )
            record["origins"] += 1
            for step in range(1, max_h + 1):
                actual = float(scores[origin + step - 1])
                predicted = float(model.forecast[step - 1])
                error = actual - predicted
                record["abs_errors"].append(abs(error))
                record["sq_errors"].append(error * error)
                record["signed_errors_by_horizon"][step].append(error)
                record["predictions"] += 1
    return results


def _select_models(cv_results: dict[str, dict[str, Any]]) -> tuple[List[str], List[dict[str, Any]]]:
    candidates: List[dict[str, Any]] = []
    for name, stats in cv_results.items():
        preds = int(stats.get("predictions") or 0)
        if preds <= 0:
            continue
        abs_errors = list(stats.get("abs_errors") or [])
        sq_errors = list(stats.get("sq_errors") or [])
        mae = _mean(abs_errors)
        rmse = sqrt(_mean(sq_errors)) if sq_errors else 0.0
        candidates.append(
            {
                "name": name,
                "cv_mae": round(mae, 4),
                "cv_rmse": round(rmse, 4),
                "origins": int(stats.get("origins") or 0),
                "predictions": preds,
            }
        )
    if not candidates:
        return ["naive_last"], []

    candidates.sort(key=lambda item: (item["cv_mae"], item["cv_rmse"], item["name"]))
    best_mae = float(candidates[0]["cv_mae"])
    tolerance = max(0.5, best_mae * 0.08)
    selected = [
        item["name"]
        for item in candidates
        if float(item["cv_mae"]) <= best_mae + tolerance
    ][:3]
    return selected or [candidates[0]["name"]], candidates


def _combine_model_outputs(
    models: Sequence[ForecastModelResult],
    history_len: int,
    horizon: int,
) -> tuple[List[float], List[float]]:
    fitted: List[float] = []
    for idx in range(history_len):
        vals = [float(model.fitted[idx]) for model in models if idx < len(model.fitted)]
        fitted.append(_clamp_score(_mean(vals)))
    forecast: List[float] = []
    for step in range(horizon):
        vals = [float(model.forecast[step]) for model in models if step < len(model.forecast)]
        forecast.append(_clamp_score(_mean(vals)))
    return fitted, forecast


def _ensemble_backtest_errors(
    scores: Sequence[float],
    selected_model_names: Sequence[str],
    eval_horizon: int,
    alpha: float,
    beta: float,
    gamma: float,
    season_length: int,
    phi: float,
) -> dict[int, List[float]]:
    errors: dict[int, List[float]] = {step: [] for step in range(1, eval_horizon + 1)}
    for origin in range(3, len(scores)):
        train = list(scores[:origin])
        max_h = min(eval_horizon, len(scores) - origin)
        models = _fit_candidate_models(train, max_h, alpha, beta, gamma, season_length, phi)
        selected = [models[name] for name in selected_model_names if name in models]
        if not selected:
            continue
        _, combined = _combine_model_outputs(selected, history_len=len(train), horizon=max_h)
        for step in range(1, max_h + 1):
            actual = float(scores[origin + step - 1])
            predicted = float(combined[step - 1])
            errors[step].append(actual - predicted)
    return errors


def _build_confidence_bands(
    forecast_values: Sequence[float],
    lead_errors: dict[int, List[float]],
) -> tuple[List[dict[str, float]], str]:
    flattened = [float(err) for errs in lead_errors.values() for err in errs]
    fallback_sigma = _mad_sigma(flattened)
    out: List[dict[str, float]] = []
    empirical_available = len(flattened) >= 8
    for step, value in enumerate(forecast_values, start=1):
        errors = list(lead_errors.get(step) or flattened)
        if len(errors) >= 8:
            lower_80 = _clamp_score(value + _quantile(errors, 0.10))
            upper_80 = _clamp_score(value + _quantile(errors, 0.90))
            lower_95 = _clamp_score(value + _quantile(errors, 0.025))
            upper_95 = _clamp_score(value + _quantile(errors, 0.975))
        else:
            sigma = fallback_sigma * sqrt(step)
            lower_80 = _clamp_score(value - 1.2816 * sigma)
            upper_80 = _clamp_score(value + 1.2816 * sigma)
            lower_95 = _clamp_score(value - 1.96 * sigma)
            upper_95 = _clamp_score(value + 1.96 * sigma)
        out.append(
            {
                "upper_80": round(upper_80, 2),
                "lower_80": round(lower_80, 2),
                "upper_95": round(upper_95, 2),
                "lower_95": round(lower_95, 2),
            }
        )
    method = "empirical_rolling_origin_quantiles" if empirical_available else "mad_normal_approximation"
    return out, method


def _confidence_score(history_len: int, candidate_models: Sequence[dict[str, Any]], interval_bands: Sequence[dict[str, float]]) -> float:
    base = 0.35
    base += min(0.2, history_len / 30.0 * 0.2)
    best = candidate_models[0] if candidate_models else {"predictions": 0, "cv_mae": 20.0}
    preds = float(best.get("predictions") or 0.0)
    mae = float(best.get("cv_mae") or 20.0)
    base += min(0.2, preds / 20.0 * 0.2)
    base += max(0.0, 0.2 - min(0.2, mae / 50.0))
    if interval_bands:
        widths = [float(band["upper_80"]) - float(band["lower_80"]) for band in interval_bands]
        avg_width = _mean(widths)
        base -= min(0.15, avg_width / 100.0 * 0.15)
    return min(0.95, max(0.15, base))


def _confidence_grade(confidence: float) -> str:
    if confidence >= 0.75:
        return "high"
    if confidence >= 0.55:
        return "medium"
    return "low"


def summarize_forecast_card(forecast: Dict[str, object], *, target_day: int = 3) -> Dict[str, object]:
    if forecast.get("status") == "insufficient_data":
        return {
            "trend": "stable",
            "forecast_score": None,
            "confidence": 0.0,
            "confidence_grade": "low",
            "methodology_note": forecast.get("message") or "Forecast unavailable.",
        }
    points = list(forecast.get("forecast") or [])
    if not points:
        return {
            "trend": "stable",
            "forecast_score": None,
            "confidence": 0.0,
            "confidence_grade": "low",
            "methodology_note": "Forecast unavailable.",
        }
    idx = min(max(1, target_day) - 1, len(points) - 1)
    point = points[idx]
    confidence = float(forecast.get("forecast_confidence") or 0.0)
    return {
        "trend": forecast.get("trend_direction") or "stable",
        "forecast_score": round(_safe_float(point.get("forecast_score")), 1),
        "confidence": round(confidence, 2),
        "confidence_grade": forecast.get("confidence_grade") or _confidence_grade(confidence),
        "methodology_note": forecast.get("methodology_note") or "",
    }


def build_signal_forecast(
    *,
    history: Sequence[Dict[str, object]],
    horizon: int,
    alpha: float,
    beta: float,
    gamma: float = 0.2,
    season_length: int | None = None,
    phi: float = 0.9,
    granularity: str = "day",
    time_field: str | None = None,
    value_field: str = "avg_score",
    signal_name: str = "cyber-risk signal",
) -> Dict[str, object]:
    unit = "day" if granularity != "hour" else "hour"
    time_key = time_field or ("date" if unit == "day" else "timestamp")
    seasonal_period = season_length if season_length is not None else (7 if unit == "day" else 24)

    if len(history) < 3:
        return {
            "status": "insufficient_data",
            "message": f"Need at least 3 {unit}ly signal points, got {len(history)}.",
            "history": [],
            "forecast": [],
        }

    if unit == "hour":
        times = [_to_datetime(row.get(time_key) or row.get("timestamp") or row.get("date")) for row in history]
    else:
        times = [_to_date(row.get(time_key) or row.get("date")) for row in history]
    scores = [_clamp_score(_safe_float(row.get(value_field))) for row in history]
    eval_horizon = min(max(1, horizon), 3)

    cv_results = _rolling_origin_backtest(
        scores=scores,
        eval_horizon=eval_horizon,
        alpha=alpha,
        beta=beta,
        gamma=gamma,
        season_length=seasonal_period,
        phi=phi,
    )
    selected_model_names, candidate_models = _select_models(cv_results)
    full_models = _fit_candidate_models(
        scores=scores,
        horizon=horizon,
        alpha=alpha,
        beta=beta,
        gamma=gamma,
        season_length=seasonal_period,
        phi=phi,
    )
    selected_models = [full_models[name] for name in selected_model_names if name in full_models]
    if not selected_models:
        selected_models = [full_models[name] for name in full_models][:1]
        selected_model_names = [selected_models[0].name] if selected_models else ["naive_last"]

    fitted, forecast_values = _combine_model_outputs(selected_models, history_len=len(history), horizon=horizon)
    lead_errors = _ensemble_backtest_errors(
        scores=scores,
        selected_model_names=selected_model_names,
        eval_horizon=eval_horizon,
        alpha=alpha,
        beta=beta,
        gamma=gamma,
        season_length=seasonal_period,
        phi=phi,
    )
    interval_bands, interval_method = _build_confidence_bands(forecast_values, lead_errors)
    model_label = selected_model_names[0] if len(selected_model_names) == 1 else "ensemble_average"

    out_history: List[Dict[str, object]] = []
    residuals: List[float] = []
    for idx, row in enumerate(history):
        smoothed = round(float(fitted[idx]), 2)
        item = dict(row)
        item["smoothed_score"] = smoothed
        out_history.append(item)
        if idx >= 1:
            residuals.append(float(scores[idx]) - float(fitted[idx]))

    forecast_points: List[Dict[str, object]] = []
    last_time = times[-1]
    for step in range(1, horizon + 1):
        bands = interval_bands[step - 1]
        next_time = (
            last_time + timedelta(hours=step)
            if unit == "hour"
            else last_time + timedelta(days=step)
        )
        forecast_points.append(
            {
                time_key: next_time.isoformat() if unit == "hour" else str(next_time),
                "forecast_score": round(float(forecast_values[step - 1]), 2),
                **bands,
                f"horizon_{unit}": step,
            }
        )

    peak_forecast = max(float(point["forecast_score"]) for point in forecast_points)
    net_change = float(forecast_points[-1]["forecast_score"]) - float(scores[-1])
    if net_change > 3.0:
        trend_direction = "rising"
    elif net_change < -3.0:
        trend_direction = "falling"
    else:
        trend_direction = "stable"

    if peak_forecast >= 85:
        alert_level = "CRITICAL"
        alert_msg = f"Forecast peak risk >=85. Recommend activating response for the monitored {signal_name}."
    elif peak_forecast >= 70:
        alert_level = "HIGH"
        alert_msg = f"Forecast peak risk >=70. Recommend heightened monitoring for the monitored {signal_name}."
    elif peak_forecast >= 55:
        alert_level = "ELEVATED"
        alert_msg = f"Forecast risk is elevated for the monitored {signal_name}. Continue active monitoring."
    else:
        alert_level = "NORMAL"
        alert_msg = f"Forecast risk is within normal range for the monitored {signal_name}."

    confidence = _confidence_score(len(history), candidate_models, interval_bands)
    confidence_grade = _confidence_grade(confidence)

    methodology = (
        "Rolling-origin cross-validation compares mean level, naive, drift, simple exponential smoothing, "
        "Holt linear, damped Holt, and seasonal candidates where repeated structure is supported; "
        "the best model or a small average of near-best models is then used for the final forecast."
    )

    out: Dict[str, object] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "ok",
        f"history_{unit}s": len(history),
        f"horizon_{unit}s": horizon,
        "alpha": alpha,
        "beta": beta,
        "gamma": gamma,
        "phi": phi,
        "season_length": seasonal_period,
        "model": model_label,
        "selected_models": selected_model_names,
        "candidate_models": candidate_models,
        "cross_validation": {
            "method": "rolling_origin",
            f"evaluation_horizon_{unit}s": eval_horizon,
            "candidate_count": len(candidate_models),
            "folds": max((int(item.get("origins") or 0) for item in candidate_models), default=0),
        },
        "history": out_history,
        "forecast": forecast_points,
        "trend_direction": trend_direction,
        "net_change_forecast": round(float(net_change), 2),
        "volatility": round(float(_mean_abs(residuals)), 2),
        "forecast_confidence": round(confidence, 2),
        "confidence_grade": confidence_grade,
        "interval_method": interval_method,
        "alert_recommendation": {
            "level": alert_level,
            "message": alert_msg,
            "peak_forecast_score": round(float(peak_forecast), 2),
        },
        "methodology_note": (
            methodology
            + f" This forecasts the learned {unit}ly {signal_name}, not the guaranteed occurrence or exact timing of a specific attack."
        ),
    }
    return out


def build_risk_forecast(
    *,
    history: Sequence[Dict[str, object]],
    horizon: int,
    alpha: float,
    beta: float,
    gamma: float = 0.2,
    season_length: int = 7,
    phi: float = 0.9,
) -> Dict[str, object]:
    return build_signal_forecast(
        history=history,
        horizon=horizon,
        alpha=alpha,
        beta=beta,
        gamma=gamma,
        season_length=season_length,
        phi=phi,
        granularity="day",
        time_field="date",
        value_field="avg_score",
        signal_name="cyber-risk signal",
    )

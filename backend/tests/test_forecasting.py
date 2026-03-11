from app.analytics.layer3.forecasting import build_risk_forecast


def test_build_risk_forecast_returns_seasonal_model_when_history_is_long_enough():
    history = []
    for i in range(14):
        history.append(
            {
                "date": f"2026-03-{i + 1:02d}",
                "avg_score": 40.0 + (i % 7) * 3.0,
                "max_score": 50.0 + (i % 7) * 3.0,
                "n": 25,
            }
        )

    out = build_risk_forecast(history=history, horizon=5, alpha=0.3, beta=0.1)

    assert out["model"] == "holt_winters_additive"
    assert len(out["forecast"]) == 5
    assert out["season_length"] == 7


def test_build_risk_forecast_falls_back_to_linear_model_for_short_history():
    history = [
        {"date": "2026-03-01", "avg_score": 45.0, "max_score": 52.0, "n": 12},
        {"date": "2026-03-02", "avg_score": 49.0, "max_score": 54.0, "n": 11},
        {"date": "2026-03-03", "avg_score": 53.0, "max_score": 58.0, "n": 13},
    ]

    out = build_risk_forecast(history=history, horizon=3, alpha=0.3, beta=0.1)

    assert out["model"] == "holt_linear_double_exponential"
    assert len(out["forecast"]) == 3

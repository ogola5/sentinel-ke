from app.analytics.layer3.forecasting import build_risk_forecast, build_signal_forecast, summarize_forecast_card


def test_build_risk_forecast_returns_cross_validated_output_for_short_history():
    history = [
        {"date": "2026-03-01", "avg_score": 42.0, "max_score": 49.0, "n": 12},
        {"date": "2026-03-02", "avg_score": 45.0, "max_score": 52.0, "n": 12},
        {"date": "2026-03-03", "avg_score": 48.0, "max_score": 55.0, "n": 11},
        {"date": "2026-03-04", "avg_score": 52.0, "max_score": 59.0, "n": 13},
        {"date": "2026-03-05", "avg_score": 54.0, "max_score": 60.0, "n": 14},
    ]

    out = build_risk_forecast(history=history, horizon=4, alpha=0.3, beta=0.1)

    assert out["status"] == "ok"
    assert len(out["forecast"]) == 4
    assert out["selected_models"]
    assert out["candidate_models"]
    assert out["cross_validation"]["method"] == "rolling_origin"
    assert out["forecast"][0]["upper_80"] >= out["forecast"][0]["lower_80"]
    assert out["forecast"][0]["upper_95"] >= out["forecast"][0]["lower_95"]
    assert out["confidence_grade"] in {"low", "medium", "high"}


def test_build_risk_forecast_exposes_seasonal_candidates_when_history_supports_weekly_structure():
    history = []
    for i in range(21):
        history.append(
            {
                "date": f"2026-03-{i + 1:02d}",
                "avg_score": 44.0 + (i % 7) * 2.5,
                "max_score": 50.0 + (i % 7) * 2.5,
                "n": 25,
            }
        )

    out = build_risk_forecast(history=history, horizon=5, alpha=0.3, beta=0.1)

    candidate_names = {item["name"] for item in out["candidate_models"]}
    assert "seasonal_naive" in candidate_names
    assert "holt_winters_additive_damped" in candidate_names
    assert len(out["forecast"]) == 5


def test_summarize_forecast_card_returns_near_term_score_and_confidence():
    history = []
    for i in range(14):
        history.append(
            {
                "date": f"2026-03-{i + 1:02d}",
                "avg_score": 50.0 + (i % 7),
                "max_score": 58.0 + (i % 7),
                "n": 20,
            }
        )

    forecast = build_risk_forecast(history=history, horizon=7, alpha=0.3, beta=0.1)
    card = summarize_forecast_card(forecast, target_day=3)

    assert card["forecast_score"] is not None
    assert 0.0 <= card["confidence"] <= 1.0
    assert card["trend"] in {"rising", "falling", "stable"}


def test_build_risk_forecast_reports_insufficient_data():
    out = build_risk_forecast(
        history=[
            {"date": "2026-03-01", "avg_score": 40.0},
            {"date": "2026-03-02", "avg_score": 42.0},
        ],
        horizon=3,
        alpha=0.3,
        beta=0.1,
    )

    assert out["status"] == "insufficient_data"
    assert out["forecast"] == []


def test_build_signal_forecast_supports_hourly_scenario_series():
    history = []
    for hour in range(12):
        history.append(
            {
                "timestamp": f"2026-03-18T{hour:02d}:00:00+00:00",
                "score": 25.0 + hour * 2.5,
                "event_count": 3 + hour,
            }
        )

    out = build_signal_forecast(
        history=history,
        horizon=6,
        alpha=0.3,
        beta=0.1,
        season_length=6,
        granularity="hour",
        time_field="timestamp",
        value_field="score",
        signal_name="scenario pressure signal",
    )

    assert out["status"] == "ok"
    assert out["history_hours"] == 12
    assert out["horizon_hours"] == 6
    assert len(out["forecast"]) == 6
    assert "timestamp" in out["forecast"][0]
    assert out["forecast"][0]["horizon_hour"] == 1

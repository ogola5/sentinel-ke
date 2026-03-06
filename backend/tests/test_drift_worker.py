from app.analytics.layer3.drift_worker import _drift_score, _status_for_fairness, _status_for_score


def test_drift_score_increases_with_distribution_shift():
    baseline = [10.0, 12.0, 11.0, 10.5]
    current = [80.0, 85.0, 79.0, 81.0]
    score, metrics = _drift_score(baseline, current)
    assert score > 0.2
    assert metrics["mean_shift"] > 0.5


def test_status_for_score_thresholds():
    assert _status_for_score(0.05) == "ok"
    assert _status_for_score(0.13) == "warning"
    assert _status_for_score(0.25) == "critical"


def test_status_for_fairness_thresholds():
    assert _status_for_fairness(None) == "ok"
    assert _status_for_fairness(0.1) == "ok"
    assert _status_for_fairness(0.31) in {"warning", "critical"}

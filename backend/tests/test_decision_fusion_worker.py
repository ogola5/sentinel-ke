from app.analytics.layer3.decision_fusion_worker import _severity


def test_severity_thresholds():
    assert _severity(95) == "critical"
    assert _severity(80) == "high"
    assert _severity(60) == "medium"
    assert _severity(20) == "low"

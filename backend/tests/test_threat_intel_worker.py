from app.analytics.layer3.threat_intel_worker import _parse_indicator


def test_parse_indicator_extracts_value_and_kind():
    row = {
        "type": "indicator",
        "id": "indicator--123",
        "pattern": "[ipv4-addr:value = '203.0.113.99']",
        "confidence": 80,
        "labels": ["malicious-activity"],
    }
    out = _parse_indicator(row)
    assert out is not None
    assert out["indicator_type"] == "ipv4-addr"
    assert out["value"] == "203.0.113.99"


def test_parse_indicator_returns_none_for_invalid_pattern():
    row = {"type": "indicator", "pattern": "[invalid pattern]"}
    assert _parse_indicator(row) is None

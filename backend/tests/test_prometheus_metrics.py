from app.core.prometheus_metrics import (
    prometheus_enabled,
    prometheus_payload,
    record_http_request,
)


def test_prometheus_payload_available_and_records_requests():
    record_http_request(method="GET", path="/health", status_code=200, duration_ms=42.0)
    payload, content_type = prometheus_payload()
    assert content_type.startswith("text/plain")
    assert isinstance(payload, (bytes, bytearray))
    if prometheus_enabled():
        assert b"sentinel_http_requests_total" in payload

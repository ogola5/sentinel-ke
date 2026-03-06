from __future__ import annotations

from typing import Tuple

try:
    from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

    _PROM_ENABLED = True
except Exception:  # noqa: BLE001
    CONTENT_TYPE_LATEST = "text/plain; version=0.0.4; charset=utf-8"
    _PROM_ENABLED = False


if _PROM_ENABLED:
    HTTP_REQUESTS_TOTAL = Counter(
        "sentinel_http_requests_total",
        "Total HTTP requests handled by Sentinel backend",
        ["method", "path", "status_code"],
    )
    HTTP_REQUEST_DURATION_MS = Histogram(
        "sentinel_http_request_duration_ms",
        "HTTP request duration in milliseconds",
        ["method", "path"],
        buckets=(5, 10, 25, 50, 100, 200, 300, 500, 750, 1000, 2000, 5000),
    )
else:
    HTTP_REQUESTS_TOTAL = None
    HTTP_REQUEST_DURATION_MS = None


def record_http_request(*, method: str, path: str, status_code: int, duration_ms: float) -> None:
    if not _PROM_ENABLED:
        return
    m = str(method or "GET").upper()
    p = str(path or "/")
    s = str(int(status_code))
    d = max(0.0, float(duration_ms))
    HTTP_REQUESTS_TOTAL.labels(method=m, path=p, status_code=s).inc()
    HTTP_REQUEST_DURATION_MS.labels(method=m, path=p).observe(d)


def prometheus_payload() -> Tuple[bytes, str]:
    if not _PROM_ENABLED:
        return b"# Prometheus client not available\n", CONTENT_TYPE_LATEST
    return generate_latest(), CONTENT_TYPE_LATEST


def prometheus_enabled() -> bool:
    return _PROM_ENABLED

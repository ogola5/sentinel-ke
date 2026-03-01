"""
Sentinel-KE — In-process request latency store.

Stores the last 1 000 request durations in a thread-safe circular deque.
Exposes p50/p95/p99 percentiles and uptime for the /v1/metrics endpoint.

No external dependencies — stdlib only.
Resets on process restart (acceptable for demo; swap for Prometheus in production).
"""
from __future__ import annotations

import collections
import threading
import time

_lock = threading.Lock()
_latencies: collections.deque[float] = collections.deque(maxlen=1_000)
_request_count: int = 0
_error_count: int = 0
_start_time: float = time.monotonic()


def record(duration_ms: float, *, is_error: bool = False) -> None:
    """Called by the timing middleware on every request completion."""
    global _request_count, _error_count
    with _lock:
        _latencies.append(duration_ms)
        _request_count += 1
        if is_error:
            _error_count += 1


def snapshot() -> dict:
    """Return current performance snapshot (safe to call from any thread)."""
    with _lock:
        data = sorted(_latencies)
        n = len(data)
        rc = _request_count
        ec = _error_count

    def pct(p: int) -> float | None:
        if not n:
            return None
        idx = min(int(n * p / 100), n - 1)
        return round(data[idx], 2)

    return {
        "uptime_seconds": round(time.monotonic() - _start_time),
        "request_count": rc,
        "error_count": ec,
        "sample_size": n,
        "latency_p50_ms": pct(50),
        "latency_p95_ms": pct(95),
        "latency_p99_ms": pct(99),
    }

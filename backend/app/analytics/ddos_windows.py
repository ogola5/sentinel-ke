# app/analytics/ddos_windows.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict


@dataclass(frozen=True)
class TimeWindow:
    start: datetime
    end: datetime

    def to_opensearch_range(self) -> Dict[str, str]:
        # OpenSearch accepts ISO8601.
        return {"gte": self.start.isoformat(), "lte": self.end.isoformat()}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def window_last_minutes(minutes: int) -> TimeWindow:
    if minutes <= 0:
        raise ValueError("minutes must be > 0")
    end = utcnow()
    start = end - timedelta(minutes=minutes)
    return TimeWindow(start=start, end=end)


def bucket_interval(bucket: str) -> str:
    """
    Allowed buckets: "30s", "1m", "2m", "5m"
    Keep this small set for MVP stability.
    """
    allowed = {"30s", "1m", "2m", "5m"}
    if bucket not in allowed:
        raise ValueError(f"bucket must be one of {sorted(allowed)}")
    return bucket

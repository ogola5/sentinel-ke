# backend/app/analytics/infra_windows.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


@dataclass(frozen=True)
class TimeWindow:
    start: datetime
    end: datetime

    def to_opensearch_range(self) -> dict:
        # OpenSearch accepts ISO strings; keep UTC
        return {
            "gte": self.start.isoformat(),
            "lte": self.end.isoformat(),
        }


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def last_minutes(minutes: int) -> TimeWindow:
    if minutes <= 0:
        raise ValueError("minutes must be > 0")
    end = utcnow()
    start = end - timedelta(minutes=minutes)
    return TimeWindow(start=start, end=end)


def between(start_iso: str, end_iso: str) -> TimeWindow:
    # strict parse without external deps
    start = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
    end = datetime.fromisoformat(end_iso.replace("Z", "+00:00"))
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    if end <= start:
        raise ValueError("end must be after start")
    return TimeWindow(start=start, end=end)

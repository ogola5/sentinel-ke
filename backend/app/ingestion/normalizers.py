from __future__ import annotations

from datetime import timezone
from typing import Any, Dict

from app.ingestion.schemas import CanonicalEvent


def normalize_event(event: CanonicalEvent) -> CanonicalEvent:
    """
    Pure normalization:
    - occurred_at -> UTC
    - ensure anchors/payload dicts exist
    NO hashing here (Phase 1.3).
    """
    if event.occurred_at.tzinfo is not None:
        event.occurred_at = event.occurred_at.astimezone(timezone.utc)

    if event.payload is None:
        event.payload = {}
    if event.anchors is None:
        event.anchors = {}

    return event

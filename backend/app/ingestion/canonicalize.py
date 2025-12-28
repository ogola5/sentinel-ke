from __future__ import annotations

from typing import Any, Dict
from datetime import timezone

from app.ingestion.schemas import CanonicalEvent


def build_hash_canonical_object(event: CanonicalEvent, source_id: str) -> Dict[str, Any]:
    """
    Build the canonical object to hash.
    IMPORTANT: Do NOT include received_at (varies per node).
    Do include source_id because provenance is part of evidence.
    """
    occurred_utc = event.occurred_at.astimezone(timezone.utc)

    return {
        "schema_version": event.schema_version,
        "event_type": event.event_type,
        "occurred_at": occurred_utc.isoformat(),
        "source_id": source_id,
        "confidence": float(event.confidence),
        "classification": event.classification,  # may be None; resolved later
        "anchors": event.anchors,
        "payload": event.payload,
    }

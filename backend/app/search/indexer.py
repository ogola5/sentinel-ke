from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

from opensearchpy import OpenSearch


def to_index_doc(
    *,
    event_hash: str,
    event_type: str,
    source_id: str,
    source_type: str,
    classification: str,
    schema_version: str,
    signature_valid: bool,
    occurred_at,
    received_at,
    anchors: Dict[str, str],
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    # Ensure ISO strings
    if isinstance(occurred_at, datetime):
        occurred_at = occurred_at.astimezone(timezone.utc).isoformat()
    if isinstance(received_at, datetime):
        received_at = received_at.astimezone(timezone.utc).isoformat()

    anchors_flat = [f"{k}:{v}" for k, v in anchors.items() if v]

    return {
        "event_hash": event_hash,
        "event_type": event_type,
        "source_id": source_id,
        "source_type": source_type,
        "classification": classification,
        "schema_version": schema_version,
        "signature_valid": bool(signature_valid),
        "occurred_at": occurred_at,
        "received_at": received_at,
        "anchors": anchors,
        "anchors_flat": anchors_flat,
        "payload": payload,
    }


def index_event(client: OpenSearch, index_name: str, doc: Dict[str, Any]) -> None:
    # Use event_hash as document id => idempotent indexing
    client.index(index=index_name, id=doc["event_hash"], body=doc, refresh=False)

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional


def _iso(dt: str) -> datetime:
    # messages you emit are ISO with timezone, example: 2025-12-28T11:50:35+00:00
    return datetime.fromisoformat(dt.replace("Z", "+00:00"))


@dataclass(frozen=True)
class EventView:
    event_hash: str
    event_type: str
    occurred_at: datetime
    received_at: datetime
    confidence: float
    classification: str
    signature_valid: bool
    source_id: str
    source_type: str
    anchors: Dict[str, Any]
    payload: Dict[str, Any]

    @staticmethod
    def from_bus(msg: Dict[str, Any]) -> "EventView":
        # msg format is exactly what your ingestion bus prints
        event_hash = msg["event_hash"]
        src = msg.get("source") or {}
        ev = msg.get("event") or {}

        return EventView(
            event_hash=event_hash,
            event_type=(ev.get("event_type") or "").upper(),
            occurred_at=_iso(ev["occurred_at"]),
            received_at=_iso(ev["received_at"]),
            confidence=float(ev.get("confidence") or 0.0),
            classification=(ev.get("classification") or src.get("classification") or "RESTRICTED"),
            signature_valid=bool(ev.get("signature_valid") or False),
            source_id=str(src.get("source_id") or "unknown"),
            source_type=str(src.get("source_type") or "unknown"),
            anchors=ev.get("anchors") or {},
            payload=ev.get("payload") or {},
        )

    def anchor(self, key: str) -> Optional[str]:
        v = self.anchors.get(key)
        if v is None:
            return None
        s = str(v).strip()
        return s if s else None

    def payload_get(self, key: str) -> Optional[str]:
        v = self.payload.get(key)
        if v is None:
            return None
        s = str(v).strip()
        return s if s else None

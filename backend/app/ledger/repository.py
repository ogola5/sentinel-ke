from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.ledger.models import (
    SourceRegistry,
    EventLog,
    EventEntityIndex,
    AuditLog,
)
from app.core.security import verify_api_key


class LedgerRepository:
    def __init__(self, db: Session):
        self.db = db

    # -------------------------
    # SOURCE / AUTH
    # -------------------------

    def get_source_by_api_key(self, raw_api_key: str) -> SourceRegistry | None:
        sources = self.db.query(SourceRegistry).all()
        for src in sources:
            if verify_api_key(raw_api_key, src.api_key_hash):
                return src
        return None

    def ensure_source_active(self, source: SourceRegistry):
        if not source.is_active:
            raise PermissionError("Source is disabled")

    # -------------------------
    # AUDIT
    # -------------------------

    def audit(
        self,
        actor_type: str,
        actor_id: str,
        action: str,
        target: str | None = None,
    ):
        entry = AuditLog(
            id=str(uuid.uuid4()),
            actor_type=actor_type,
            actor_id=actor_id,
            action=action,
            target=target,
            at=datetime.now(timezone.utc),
        )
        self.db.add(entry)
        self.db.commit()

    # -------------------------
    # EVENT LEDGER (APPEND ONLY)
    # -------------------------

    def insert_event_append_only(
        self,
        *,
        event_hash: str,
        event_type: str,
        source_id: str,
        classification: str,
        occurred_at,
        schema_version: str,
        signature_valid: bool,
        anchors: dict,
        payload: dict,
    ) -> tuple[str, str]:
        """
        Append-only insert with explicit idempotency and correct FK ordering.
        """

        # 1) Explicit duplicate check
        exists = (
            self.db.query(EventLog)
            .filter(EventLog.event_hash == event_hash)
            .first()
        )
        if exists:
            return event_hash, "duplicate"

        row = EventLog(
            event_hash=event_hash,
            event_type=event_type,
            source_id=source_id,
            classification=classification,
            occurred_at=occurred_at,
            schema_version=schema_version,
            signature_valid=signature_valid,
            anchors_json=anchors,
            payload_json=payload,
        )

        try:
            # 2) Insert parent row FIRST
            self.db.add(row)
            self.db.flush()  # <-- THIS IS THE CRITICAL FIX

            # 3) Insert child index rows AFTER parent exists
            for k, v in anchors.items():
                if not v:
                    continue
                entity_key = f"{k}:{v}"
                self.db.add(
                    EventEntityIndex(
                        event_hash=event_hash,
                        entity_key=entity_key,
                    )
                )

            # 4) Commit atomically
            self.db.commit()
            return event_hash, "accepted"

        except IntegrityError as e:
            self.db.rollback()
            raise RuntimeError(f"Ledger insert failed: {e}")

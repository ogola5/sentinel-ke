from __future__ import annotations

import hashlib
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


def _key_lookup_hash(raw_api_key: str) -> str:
    """SHA-256 of the raw key — used as a non-secret indexed lookup token.

    Not a replacement for the HMAC stored in api_key_hash; the full
    verify_api_key() call still happens after the indexed DB lookup.
    """
    return hashlib.sha256(raw_api_key.encode()).hexdigest()


class LedgerRepository:
    def __init__(self, db: Session):
        self.db = db

    # -------------------------
    # SOURCE / AUTH
    # -------------------------

    def get_source_by_api_key(self, raw_api_key: str) -> SourceRegistry | None:
        lookup = _key_lookup_hash(raw_api_key)

        # O(1) fast path — indexed lookup
        src = (
            self.db.query(SourceRegistry)
            .filter(SourceRegistry.api_key_lookup == lookup)
            .first()
        )
        if src and verify_api_key(raw_api_key, src.api_key_hash):
            return src

        # Backward-compat fallback for rows created before the lookup column existed.
        # On first match the column is back-filled so subsequent calls use the fast path.
        for src in (
            self.db.query(SourceRegistry)
            .filter(SourceRegistry.api_key_lookup.is_(None))
            .all()
        ):
            if verify_api_key(raw_api_key, src.api_key_hash):
                try:
                    src.api_key_lookup = lookup
                    self.db.commit()
                except Exception:
                    self.db.rollback()
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
        section_code: str | None = None,
    ):
        self.db.add(
            AuditLog(
                id=str(uuid.uuid4()),
                actor_type=actor_type,
                actor_id=actor_id,
                action=action,
                target=target,
                section_code=section_code,
                at=datetime.now(timezone.utc),
            )
        )
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
        section_code: str | None,
        classification: str,
        occurred_at,
        schema_version: str,
        signature_valid: bool,
        anchors: dict,
        payload: dict,
    ) -> tuple[str, str]:

        # Idempotency
        if self.db.get(EventLog, event_hash):
            return event_hash, "duplicate"

        try:
            self.db.add(
                EventLog(
                    event_hash=event_hash,
                    event_type=event_type,
                    source_id=source_id,
                    section_code=section_code,
                    classification=classification,
                    occurred_at=occurred_at,
                    schema_version=schema_version,
                    signature_valid=signature_valid,
                    anchors_json=anchors,
                    payload_json=payload,
                )
            )
            self.db.flush()  # guarantees FK parent exists

            for k, v in anchors.items():
                if v:
                    self.db.add(
                        EventEntityIndex(
                            event_hash=event_hash,
                            entity_key=f"{k}:{v}",
                            entity_type=str(k),
                        )
                    )

            self.db.commit()
            return event_hash, "accepted"

        except IntegrityError as e:
            self.db.rollback()
            raise RuntimeError(f"Ledger insert failed: {e}")

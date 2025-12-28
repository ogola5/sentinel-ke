from __future__ import annotations
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.ledger.models import SourceRegistry, EventLog, EventEntityIndex, AuditLog
from app.core.security import verify_api_key
from datetime import datetime, timezone
import uuid


class LedgerRepository:
    def __init__(self, db: Session):
        self.db = db

    # -------- Source Registry --------

    def get_source_by_api_key(self, raw_api_key: str) -> SourceRegistry | None:
        sources = self.db.query(SourceRegistry).all()
        for src in sources:
            if verify_api_key(raw_api_key, src.api_key_hash):
                return src
        return None

    def ensure_source_active(self, source: SourceRegistry):
        if not source.is_active:
            raise PermissionError("Source is disabled")

    # -------- Audit --------

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
            at=datetime.utcnow(),
        )
        self.db.add(entry)
        self.db.commit()

class LedgerRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_source_by_api_key(self, raw_api_key: str) -> SourceRegistry | None:
        # MVP O(n). Later replace with indexed lookup or HMAC key id.
        sources = self.db.query(SourceRegistry).all()
        for src in sources:
            if verify_api_key(raw_api_key, src.api_key_hash):
                return src
        return None

    def ensure_source_active(self, source: SourceRegistry):
        if not source.is_active:
            raise PermissionError("Source is disabled")

    def audit(self, actor_type: str, actor_id: str, action: str, target: str | None = None):
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
        Append-only insert.
        Returns: (event_hash, status) where status in {"accepted", "duplicate"}.
        """
        now = datetime.now(timezone.utc)

        row = EventLog(
            event_hash=event_hash,
            event_type=event_type,
            source_id=source_id,
            classification=classification,
            occurred_at=occurred_at,
            received_at=now,
            schema_version=schema_version,
            signature_valid=signature_valid,
            anchors_json=anchors,
            payload_json=payload,
        )

        try:
            self.db.add(row)
            # index anchors into event_entity_index
            for k, v in anchors.items():
                if v is None:
                    continue
                entity_key = f"{k}:{v}"
                self.db.add(EventEntityIndex(event_hash=event_hash, entity_key=entity_key))

            self.db.commit()
            return event_hash, "accepted"

        except IntegrityError:
            # event_hash already exists => idempotent duplicate
            self.db.rollback()
            return event_hash, "duplicate"
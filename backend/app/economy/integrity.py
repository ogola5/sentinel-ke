from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

from sqlalchemy.orm import Session

from app.analytics.economy_guardrails import ExternalIntegritySnapshot, ExternalTamperAlert
from app.core.security import sha256_hex, stable_json_dumps
from app.economy.schemas import IntegritySnapshotIn


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _hash_payload(payload: Dict[str, Any]) -> str:
    canonical = stable_json_dumps(payload).encode("utf-8")
    return sha256_hex(canonical)


def _upsert_open_alert(
    db: Session,
    *,
    source_system: str,
    record_type: str,
    record_id: str,
    alert_type: str,
    severity: str,
    confidence: float,
    reason_codes: list[str],
    details: dict,
    seen_at: datetime,
) -> ExternalTamperAlert:
    row = (
        db.query(ExternalTamperAlert)
        .filter(ExternalTamperAlert.source_system == source_system)
        .filter(ExternalTamperAlert.record_type == record_type)
        .filter(ExternalTamperAlert.record_id == record_id)
        .filter(ExternalTamperAlert.alert_type == alert_type)
        .filter(ExternalTamperAlert.status == "open")
        .first()
    )
    if row:
        row.last_seen = seen_at
        row.updated_at = _now()
        row.severity = severity
        row.confidence = confidence
        row.reason_codes = sorted(set((row.reason_codes or []) + list(reason_codes or [])))
        merged = dict(row.details_json or {})
        merged.update(details or {})
        row.details_json = merged
        return row

    row = ExternalTamperAlert(
        source_system=source_system,
        record_type=record_type,
        record_id=record_id,
        alert_type=alert_type,
        severity=severity,
        confidence=confidence,
        status="open",
        reason_codes=reason_codes,
        details_json=details,
        first_seen=seen_at,
        last_seen=seen_at,
    )
    db.add(row)
    db.flush()
    return row


def ingest_integrity_snapshot(db: Session, *, payload: IntegritySnapshotIn) -> Dict[str, Any]:
    observed_at = payload.observed_at or _now()

    latest = (
        db.query(ExternalIntegritySnapshot)
        .filter(ExternalIntegritySnapshot.source_system == payload.source_system)
        .filter(ExternalIntegritySnapshot.record_type == payload.record_type)
        .filter(ExternalIntegritySnapshot.record_id == payload.record_id)
        .order_by(ExternalIntegritySnapshot.observed_at.desc(), ExternalIntegritySnapshot.created_at.desc())
        .first()
    )

    if payload.payload_hash:
        current_hash = payload.payload_hash
    elif payload.payload:
        current_hash = _hash_payload(payload.payload)
    elif payload.is_deleted and latest and latest.payload_hash:
        current_hash = latest.payload_hash
    elif payload.is_deleted:
        current_hash = "deleted-without-prior-hash"
    else:
        current_hash = "missing-payload-hash"

    snap = ExternalIntegritySnapshot(
        source_system=payload.source_system,
        record_type=payload.record_type,
        record_id=payload.record_id,
        observed_at=observed_at,
        payload_hash=current_hash,
        is_deleted=payload.is_deleted,
        metadata_json={
            "change_ticket": payload.change_ticket,
            "actor_id": payload.actor_id,
            **(payload.metadata or {}),
        },
        evidence_json=payload.evidence or {},
    )
    db.add(snap)
    db.flush()

    alert = None
    if latest:
        if (not latest.is_deleted) and payload.is_deleted:
            alert = _upsert_open_alert(
                db,
                source_system=payload.source_system,
                record_type=payload.record_type,
                record_id=payload.record_id,
                alert_type="RECORD_DELETION",
                severity="high",
                confidence=0.9,
                reason_codes=["record_deleted_after_existing_version"],
                details={
                    "previous_hash": latest.payload_hash,
                    "current_hash": current_hash,
                    "change_ticket": payload.change_ticket,
                },
                seen_at=observed_at,
            )
        elif latest.is_deleted and (not payload.is_deleted):
            alert = _upsert_open_alert(
                db,
                source_system=payload.source_system,
                record_type=payload.record_type,
                record_id=payload.record_id,
                alert_type="RECORD_RESTORED_AFTER_DELETION",
                severity="medium",
                confidence=0.7,
                reason_codes=["record_restored_after_delete"],
                details={
                    "previous_hash": latest.payload_hash,
                    "current_hash": current_hash,
                    "change_ticket": payload.change_ticket,
                },
                seen_at=observed_at,
            )
        elif (not latest.is_deleted) and (not payload.is_deleted) and latest.payload_hash != current_hash:
            if payload.change_ticket:
                alert = _upsert_open_alert(
                    db,
                    source_system=payload.source_system,
                    record_type=payload.record_type,
                    record_id=payload.record_id,
                    alert_type="RECORD_MUTATION_WITH_TICKET",
                    severity="low",
                    confidence=0.55,
                    reason_codes=["record_hash_changed_with_change_ticket"],
                    details={
                        "previous_hash": latest.payload_hash,
                        "current_hash": current_hash,
                        "change_ticket": payload.change_ticket,
                    },
                    seen_at=observed_at,
                )
            else:
                alert = _upsert_open_alert(
                    db,
                    source_system=payload.source_system,
                    record_type=payload.record_type,
                    record_id=payload.record_id,
                    alert_type="RECORD_MUTATION_WITHOUT_TICKET",
                    severity="high",
                    confidence=0.85,
                    reason_codes=["record_hash_changed_without_change_ticket"],
                    details={
                        "previous_hash": latest.payload_hash,
                        "current_hash": current_hash,
                    },
                    seen_at=observed_at,
                )

    db.commit()
    db.refresh(snap)
    if alert:
        db.refresh(alert)

    return {
        "snapshot_id": str(snap.id),
        "source_system": snap.source_system,
        "record_type": snap.record_type,
        "record_id": snap.record_id,
        "observed_at": snap.observed_at.isoformat(),
        "payload_hash": snap.payload_hash,
        "is_deleted": snap.is_deleted,
        "alert": (
            {
                "alert_id": str(alert.id),
                "alert_type": alert.alert_type,
                "severity": alert.severity,
                "confidence": alert.confidence,
                "status": alert.status,
                "reason_codes": alert.reason_codes,
                "first_seen": alert.first_seen.isoformat(),
                "last_seen": alert.last_seen.isoformat(),
            }
            if alert
            else None
        ),
    }

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.ingestion.schemas import CanonicalEvent
from app.ingestion.validators import validate_event


def _now() -> datetime:
    return datetime.now(timezone.utc)


def test_validate_db_audit_event_payload_accepts_minimal_shape():
    ev = CanonicalEvent(
        event_type="DB_AUDIT_EVENT",
        occurred_at=_now(),
        anchors={"service_id": "pg-primary-01"},
        payload={
            "db_instance": "pg-primary-01",
            "statement_type": "SELECT",
            "success": True,
        },
    )
    validate_event(ev)


def test_validate_file_integrity_event_payload_accepts_minimal_shape():
    ev = CanonicalEvent(
        event_type="FILE_INTEGRITY_EVENT",
        occurred_at=_now(),
        anchors={"service_id": "host:county-finance-01", "endpoint": "/var/lib/postgresql/data"},
        payload={
            "host": "county-finance-01",
            "file_path": "/var/lib/postgresql/data",
            "action": "modified",
        },
    )
    validate_event(ev)


def test_validate_dfir_finding_event_payload_accepts_minimal_shape():
    ev = CanonicalEvent(
        event_type="DFIR_FINDING_EVENT",
        occurred_at=_now(),
        anchors={"service_id": "endpoint:workstation-01"},
        payload={
            "host": "workstation-01",
            "artifact_name": "Windows.Detection.Prefetch",
            "finding_type": "suspicious_binary_execution",
            "severity": "high",
        },
    )
    validate_event(ev)


def test_validate_db_audit_event_rejects_missing_required_fields():
    ev = CanonicalEvent(
        event_type="DB_AUDIT_EVENT",
        occurred_at=_now(),
        anchors={"service_id": "pg-primary-01"},
        payload={"db_instance": "pg-primary-01"},
    )
    with pytest.raises(ValueError, match="payload validation failed"):
        validate_event(ev)

import os
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.analytics.economy_guardrails import ExternalIntegritySnapshot, ExternalTamperAlert
from app.db import registry as _  # noqa: F401  # register models
from app.db.base import Base
from app.economy.integrity import ingest_integrity_snapshot
from app.economy.schemas import IntegritySnapshotIn


TEST_DB_URL_ENV = "TEST_DATABASE_URL"


def _session():
    url = os.environ.get(TEST_DB_URL_ENV)
    if not url:
        pytest.skip(f"{TEST_DB_URL_ENV} not set (expected a Postgres URL for integration test)")
    engine = create_engine(url)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    return Session()


def test_integrity_deletion_creates_alert():
    session = _session()
    try:
        session.query(ExternalTamperAlert).delete()
        session.query(ExternalIntegritySnapshot).delete()
        session.commit()

        first = IntegritySnapshotIn(
            source_system="ifmis",
            record_type="invoice",
            record_id="INV-001",
            observed_at=datetime.now(timezone.utc),
            payload={"amount": 100000, "status": "posted"},
            actor_id="svc-sync",
        )
        res1 = ingest_integrity_snapshot(session, payload=first)
        assert res1["alert"] is None

        second = IntegritySnapshotIn(
            source_system="ifmis",
            record_type="invoice",
            record_id="INV-001",
            observed_at=datetime.now(timezone.utc),
            is_deleted=True,
            actor_id="unknown",
        )
        res2 = ingest_integrity_snapshot(session, payload=second)
        assert res2["alert"] is not None
        assert res2["alert"]["alert_type"] == "RECORD_DELETION"
        assert res2["alert"]["severity"] == "high"

        alerts = session.query(ExternalTamperAlert).all()
        assert len(alerts) == 1
    finally:
        session.close()


def test_integrity_mutation_without_ticket_creates_high_alert():
    session = _session()
    try:
        session.query(ExternalTamperAlert).delete()
        session.query(ExternalIntegritySnapshot).delete()
        session.commit()

        first = IntegritySnapshotIn(
            source_system="ecitizen",
            record_type="tender_award",
            record_id="AWARD-100",
            payload={"vendor_id": "V-1", "amount": 2500000},
            actor_id="svc-sync",
        )
        res1 = ingest_integrity_snapshot(session, payload=first)
        assert res1["alert"] is None

        second = IntegritySnapshotIn(
            source_system="ecitizen",
            record_type="tender_award",
            record_id="AWARD-100",
            payload={"vendor_id": "V-1", "amount": 3900000},
            actor_id="manual-edit",
        )
        res2 = ingest_integrity_snapshot(session, payload=second)
        assert res2["alert"] is not None
        assert res2["alert"]["alert_type"] == "RECORD_MUTATION_WITHOUT_TICKET"
        assert res2["alert"]["severity"] == "high"

        alerts = session.query(ExternalTamperAlert).all()
        assert len(alerts) == 1
        assert alerts[0].record_id == "AWARD-100"
    finally:
        session.close()

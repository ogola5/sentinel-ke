from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.integrations import ingest_connector_batch, ingest_connector_event
from app.core.security import hash_api_key
from app.db import registry as _  # noqa: F401  # register models
from app.db.base import Base
from app.integrations.schemas import ConnectorBatchRequest, ConnectorEventRequest
from app.ledger.models import AuditLog, EventEntityIndex, EventLog, SourceRegistry


TEST_DB_URL_ENV = "TEST_DATABASE_URL"


def _session():
    url = os.environ.get(TEST_DB_URL_ENV)
    if not url:
        pytest.skip(f"{TEST_DB_URL_ENV} not set (expected a Postgres URL for integration test)")
    engine = create_engine(url)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    return Session()


def _reset_for_test(session):
    session.query(EventEntityIndex).delete()
    session.query(EventLog).delete()
    session.query(AuditLog).delete()
    session.query(SourceRegistry).delete()
    session.commit()


def _seed_source(session):
    session.add(
        SourceRegistry(
            source_id="integration-test-source",
            source_type="bank",
            classification_level="RESTRICTED",
            api_key_hash=hash_api_key("integration-test-key"),
            is_active=True,
        )
    )
    session.commit()


def test_ingest_connector_event_accepts_then_duplicates():
    session = _session()
    try:
        _reset_for_test(session)
        _seed_source(session)

        req = ConnectorEventRequest(
            source_api_key="integration-test-key",
            confidence=0.92,
            payload={
                "transaction_time": "2026-02-13T11:30:00Z",
                "from_account": "ACC-100",
                "to_account": "ACC-200",
                "amount": 7800,
                "currency": "KES",
                "src_ip": "41.90.1.5",
                "device_id": "ATM-02",
                "channel": "atm",
            },
        )

        r1 = ingest_connector_event("core_banking_tx_v1", req, db=session)
        assert r1["status"] == "accepted"
        assert r1["mapped_event_type"] == "TRANSACTION_EVENT"

        r2 = ingest_connector_event("core_banking_tx_v1", req, db=session)
        assert r2["status"] == "duplicate"

        rows = session.query(EventLog).all()
        assert len(rows) == 1
    finally:
        session.close()


def test_ingest_connector_batch_returns_per_item_result():
    session = _session()
    try:
        _reset_for_test(session)
        _seed_source(session)

        req = ConnectorBatchRequest(
            source_api_key="integration-test-key",
            items=[
                {
                    "_time": "2026-02-13T12:00:00Z",
                    "user": "alice",
                    "status": "failed",
                    "src_ip": "10.10.10.10",
                },
                {
                    "user": "bob",
                    "status": "success",
                    "src_ip": "10.10.10.11",
                },
            ],
        )

        out = ingest_connector_batch("splunk_login_v1", req, db=session)
        assert out["connector"] == "splunk_login_v1"
        assert len(out["results"]) == 2
        assert out["results"][0]["status"] in {"accepted", "duplicate"}
        assert "error" in out["results"][1]
    finally:
        session.close()


import os
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.economy import analyze_procurement
from app.db.base import Base
from app.db import registry as _  # noqa: F401  # register models
from app.analytics.economics import EconomicSignal, ProcurementAnomaly
from app.economy.schemas import ProcurementRecord
from app.economy.scoring import score_procurement


TEST_DB_URL_ENV = "TEST_DATABASE_URL"


def _session():
    url = os.environ.get(TEST_DB_URL_ENV)
    if not url:
        pytest.skip(f"{TEST_DB_URL_ENV} not set (expected a Postgres URL for integration test)")
    engine = create_engine(url)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    return Session()


def test_score_procurement_expected_reasons():
    record = ProcurementRecord(
        sector="public",
        amount=1500000,
        baseline_amount=900000,
        competitive_bids=1,
        vendor_award_count_90d=5,
        single_source=True,
        change_order_count=3,
    )
    scored = score_procurement(record)

    assert scored.score > 0.7
    assert scored.severity in {"high", "critical"}
    assert "amount_vs_baseline_high" in scored.reason_codes
    assert "single_source_award" in scored.reason_codes
    assert "low_competition" in scored.reason_codes
    assert "vendor_award_concentration_high" in scored.reason_codes
    assert "excessive_change_orders" in scored.reason_codes


def test_analyze_procurement_inserts_signal_and_anomaly():
    session = _session()
    try:
        session.query(ProcurementAnomaly).delete()
        session.query(EconomicSignal).delete()
        session.commit()

        record = ProcurementRecord(
            tender_id="T-001",
            vendor_id="V-123",
            project_id="P-777",
            agency="min-finance",
            sector="public",
            amount=1200000,
            baseline_amount=900000,
            competitive_bids=2,
            vendor_award_count_90d=4,
            single_source=False,
            change_order_count=2,
            occurred_at=datetime(2025, 1, 10, 10, 0, 0, tzinfo=timezone.utc),
            evidence={"doc_ref": "audit-2025-01"},
        )

        result = analyze_procurement(record=record, db=session)
        assert "signal_id" in result
        assert "anomaly_id" in result

        signals = session.query(EconomicSignal).all()
        anomalies = session.query(ProcurementAnomaly).all()

        assert len(signals) == 1
        assert len(anomalies) == 1

        signal = signals[0]
        anomaly = anomalies[0]

        assert signal.signal_type == "procurement_anomaly"
        assert signal.sector == "public"
        assert signal.entity_id == "V-123"
        assert anomaly.tender_id == "T-001"
        assert anomaly.vendor_id == "V-123"
        assert anomaly.project_id == "P-777"
        assert anomaly.agency == "min-finance"
        assert anomaly.sector == "public"
        assert anomaly.currency == "KES"
        assert anomaly.score == signal.score
        assert anomaly.severity == signal.severity
    finally:
        session.close()

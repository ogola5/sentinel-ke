import os
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.analytics.economic_leakage import LeakageAlert
from app.analytics.economics import EconomicSignal, ProcurementAnomaly
from app.analytics.layer3.economic_leakage_worker import run_once
from app.db import registry as _  # noqa: F401  # register models
from app.db.base import Base


TEST_DB_URL_ENV = "TEST_DATABASE_URL"


def _session():
    url = os.environ.get(TEST_DB_URL_ENV)
    if not url:
        pytest.skip(f"{TEST_DB_URL_ENV} not set (expected a Postgres URL for integration test)")
    engine = create_engine(url)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    return Session()


def test_economic_leakage_worker_creates_alerts_and_signals_idempotently():
    session = _session()
    try:
        session.query(LeakageAlert).delete()
        session.query(ProcurementAnomaly).delete()
        session.query(EconomicSignal).delete()
        session.commit()

        now = datetime.now(timezone.utc)
        rows = [
            ProcurementAnomaly(
                tender_id="S-1",
                vendor_id="V-901",
                project_id="P-A",
                agency="min-finance",
                sector="public",
                amount=920000,
                baseline_amount=700000,
                currency="KES",
                competitive_bids=1,
                vendor_award_count_90d=4,
                single_source=True,
                change_order_count=1,
                score=0.7,
                severity="high",
                indicators={},
                evidence={},
                occurred_at=now - timedelta(days=2),
            ),
            ProcurementAnomaly(
                tender_id="S-2",
                vendor_id="V-901",
                project_id="P-B",
                agency="min-finance",
                sector="public",
                amount=940000,
                baseline_amount=710000,
                currency="KES",
                competitive_bids=1,
                vendor_award_count_90d=4,
                single_source=True,
                change_order_count=1,
                score=0.72,
                severity="high",
                indicators={},
                evidence={},
                occurred_at=now - timedelta(days=1),
            ),
            ProcurementAnomaly(
                tender_id="S-3",
                vendor_id="V-901",
                project_id="P-C",
                agency="min-finance",
                sector="public",
                amount=910000,
                baseline_amount=690000,
                currency="KES",
                competitive_bids=1,
                vendor_award_count_90d=4,
                single_source=True,
                change_order_count=1,
                score=0.71,
                severity="high",
                indicators={},
                evidence={},
                occurred_at=now - timedelta(days=1),
            ),
            ProcurementAnomaly(
                tender_id="C-1",
                vendor_id="V-901",
                project_id="P-D",
                agency="min-finance",
                sector="public",
                amount=2_100_000,
                baseline_amount=1_300_000,
                currency="KES",
                competitive_bids=1,
                vendor_award_count_90d=4,
                single_source=True,
                change_order_count=3,
                score=0.84,
                severity="high",
                indicators={},
                evidence={},
                occurred_at=now - timedelta(days=1),
            ),
            ProcurementAnomaly(
                tender_id="C-2",
                vendor_id="V-901",
                project_id="P-E",
                agency="min-finance",
                sector="public",
                amount=2_200_000,
                baseline_amount=1_350_000,
                currency="KES",
                competitive_bids=1,
                vendor_award_count_90d=4,
                single_source=True,
                change_order_count=4,
                score=0.88,
                severity="critical",
                indicators={},
                evidence={},
                occurred_at=now - timedelta(days=1),
            ),
        ]
        session.add_all(rows)
        session.commit()

        first = run_once(db=session, window_days=30)
        assert first["candidates"] >= 2
        assert first["created"] >= 2

        alerts = session.query(LeakageAlert).all()
        assert len(alerts) >= 2
        assert any(a.detector_type == "split_tendering" for a in alerts)
        assert any(a.detector_type == "vendor_concentration" for a in alerts)

        signals = session.query(EconomicSignal).filter(EconomicSignal.signal_type.like("economic_leakage_%")).all()
        assert len(signals) >= 2

        second = run_once(db=session, window_days=30)
        assert second["created"] == 0
        assert second["updated"] >= 1
    finally:
        session.close()

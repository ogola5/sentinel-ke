import os
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.analytics.economics import EconomicSignal, ProcurementAnomaly
from app.analytics.economy_guardrails import ProcurementGuardrailDecision
from app.analytics.mitigations import Mitigation
from app.db import registry as _  # noqa: F401  # register models
from app.db.base import Base
from app.economy.guardrail import evaluate_guardrail, evaluate_and_persist_guardrail
from app.economy.schemas import ProcurementRecord


TEST_DB_URL_ENV = "TEST_DATABASE_URL"


def _session():
    url = os.environ.get(TEST_DB_URL_ENV)
    if not url:
        pytest.skip(f"{TEST_DB_URL_ENV} not set (expected a Postgres URL for integration test)")
    engine = create_engine(url)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    return Session()


def test_evaluate_guardrail_blocks_repeat_high_risk():
    record = ProcurementRecord(
        sector="public",
        agency="min-health",
        vendor_id="V-999",
        amount=2_000_000,
        baseline_amount=900_000,
        competitive_bids=1,
        single_source=True,
        change_order_count=4,
    )
    out = evaluate_guardrail(
        record=record,
        prior_anomaly_count_90d=4,
        prior_high_count_180d=2,
    )

    assert out.decision == "block"
    assert out.severity in {"high", "critical"}
    assert out.score >= 0.8
    assert "vendor_repeat_anomalies_90d" in out.reason_codes
    assert "vendor_high_risk_history_180d" in out.reason_codes


def test_evaluate_and_persist_guardrail_writes_decision_signal_and_mitigation():
    session = _session()
    try:
        session.query(ProcurementGuardrailDecision).delete()
        session.query(ProcurementAnomaly).delete()
        session.query(EconomicSignal).delete()
        session.query(Mitigation).delete()
        session.commit()

        now = datetime.now(timezone.utc)
        session.add(
            ProcurementAnomaly(
                tender_id="OLD-T-001",
                vendor_id="V-321",
                project_id="P-legacy",
                agency="min-finance",
                sector="public",
                amount=1_000_000,
                baseline_amount=600_000,
                currency="KES",
                competitive_bids=1,
                vendor_award_count_90d=6,
                single_source=True,
                change_order_count=3,
                score=0.85,
                severity="high",
                indicators={},
                evidence={},
                occurred_at=now - timedelta(days=15),
            )
        )
        session.commit()

        record = ProcurementRecord(
            tender_id="T-NEW-100",
            vendor_id="V-321",
            project_id="P-2026-01",
            agency="min-finance",
            sector="public",
            amount=1_500_000,
            baseline_amount=900_000,
            competitive_bids=1,
            vendor_award_count_90d=4,
            single_source=True,
            change_order_count=2,
            occurred_at=now,
            evidence={"doc_ref": "budget-file-1"},
        )
        result = evaluate_and_persist_guardrail(session, record=record)

        assert result["decision"] in {"review", "block"}
        assert "decision_id" in result
        assert "signal_id" in result

        decisions = session.query(ProcurementGuardrailDecision).all()
        assert len(decisions) == 1
        assert decisions[0].vendor_id == "V-321"

        signals = (
            session.query(EconomicSignal)
            .filter(EconomicSignal.signal_type == "procurement_guardrail")
            .all()
        )
        assert len(signals) == 1

        mitigations = (
            session.query(Mitigation)
            .filter(Mitigation.kind == "ECONOMY")
            .all()
        )
        assert len(mitigations) == 1
    finally:
        session.close()

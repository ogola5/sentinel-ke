from __future__ import annotations

from datetime import datetime, timezone

from app.analytics.corruption.feature_builder import corruption_training_label
from app.analytics.corruption.outcome_ingest import (
    OutcomeRecord,
    _derive_outcome_signals,
    normalize_outcome_row,
)


def _sample_outcome_record(**overrides) -> OutcomeRecord:
    base = OutcomeRecord(
        outcome_id="OUT-001",
        case_id="CASE-001",
        occurred_at=datetime(2026, 3, 24, 17, 0, tzinfo=timezone.utc),
        department_id="MIN-FIN",
        department_name="National Treasury",
        supplier_id="SUP-001",
        supplier_name="Alpha Works Ltd",
        official_id="OFF-001",
        contract_id="CON-001",
        project_id="PRJ-001",
        project_title="County Fibre Expansion",
        finding_type="audit_finding",
        outcome_status="sanctioned",
        sanction_type="debarment",
        loss_amount_ksh=8_000_000.0,
        recovery_amount_ksh=2_500_000.0,
        source_system="auditor_general",
    )
    values = {**base.__dict__, **overrides}
    return OutcomeRecord(**values)


def test_normalize_outcome_row_parses_case_and_sanction_fields():
    row = {
        "outcome_id": "OUT-900",
        "case_id": "CASE-900",
        "decision_date": "2026-03-24T17:00:00Z",
        "department_id": "MIN-WATER",
        "department_name": "Ministry of Water",
        "supplier_id": "SUP-900",
        "supplier_name": "Beta Civil Works",
        "official_id": "OFF-900",
        "contract_id": "CON-900",
        "project_id": "PRJ-900",
        "project_title": "Borehole Rehab",
        "finding_type": "ppra_audit",
        "decision_status": "upheld",
        "sanction_type": "debarment",
        "loss_amount": "8000000",
        "recovered_amount": "2500000",
        "source_system": "ppra",
    }

    out = normalize_outcome_row(row)

    assert out is not None
    assert out.outcome_id == "OUT-900"
    assert out.case_id == "CASE-900"
    assert out.department_id == "MIN-WATER"
    assert out.supplier_id == "SUP-900"
    assert out.official_id == "OFF-900"
    assert out.contract_id == "CON-900"
    assert out.project_id == "PRJ-900"
    assert out.finding_type == "ppra_audit"
    assert out.outcome_status == "upheld"
    assert out.sanction_type == "debarment"
    assert out.loss_amount_ksh == 8_000_000.0
    assert out.recovery_amount_ksh == 2_500_000.0


def test_derive_outcome_signals_marks_adverse_case_and_recovery():
    record = _sample_outcome_record()

    out = _derive_outcome_signals(record)

    assert out.adverse is True
    assert out.cleared is False
    assert out.audit_finding is True
    assert out.sanction_applied is True
    assert out.recovery_order is True
    assert out.supplier_sanctioned is True
    assert out.official_sanctioned is True
    assert out.outcome_label == 1
    assert {
        "AUDIT_FINDING",
        "CASE_CONFIRMED_CORRUPTION",
        "DEBARRED_SUPPLIER",
        "OFFICIAL_SANCTIONED",
        "RECOVERY_ORDER",
    }.issubset(set(out.risk_flags))
    assert {
        "AUDIT_FINDING_EVENT",
        "CASE_OUTCOME_RECORDED",
        "RECOVERY_ORDER",
        "SANCTION_APPLIED",
    }.issubset(set(out.extra_event_types))


def test_corruption_training_label_prefers_outcome_label():
    assert corruption_training_label(
        risk_flags=[],
        event_count=0,
        single_source=False,
        director_conflict=False,
        outcome_label=1,
    ) == 1
    assert corruption_training_label(
        risk_flags=["AUDIT_FINDING"],
        event_count=20,
        single_source=True,
        director_conflict=True,
        outcome_label=0,
    ) == 0

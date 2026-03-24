from __future__ import annotations

from datetime import datetime, timezone

from app.analytics.corruption.payment_ingest import (
    PaymentTrailRecord,
    _derive_payment_signals,
    normalize_payment_row,
)


def _sample_payment_record(**overrides) -> PaymentTrailRecord:
    base = PaymentTrailRecord(
        payment_id="PAY-001",
        invoice_id="INV-001",
        voucher_id="VCH-001",
        occurred_at=datetime(2026, 3, 24, 10, 0, tzinfo=timezone.utc),
        department_id="MIN-WATER",
        department_name="Ministry of Water",
        supplier_id="SUP-001",
        supplier_name="Alpha Works Ltd",
        contract_id="CON-001",
        project_id="PRJ-001",
        project_title="Dam Rehabilitation",
        approver_id="APR-001",
        account_id="ACC-001",
        milestone_id="MILE-001",
        amount_ksh=2_500_000.0,
        approved_amount_ksh=2_500_000.0,
        advance_payment_ksh=750_000.0,
        retention_amount_ksh=150_000.0,
        delivery_progress_pct=0.2,
        certified_progress_pct=0.7,
        approval_stage_count=1,
        due_at=datetime(2026, 2, 1, 10, 0, tzinfo=timezone.utc),
        released_at=datetime(2026, 3, 15, 10, 0, tzinfo=timezone.utc),
        payment_status="held",
        emergency_procurement=True,
        supplier_debarred=True,
        audit_flag=True,
        manual_override=True,
    )
    values = {**base.__dict__, **overrides}
    return PaymentTrailRecord(**values)


def test_normalize_payment_row_parses_ifmis_style_fields():
    row = {
        "payment_id": "PAY-900",
        "invoice_id": "INV-900",
        "voucher_id": "VCH-900",
        "approved_at": "2026-03-24T10:00:00Z",
        "department_id": "MIN-FIN",
        "department_name": "National Treasury",
        "supplier_id": "SUP-900",
        "supplier_name": "Beta Supplies",
        "contract_id": "CON-900",
        "project_id": "PRJ-900",
        "project_title": "County Fibre Phase 3",
        "approver_id": "APR-900",
        "account_id": "ACC-900",
        "milestone_id": "MILE-900",
        "approved_amount": "2500000",
        "advance_amount": "750000",
        "retention_amount": "150000",
        "delivery_progress_pct": "20",
        "certified_progress_pct": "70",
        "approval_steps": "1",
        "payment_due_date": "2026-02-01T10:00:00Z",
        "payment_released_at": "2026-03-15T10:00:00Z",
        "status": "held",
        "emergency_flag": "true",
        "debarred_supplier": "yes",
        "audit_exception_flag": "true",
        "override_flag": "true",
    }

    out = normalize_payment_row(row)

    assert out is not None
    assert out.payment_id == "PAY-900"
    assert out.invoice_id == "INV-900"
    assert out.department_id == "MIN-FIN"
    assert out.supplier_id == "SUP-900"
    assert out.contract_id == "CON-900"
    assert out.project_id == "PRJ-900"
    assert out.approver_id == "APR-900"
    assert out.account_id == "ACC-900"
    assert out.amount_ksh == 2_500_000.0
    assert out.advance_payment_ksh == 750_000.0
    assert out.delivery_progress_pct == 0.2
    assert out.certified_progress_pct == 0.7
    assert out.approval_stage_count == 1
    assert out.payment_status == "held"
    assert out.emergency_procurement is True
    assert out.supplier_debarred is True
    assert out.audit_flag is True
    assert out.manual_override is True


def test_derive_payment_signals_flags_bypass_delay_and_delivery_risk():
    record = _sample_payment_record()

    out = _derive_payment_signals(record, approver_load=4)

    assert out.approver_load == 4
    assert out.payment_split is False
    assert out.approval_bypass is True
    assert out.delayed_payment is True
    assert out.high_advance is True
    assert out.delivery_mismatch is True
    assert out.approver_concentration is True
    assert out.payment_to_delivery_ratio > 0.35
    assert out.progress_mismatch == 0.5
    assert {
        "ADVANCE_PAYMENT_RISK",
        "AUDIT_FINDING",
        "DEBARRED_SUPPLIER",
        "PAYMENT_APPROVAL_BYPASS",
        "PAYMENT_DELAY_RISK",
        "PROJECT_DELIVERY_MISMATCH",
    }.issubset(set(out.risk_flags))
    assert {
        "APPROVER_LINK",
        "ADVANCE_PAYMENT",
        "INVOICE_APPROVED",
        "PAYMENT_DISBURSEMENT",
        "PAYMENT_HOLD",
        "PAYMENT_VOUCHER_CREATED",
        "PROJECT_MILESTONE_CERTIFIED",
    }.issubset(set(out.extra_event_types))

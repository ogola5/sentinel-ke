from __future__ import annotations

from datetime import datetime, timezone

from app.analytics.corruption.ocds_ingest import (
    ProcurementRecord,
    _derive_procurement_signals,
    _event_entities_for_type,
    normalize_procurement_row,
)


def _sample_record(**overrides) -> ProcurementRecord:
    base = ProcurementRecord(
        ocid="ocds-123",
        occurred_at=datetime(2026, 3, 1, 10, 0, tzinfo=timezone.utc),
        buyer_id="MIN-ICT",
        buyer_name="Ministry of ICT",
        tender_id="TEN-001",
        tender_title="National Connectivity Backbone Upgrade",
        supplier_id="SUP-001",
        supplier_name="Alpha Networks Ltd",
        contract_id="CON-001",
        award_id="AWD-001",
        amount_ksh=1_250_000.0,
        estimated_amount_ksh=900_000.0,
        payment_amount_ksh=950_000.0,
        advance_payment_ksh=200_000.0,
        procurement_method="direct",
        procurement_method_details="emergency single source",
        tenderer_count=1,
        supplier_registered_at=datetime(2025, 11, 15, tzinfo=timezone.utc),
        supplier_cluster_key="kra123|acct-1|sales@alpha.example",
        audit_flag=True,
        amendment_count=2,
        amended_amount_ksh=1_600_000.0,
        project_id="P-001",
        project_title="County Fibre Phase 1",
        supplier_director_id="DIR-001",
        supplier_bank_account="ACCT-1",
        inspector_id="ENG-001",
        milestone_id="CERT-001",
        delivery_progress_pct=0.4,
        certified_progress_pct=0.8,
        complaint_count=2,
        quality_failure_count=1,
        delay_days=45,
        supplier_debarred=True,
        delivery_status="delayed",
    )
    values = {**base.__dict__, **overrides}
    return ProcurementRecord(**values)


def test_normalize_procurement_row_parses_flat_ocds_award():
    row = {
        "ocid": "ocds-123",
        "buyer_id": "MIN-ICT",
        "buyer_name": "Ministry of ICT",
        "tender_id": "TEN-001",
        "award_date": "2026-03-01T10:00:00Z",
        "supplier_id": "SUP-001",
        "supplier_name": "Alpha Networks Ltd",
        "award_value_amount": "1250000",
        "tender_value_amount": "900000",
        "procurement_method": "direct",
        "supplier_registration_date": "2025-11-15",
        "supplier_email": "sales@alpha.example",
    }

    out = normalize_procurement_row(row)

    assert out is not None
    assert out.ocid == "ocds-123"
    assert out.buyer_id == "MIN-ICT"
    assert out.supplier_id == "SUP-001"
    assert out.amount_ksh == 1_250_000.0
    assert out.estimated_amount_ksh == 900_000.0
    assert out.procurement_method == "direct"
    assert out.supplier_cluster_key == "sales@alpha.example"


def test_normalize_procurement_row_parses_delivery_and_network_fields():
    row = {
        "ocid": "ocds-456",
        "buyer_id": "MIN-WATER",
        "buyer_name": "Ministry of Water",
        "tender_id": "TEN-900",
        "award_date": "2026-02-14T08:15:00Z",
        "supplier_id": "SUP-900",
        "supplier_name": "Beta Civil Works",
        "award_value_amount": "3200000",
        "tender_value_amount": "2500000",
        "procurement_method": "restricted",
        "supplier_registration_date": "2025-12-01",
        "supplier_tax_id": "KRA123",
        "supplier_bank_account": "ACCT-1",
        "supplier_email": "ops@beta.example",
        "project_id": "PRJ-22",
        "project_title": "Borehole Rehabilitation Phase 2",
        "beneficial_owner_id": "DIR-900",
        "site_inspector_id": "INS-77",
        "certificate_id": "CERT-77",
        "delivery_progress_pct": "40",
        "certified_progress_pct": "80",
        "complaint_count": "2",
        "quality_failure_count": "1",
        "delay_days": "45",
        "supplier_debarred": "yes",
        "delivery_status": "delayed",
    }

    out = normalize_procurement_row(row)

    assert out is not None
    assert out.project_id == "PRJ-22"
    assert out.project_title == "Borehole Rehabilitation Phase 2"
    assert out.supplier_director_id == "DIR-900"
    assert out.supplier_bank_account == "ACCT-1"
    assert out.inspector_id == "INS-77"
    assert out.milestone_id == "CERT-77"
    assert out.delivery_progress_pct == 0.4
    assert out.certified_progress_pct == 0.8
    assert out.complaint_count == 2
    assert out.quality_failure_count == 1
    assert out.delay_days == 45
    assert out.supplier_debarred is True
    assert out.delivery_status == "delayed"
    assert out.supplier_cluster_key == "kra123|acct-1"


def test_derive_procurement_signals_flags_tender_manipulation_and_delivery_risk():
    record = _sample_record()

    out = _derive_procurement_signals(record, family_size=3)

    assert out.cluster_shared is True
    assert out.family_size == 3
    assert out.price_inflated is True
    assert out.amendment_inflated is True
    assert out.shell_company is True
    assert out.single_source is True
    assert out.emergency is True
    assert out.project_delay is True
    assert out.complaints_active is True
    assert out.quality_failure is True
    assert out.delivery_mismatch is True
    assert out.payment_to_delivery_ratio > 0.35
    assert {
        "AUDIT_FINDING",
        "COMPLAINT_PRESSURE",
        "DEBARRED_SUPPLIER",
        "DIRECTOR_CONFLICT",
        "PRICE_INFLATION",
        "PROJECT_DELAY_RISK",
        "PROJECT_DELIVERY_MISMATCH",
        "QUALITY_FAILURE",
        "RELATED_PARTY_TRANSACTION",
        "SHELL_COMPANY",
    }.issubset(set(out.risk_flags))
    assert {
        "ADVANCE_PAYMENT",
        "AUDIT_FINDING_EVENT",
        "COMPLAINT_FILED",
        "COMPANY_REGISTRATION",
        "DEFECT_NOTICE",
        "EMERGENCY_PROCUREMENT",
        "PAYMENT_DISBURSEMENT",
        "PROJECT_DELAY",
        "PROJECT_MILESTONE_CERTIFIED",
        "SITE_INSPECTION",
        "SINGLE_SOURCE_AWARD",
        "TENDER_AMENDMENT",
    }.issubset(set(out.extra_event_types))


def test_event_entities_for_type_adds_relationship_entities():
    base_entities = [
        "department:min-water",
        "tender:ten-900",
        "supplier:sup-900",
        "contract:con-900",
        "project:prj-22",
    ]

    payment_entities = _event_entities_for_type(
        event_type="PAYMENT_DISBURSEMENT",
        base_entities=base_entities,
        supplier_key="supplier:sup-900",
        supplier_family_key="supplier_family:abc123",
        director_key="director:dir-900",
        account_key="account:acct-1",
        inspector_key="official:ins-77",
    )
    inspection_entities = _event_entities_for_type(
        event_type="SITE_INSPECTION",
        base_entities=base_entities,
        supplier_key="supplier:sup-900",
        supplier_family_key="supplier_family:abc123",
        director_key="director:dir-900",
        account_key="account:acct-1",
        inspector_key="official:ins-77",
    )
    registration_entities = _event_entities_for_type(
        event_type="COMPANY_REGISTRATION",
        base_entities=base_entities,
        supplier_key="supplier:sup-900",
        supplier_family_key="supplier_family:abc123",
        director_key="director:dir-900",
        account_key="account:acct-1",
        inspector_key="official:ins-77",
    )

    assert "account:acct-1" in payment_entities
    assert "official:ins-77" in inspection_entities
    assert registration_entities == [
        "supplier:sup-900",
        "supplier_family:abc123",
        "director:dir-900",
    ]

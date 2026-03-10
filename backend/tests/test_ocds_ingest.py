from __future__ import annotations

from app.analytics.corruption.ocds_ingest import normalize_procurement_row


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

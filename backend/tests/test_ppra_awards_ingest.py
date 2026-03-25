from __future__ import annotations

from app.analytics.corruption.ppra_awards_ingest import normalize_ppra_awards_row


def test_normalize_ppra_awards_row_maps_award_portal_fields():
    row = {
        "contract_award_no": "CA-2026-001",
        "date_of_award": "2026-03-01T10:00:00Z",
        "procuring_entity": "Ministry of ICT",
        "procuring_entity_id": "MIN-ICT",
        "tender_no": "TEN-900",
        "procurement_title": "National Connectivity Backbone Upgrade",
        "awardee_name": "Alpha Networks Ltd",
        "supplier_pin": "P051234567X",
        "contract_sum": "1250000",
        "estimated_cost": "900000",
        "procurement_method": "direct",
        "number_of_bidders": "1",
        "project_name": "County Fibre Phase 1",
    }

    out = normalize_ppra_awards_row(row)

    assert out is not None
    assert out.ocid == "CA-2026-001"
    assert out.buyer_id == "MIN-ICT"
    assert out.supplier_id == "P051234567X"
    assert out.amount_ksh == 1_250_000.0
    assert out.estimated_amount_ksh == 900_000.0
    assert out.project_title == "County Fibre Phase 1"

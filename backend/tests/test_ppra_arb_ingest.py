from __future__ import annotations

from app.analytics.corruption.ppra_arb_ingest import normalize_ppra_arb_row


def test_normalize_ppra_arb_row_marks_set_aside_decision_as_adverse():
    row = {
        "application_no": "ARB-2026-011",
        "decision_date": "2026-03-10T09:00:00Z",
        "procuring_entity": "Kenya Rural Roads Authority",
        "procuring_entity_id": "KERRA",
        "awardee_name": "Beta Civil Works",
        "awardee_id": "SUP-900",
        "decision_summary": "The Board sets aside the award and orders repeat evaluation.",
        "amount_in_issue": "8000000",
    }

    out = normalize_ppra_arb_row(row)

    assert out is not None
    assert out.case_id == "ARB-2026-011"
    assert out.department_id == "KERRA"
    assert out.supplier_id == "SUP-900"
    assert out.outcome_status == "adverse"
    assert out.sanction_type == "award_set_aside"
    assert out.loss_amount_ksh == 8_000_000.0

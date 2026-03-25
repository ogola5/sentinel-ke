from __future__ import annotations

from app.analytics.corruption.public_case_outcome_ingest import (
    normalize_eacc_row,
    normalize_kenyalaw_row,
)


def test_normalize_kenyalaw_row_maps_conviction_to_confirmed_outcome():
    row = {
        "case_number": "ACC-12-2026",
        "judgment_date": "2026-03-20T10:00:00Z",
        "title": "Republic v Director of Alpha Works",
        "summary": "The court convicted the accused and ordered recovery.",
        "agency_name": "Kenya National Highways Authority",
        "company_name": "Alpha Works Ltd",
        "recovery_amount_ksh": "2500000",
    }

    out = normalize_kenyalaw_row(row)

    assert out is not None
    assert out.case_id == "ACC-12-2026"
    assert out.outcome_status == "confirmed"
    assert out.supplier_name == "Alpha Works Ltd"
    assert out.recovery_amount_ksh == 2_500_000.0


def test_normalize_eacc_row_maps_dismissed_case():
    row = {
        "reference_no": "EACC-2026-02",
        "date": "2026-03-21T10:00:00Z",
        "title": "Petition against county procurement officials",
        "outcome": "The petition was dismissed.",
        "agency_name": "County Government of Mombasa",
        "official_name": "John Doe",
    }

    out = normalize_eacc_row(row)

    assert out is not None
    assert out.case_id == "EACC-2026-02"
    assert out.outcome_status == "dismissed"
    assert out.department_name == "County Government of Mombasa"

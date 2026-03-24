from __future__ import annotations

from datetime import datetime, timezone

from app.analytics.corruption.registry_ingest import (
    RegistryRecord,
    _derive_registry_signals,
    normalize_registry_row,
)


def _sample_registry_record(**overrides) -> RegistryRecord:
    base = RegistryRecord(
        company_id="COMP-001",
        company_name="Alpha Works Ltd",
        occurred_at=datetime(2026, 3, 24, 9, 0, tzinfo=timezone.utc),
        registered_at=datetime(2025, 12, 1, tzinfo=timezone.utc),
        director_id="DIR-001",
        beneficial_owner_id="DIR-001",
        tax_id="P051234567A",
        bank_account="00123456789",
        email="ops@alpha.example",
        phone="+254700111222",
        address="Nairobi CBD",
        supplier_cluster_key="p051234567a|00123456789",
        debarred=True,
        debarred_at=datetime(2026, 3, 20, 9, 0, tzinfo=timezone.utc),
        watchlist_flag=True,
        watchlist_reason="PEP overlap",
    )
    values = {**base.__dict__, **overrides}
    return RegistryRecord(**values)


def test_normalize_registry_row_parses_supplier_network_fields():
    row = {
        "company_id": "COMP-900",
        "company_name": "Beta Civil Works",
        "registered_at": "2025-12-01",
        "updated_at": "2026-03-24T09:15:00Z",
        "beneficial_owner_id": "DIR-900",
        "tax_id": "P051111111K",
        "bank_account": "ACC-900",
        "email": "ops@beta.example",
        "phone": "+254700123456",
        "address": "Westlands",
        "debarred": "yes",
        "debarred_at": "2026-03-20",
        "watchlist_flag": "true",
        "watchlist_reason": "Shared sanctioned owner",
    }

    out = normalize_registry_row(row)

    assert out is not None
    assert out.company_id == "COMP-900"
    assert out.company_name == "Beta Civil Works"
    assert out.director_id == "DIR-900"
    assert out.beneficial_owner_id == "DIR-900"
    assert out.debarred is True
    assert out.watchlist_flag is True
    assert out.watchlist_reason == "Shared sanctioned owner"
    assert out.supplier_cluster_key == "p051111111k|acc-900"


def test_derive_registry_signals_marks_cluster_and_debarment_risk():
    record = _sample_registry_record()

    out = _derive_registry_signals(record, family_size=3)

    assert out.family_size == 3
    assert out.cluster_shared is True
    assert out.shell_company is True
    assert out.debarred is True
    assert out.watchlist_flag is True
    assert {
        "DEBARRED_SUPPLIER",
        "DIRECTOR_CONFLICT",
        "RELATED_PARTY_TRANSACTION",
        "SHELL_COMPANY",
    }.issubset(set(out.risk_flags))
    assert {
        "COMPANY_REGISTRATION",
        "SUPPLIER_NETWORK_LINK",
        "DEBARMENT_LISTING",
        "WATCHLIST_HIT",
    }.issubset(set(out.extra_event_types))

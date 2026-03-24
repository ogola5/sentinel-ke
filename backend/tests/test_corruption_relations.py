from __future__ import annotations

from app.analytics.corruption.feature_builder import (
    CORRUPTION_ENTITY_TYPES,
    corruption_build_feature_vector,
)
from app.analytics.corruption.relations import derive_typed_edges_for_event


def test_supplier_network_link_derives_family_director_and_account_edges():
    edges = derive_typed_edges_for_event(
        event_type="SUPPLIER_NETWORK_LINK",
        entity_keys=[
            "supplier:sup-001",
            "supplier_family:abc123",
            "director:dir-001",
            "account:acc-001",
        ],
    )

    edge_map = {(src, dst): weight for src, dst, weight in edges}

    assert edge_map[("account:acc-001", "supplier:sup-001")] == 4.0
    assert edge_map[("director:dir-001", "supplier:sup-001")] == 4.4
    assert edge_map[("supplier:sup-001", "supplier_family:abc123")] == 5.0
    assert edge_map[("account:acc-001", "supplier_family:abc123")] == 3.9
    assert edge_map[("director:dir-001", "supplier_family:abc123")] == 4.1


def test_case_outcome_recorded_derives_enforcement_structure_edges():
    edges = derive_typed_edges_for_event(
        event_type="CASE_OUTCOME_RECORDED",
        entity_keys=[
            "department:min-water",
            "supplier:sup-001",
            "official:off-001",
            "contract:con-001",
            "project:prj-001",
        ],
    )

    edge_map = {(src, dst): weight for src, dst, weight in edges}

    assert edge_map[("contract:con-001", "department:min-water")] == 3.1
    assert edge_map[("contract:con-001", "supplier:sup-001")] == 3.1
    assert edge_map[("contract:con-001", "project:prj-001")] == 3.5
    assert edge_map[("official:off-001", "supplier:sup-001")] == 2.4
    assert edge_map[("contract:con-001", "official:off-001")] == 2.7


def test_unknown_event_type_derives_no_typed_edges():
    assert derive_typed_edges_for_event(
        event_type="UNRELATED_EVENT",
        entity_keys=["supplier:sup-001", "contract:con-001"],
    ) == []


def test_supplier_family_entity_type_maps_to_company_feature_slot():
    vec = corruption_build_feature_vector(
        entity_type="supplier_family",
        event_count=1,
        transaction_count=0,
        counterparty_count=1,
        total_value_ksh=0.0,
        degree=1,
        risk_flags=[],
        corruption_events={},
    )

    company_idx = CORRUPTION_ENTITY_TYPES.index("company")
    assert vec[company_idx] == 1.0

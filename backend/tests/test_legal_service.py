from __future__ import annotations

from types import SimpleNamespace

from app.legal.schemas import ApprovalPayloadRequest, ScanCandidate
from app.legal.service import (
    _match_action,
    _match_target,
    LegalAuthorizationService,
    build_approval_message,
    greedy_select_candidates,
)


def test_match_action_supports_wildcards():
    assert _match_action("active_network_probe", ["active_*"])
    assert _match_action("database_integrity_scan", ["*"])
    assert not _match_action("database_dump", ["active_*", "integrity_*"])


def test_match_target_supports_exact_and_cidr_and_pattern():
    assert _match_target("10.10.10.5", ["10.10.10.0/24"])
    assert _match_target("db:payments.primary", ["db:*"])
    assert _match_target("core-router-01", ["core-router-*"])
    assert not _match_target("192.168.1.12", ["10.0.0.0/8"])


def test_build_approval_message_is_deterministic():
    req = ApprovalPayloadRequest(
        order_id="ord-1",
        action_type="economic_leakage_scan",
        target="economy:procurement",
        requested_by="analyst-a",
        requested_minutes=45,
    )
    msg1, digest1 = build_approval_message(req)
    msg2, digest2 = build_approval_message(req)
    assert msg1 == msg2
    assert digest1 == digest2


def test_greedy_select_respects_scope_and_budget():
    candidates = [
        ScanCandidate(target="10.0.0.10", estimated_cost=5.0, risk_score=0.9, criticality=2.0, intel_confidence=0.9),
        ScanCandidate(target="10.0.0.20", estimated_cost=2.0, risk_score=0.4, criticality=1.0, intel_confidence=1.0),
        ScanCandidate(target="172.16.0.2", estimated_cost=1.0, risk_score=1.0, criticality=1.0, intel_confidence=1.0),
    ]

    selected, skipped, used_budget, utility = greedy_select_candidates(
        candidates=candidates,
        max_budget=6.0,
        allowed_targets=["10.0.0.0/24"],
    )

    assert used_budget <= 6.0
    assert utility > 0.0
    assert all(item["target"].startswith("10.0.0.") for item in selected)
    assert any(item["reason"] == "target_not_in_scope" for item in skipped)


def test_greedy_select_prefers_higher_ratio():
    candidates = [
        ScanCandidate(target="db:a", estimated_cost=8.0, risk_score=0.9, criticality=1.0, intel_confidence=1.0),
        ScanCandidate(target="db:b", estimated_cost=2.0, risk_score=0.8, criticality=1.0, intel_confidence=1.0),
        ScanCandidate(target="db:c", estimated_cost=2.0, risk_score=0.7, criticality=1.0, intel_confidence=1.0),
    ]
    selected, skipped, used_budget, _ = greedy_select_candidates(
        candidates=candidates,
        max_budget=4.0,
        allowed_targets=["db:*"],
    )

    assert used_budget == 4.0
    assert [x["target"] for x in selected] == ["db:b", "db:c"]
    assert any(x["target"] == "db:a" and x["reason"] == "budget_exceeded" for x in skipped)


def test_grant_to_dict_hides_execution_token_by_default():
    row = SimpleNamespace(
        grant_id="g1",
        order_id="o1",
        action_type="economic_leakage_scan",
        target="economy:procurement",
        requested_by="analyst-a",
        approved_by_json=["a", "b"],
        status="allow",
        reason_codes_json=["authorized"],
        valid_from=SimpleNamespace(isoformat=lambda: "2026-01-01T00:00:00+00:00"),
        valid_until=SimpleNamespace(isoformat=lambda: "2026-01-01T01:00:00+00:00"),
        execution_token="secret-token",
        evidence_json={},
        created_at=SimpleNamespace(isoformat=lambda: "2026-01-01T00:00:00+00:00"),
    )
    out = LegalAuthorizationService._grant_to_dict(row)
    assert "execution_token" not in out


def test_grant_to_dict_can_include_execution_token():
    row = SimpleNamespace(
        grant_id="g1",
        order_id="o1",
        action_type="economic_leakage_scan",
        target="economy:procurement",
        requested_by="analyst-a",
        approved_by_json=["a", "b"],
        status="allow",
        reason_codes_json=["authorized"],
        valid_from=SimpleNamespace(isoformat=lambda: "2026-01-01T00:00:00+00:00"),
        valid_until=SimpleNamespace(isoformat=lambda: "2026-01-01T01:00:00+00:00"),
        execution_token="secret-token",
        evidence_json={},
        created_at=SimpleNamespace(isoformat=lambda: "2026-01-01T00:00:00+00:00"),
    )
    out = LegalAuthorizationService._grant_to_dict(row, include_execution_token=True)
    assert out["execution_token"] == "secret-token"

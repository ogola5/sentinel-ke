from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.api import federation


class _FakeQuery:
    def __init__(self, rows):
        self.rows = list(rows)

    def filter(self, *args, **kwargs):  # noqa: ANN002, ARG002
        return self

    def order_by(self, *args, **kwargs):  # noqa: ANN002, ARG002
        return self

    def all(self):
        return list(self.rows)

    def first(self):
        return self.rows[0] if self.rows else None


class _FakeDB:
    def __init__(self, query_rows=None):
        self.query_rows = query_rows or {}

    def query(self, model):  # noqa: ANN001
        return _FakeQuery(self.query_rows.get(model, []))


def test_build_warning_from_patterns_sets_partner_targets_and_defaults():
    now = datetime(2026, 3, 24, 12, 0, tzinfo=timezone.utc)
    rows = [
        SimpleNamespace(
            partner_id="cbk-ke",
            entity_key_hash="abc123",
            entity_type="phone_h",
            fraud_family="SIM_SWAP",
            risk_flags=["CAMPAIGN_ENTITY"],
            window_start=now - timedelta(minutes=15),
            window_end=now - timedelta(minutes=10),
            received_at=now - timedelta(minutes=9),
            risk_score=0.91,
            chain_score=0.82,
        ),
        SimpleNamespace(
            partner_id="safaricom-ke",
            entity_key_hash="abc123",
            entity_type="phone_h",
            fraud_family="SIM_SWAP",
            risk_flags=["CROSS_PARTNER_SIGNAL"],
            window_start=now - timedelta(minutes=14),
            window_end=now - timedelta(minutes=8),
            received_at=now - timedelta(minutes=7),
            risk_score=0.87,
            chain_score=0.78,
        ),
    ]

    payload = federation._build_warning_from_patterns(rows=rows)

    assert payload.entity_key_hash == "abc123"
    assert payload.threat_family == "SIM_SWAP"
    assert payload.source_partner_ids == ["cbk-ke", "safaricom-ke"]
    assert payload.target_partner_ids == ["cbk-ke", "safaricom-ke"]
    assert payload.severity in {"medium", "high", "critical"}
    assert payload.recommended_actions


def test_partner_warning_inbox_hides_other_partner_targets_and_acks():
    warning_id = uuid.uuid4()
    now = datetime(2026, 3, 24, 12, 0, tzinfo=timezone.utc)
    warning = SimpleNamespace(
        id=warning_id,
        created_at=now,
        updated_at=now,
        created_by_actor="central:ncsc",
        source_kind="correlation",
        entity_key_hash="hash-1",
        entity_type="phone_h",
        threat_family="SIM_SWAP",
        severity="high",
        urgency="urgent",
        title="High cross-agency SIM swap warning",
        summary_text="Validate the local customer and session posture.",
        tlp="amber",
        classification="RESTRICTED",
        status="open",
        source_partner_ids=["cbk-ke", "safaricom-ke"],
        target_partner_ids=["cbk-ke", "equity-ke"],
        first_seen=now - timedelta(minutes=20),
        last_seen=now - timedelta(minutes=2),
        correlation_count=2,
        max_risk=0.93,
        avg_risk=0.89,
        max_chain_score=0.81,
        risk_flags=["CAMPAIGN_ENTITY"],
        recommended_actions=["Escalate to local fraud queue."],
        metadata_json={"window_hours": 6},
    )
    cbk_ack = SimpleNamespace(
        warning_id=warning_id,
        partner_id="cbk-ke",
        status="received",
        acknowledged_at=now,
        detail_json={"ticket": "CBK-77"},
    )
    equity_ack = SimpleNamespace(
        warning_id=warning_id,
        partner_id="equity-ke",
        status="resolved",
        acknowledged_at=now,
        detail_json={"ticket": "EQ-22"},
    )
    db = _FakeDB(
        query_rows={
            federation.FederationWarning: [warning],
            federation.FederationWarningAck: [cbk_ack, equity_ack],
        }
    )

    out = federation.partner_warning_inbox(
        status="open",
        limit=100,
        partner=SimpleNamespace(partner_id="cbk-ke"),
        db=db,
    )

    assert out["partner_id"] == "cbk-ke"
    assert out["total_found"] == 1
    row = out["warnings"][0]
    assert row["created_by_actor"] == "central-command"
    assert row["source_partner_ids"] == []
    assert row["target_partner_ids"] == ["cbk-ke"]
    assert row["source_partner_count"] == 2
    assert row["target_partner_count"] == 2
    assert row["partner_ack_status"] == "received"
    assert row["acknowledgements"] == [
        {
            "partner_id": "cbk-ke",
            "status": "received",
            "acknowledged_at": now.isoformat(),
            "detail": {"ticket": "CBK-77"},
        }
    ]


def test_list_warnings_central_keeps_all_acknowledgements():
    warning_id = uuid.uuid4()
    now = datetime(2026, 3, 24, 12, 0, tzinfo=timezone.utc)
    warning = SimpleNamespace(
        id=warning_id,
        created_at=now,
        updated_at=now,
        created_by_actor="central:ncsc",
        source_kind="correlation",
        entity_key_hash="hash-2",
        entity_type="ip",
        threat_family="DDOS",
        severity="critical",
        urgency="immediate",
        title="Critical DDoS warning",
        summary_text="Shared service pressure observed.",
        tlp="amber",
        classification="RESTRICTED",
        status="open",
        source_partner_ids=["cbk-ke", "ke-cirt"],
        target_partner_ids=["cbk-ke", "ke-cirt"],
        first_seen=now - timedelta(minutes=25),
        last_seen=now - timedelta(minutes=1),
        correlation_count=2,
        max_risk=0.98,
        avg_risk=0.95,
        max_chain_score=0.66,
        risk_flags=["DDOS_ALERT_SERVICE"],
        recommended_actions=["Review WAF posture."],
        metadata_json={},
    )
    acks = [
        SimpleNamespace(
            warning_id=warning_id,
            partner_id="cbk-ke",
            status="received",
            acknowledged_at=now,
            detail_json={"ticket": "CBK-1"},
        ),
        SimpleNamespace(
            warning_id=warning_id,
            partner_id="ke-cirt",
            status="actioned",
            acknowledged_at=now,
            detail_json={"ticket": "KECIRT-1"},
        ),
    ]
    db = _FakeDB(
        query_rows={
            federation.FederationWarning: [warning],
            federation.FederationWarningAck: acks,
        }
    )

    out = federation.list_warnings(status=None, partner_id=None, limit=100, db=db)

    assert out["total_found"] == 1
    row = out["warnings"][0]
    assert row["source_partner_ids"] == ["cbk-ke", "ke-cirt"]
    assert row["target_partner_ids"] == ["cbk-ke", "ke-cirt"]
    assert len(row["acknowledgements"]) == 2

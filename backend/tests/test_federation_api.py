from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.api import federation


class _FakeQuery:
    def __init__(self, rows):
        self.rows = rows

    def order_by(self, *args, **kwargs):  # noqa: ANN002, ARG002
        return self

    def all(self):
        return self.rows


class _FakeDB:
    def __init__(self, *, partners=None, rows=None):
        self.partners = partners or []
        self.rows = rows or []

    def query(self, model):  # noqa: ANN001, ARG002
        return _FakeQuery(self.partners)

    def execute(self, stmt, params):  # noqa: ANN001, ARG002
        return SimpleNamespace(fetchall=lambda: self.rows)


def test_list_partners_derives_online_status_and_heartbeat_fields(monkeypatch):
    now = datetime(2026, 3, 24, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(federation, "utcnow", lambda: now)
    partner = SimpleNamespace(
        partner_id="safaricom-ke",
        partner_name="Safaricom PLC",
        partner_type="telco",
        last_seen=now - timedelta(seconds=120),
        last_pattern_at=now - timedelta(minutes=5),
        total_patterns=12,
        is_active=True,
        registered_at=now - timedelta(days=1),
        metadata_json={
            "edge_status": {
                "last_heartbeat_at": now.isoformat(),
                "agent_version": "1.0.0",
                "model_version": "cyber-gnn-v2",
                "data_source": "demo",
                "hub_reachable": True,
                "capabilities": ["local_gnn"],
                "last_run_status": "ok",
                "last_publish_status": "ok",
                "run_count": 7,
            }
        },
    )

    out = federation.list_partners(db=_FakeDB(partners=[partner]))

    assert len(out) == 1
    assert out[0]["status"] == "online"
    assert out[0]["agent_version"] == "1.0.0"
    assert out[0]["model_version"] == "cyber-gnn-v2"


def test_cross_partner_correlations_formats_rows(monkeypatch):
    now = datetime(2026, 3, 24, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(federation, "utcnow", lambda: now)
    rows = [
        (
            "abc123hash",
            "phone_h",
            ["cbk-ke", "safaricom-ke"],
            2,
            0.93,
            0.88,
            ["SIM_SWAP"],
            ["cross_agency_correlation"],
            0.81,
            now,
            3,
        )
    ]

    out = federation.cross_partner_correlations(
        hours=1,
        min_risk=0.7,
        min_partners=2,
        limit=10,
        db=_FakeDB(rows=rows),
    )

    assert out["total_found"] == 1
    corr = out["correlations"][0]
    assert corr["entity_key_hash"] == "abc123hash"
    assert corr["partner_count"] == 2
    assert corr["threat_level"] == "MEDIUM"
    assert corr["fraud_families"] == ["SIM_SWAP"]

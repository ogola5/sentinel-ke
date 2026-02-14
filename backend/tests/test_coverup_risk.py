from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.economy.coverup import (
    CoverupEventView,
    build_alert_key,
    build_coverup_candidates,
    score_coverup_events,
)


def _ts(hour_delta: int = 0) -> datetime:
    return datetime(2026, 2, 14, 12, 0, tzinfo=timezone.utc) + timedelta(hours=hour_delta)


def test_score_coverup_events_high_when_tamper_and_destruction_present():
    events = [
        CoverupEventView(
            event_hash="h1",
            event_type="DB_AUDIT_EVENT",
            occurred_at=_ts(-2),
            source_id="src-a",
            anchors={"service_id": "pg-primary-01"},
            payload={
                "statement_type": "COPY",
                "row_count": 20000,
                "reason_codes": ["high_impact_db_statement", "audit_config_changed"],
            },
        ),
        CoverupEventView(
            event_hash="h2",
            event_type="FILE_INTEGRITY_EVENT",
            occurred_at=_ts(-1),
            source_id="src-a",
            anchors={"service_id": "pg-primary-01", "endpoint": "/var/backups/ifmis/ledger.sql"},
            payload={
                "action": "deleted",
                "is_critical_path": True,
                "file_path": "/var/backups/ifmis/ledger.sql",
                "reason_codes": ["critical_path_mutation"],
            },
        ),
        CoverupEventView(
            event_hash="h3",
            event_type="DFIR_FINDING_EVENT",
            occurred_at=_ts(0),
            source_id="src-a",
            anchors={"service_id": "pg-primary-01"},
            payload={
                "finding_type": "eventlog_cleared",
                "reason_codes": ["log_tamper_signal"],
                "severity": "high",
            },
        ),
    ]

    scored = score_coverup_events(events)
    assert scored.score >= 0.7
    assert scored.severity in {"high", "critical"}
    assert "audit_tamper_signal_detected" in scored.reason_codes
    assert "destruction_signal_detected" in scored.reason_codes


def test_build_alert_key_is_stable():
    window_end = datetime(2026, 2, 14, 10, 0, tzinfo=timezone.utc)
    k1 = build_alert_key(target_type="service", target_id="pg-primary-01", window_end=window_end)
    k2 = build_alert_key(target_type="service", target_id="pg-primary-01", window_end=window_end)
    assert k1 == k2
    assert len(k1) == 48


def test_build_coverup_candidates_groups_per_target():
    events = [
        CoverupEventView(
            event_hash="a1",
            event_type="DB_AUDIT_EVENT",
            occurred_at=_ts(-3),
            source_id="src-a",
            anchors={"service_id": "svc-a"},
            payload={"statement_type": "COPY", "reason_codes": ["high_impact_db_statement"]},
        ),
        CoverupEventView(
            event_hash="a2",
            event_type="FILE_INTEGRITY_EVENT",
            occurred_at=_ts(-2),
            source_id="src-a",
            anchors={"service_id": "svc-a", "endpoint": "/var/backups/a.log"},
            payload={"action": "deleted", "is_critical_path": True, "file_path": "/var/backups/a.log"},
        ),
        CoverupEventView(
            event_hash="b1",
            event_type="DFIR_FINDING_EVENT",
            occurred_at=_ts(-1),
            source_id="src-b",
            anchors={"service_id": "svc-b"},
            payload={"finding_type": "eventlog_cleared", "reason_codes": ["log_tamper_signal"]},
        ),
        CoverupEventView(
            event_hash="b2",
            event_type="DB_AUDIT_EVENT",
            occurred_at=_ts(0),
            source_id="src-b",
            anchors={"service_id": "svc-b"},
            payload={"statement_type": "ALTER SYSTEM", "reason_codes": ["audit_config_changed"]},
        ),
    ]
    out = build_coverup_candidates(
        events,
        window_start=datetime(2026, 2, 13, 10, 0, tzinfo=timezone.utc),
        window_end=datetime(2026, 2, 14, 10, 0, tzinfo=timezone.utc),
        min_score=0.30,
    )
    targets = {(c.target_type, c.target_id) for c in out}
    assert ("service", "svc-a") in targets
    assert ("service", "svc-b") in targets

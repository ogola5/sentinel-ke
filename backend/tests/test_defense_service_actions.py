from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.defense.service import DefenseService


def _service() -> DefenseService:
    return DefenseService(db=object())


def _original_block(minutes_ago: int = 15):
    return SimpleNamespace(
        id="0e9b5506-6b8f-4d01-8508-1f8e4c4d2b57",
        run_id="9f2a24ca-3ec0-4a38-9552-f2f35c0d9f88",
        executed_at=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago),
    )


def test_rollback_block_ip_fails_when_original_action_missing(monkeypatch):
    svc = _service()
    monkeypatch.setattr(
        DefenseService,
        "_latest_executed_block_ip_action",
        lambda self, *, section_code, target: None,
    )

    status, details = svc._execute_single_action(
        action_type="rollback_block_ip",
        target="41.90.0.1",
        details={},
        section_code="telecom",
    )

    assert status == "failed"
    assert details["error"] == "no_block_ip_action_found"


def test_rollback_block_ip_enforces_time_window(monkeypatch):
    svc = _service()
    monkeypatch.setattr("app.defense.service.settings.defense_rollback_window_minutes", 60)
    monkeypatch.setattr(
        DefenseService,
        "_latest_executed_block_ip_action",
        lambda self, *, section_code, target: _original_block(minutes_ago=90),
    )

    status, details = svc._execute_single_action(
        action_type="rollback_block_ip",
        target="41.90.0.2",
        details={},
        section_code="telecom",
    )

    assert status == "failed"
    assert details["error"] == "rollback_window_expired"
    assert details["rollback_window_minutes"] == 60


def test_rollback_block_ip_prevents_duplicate_rollback(monkeypatch):
    svc = _service()
    monkeypatch.setattr("app.defense.service.settings.defense_rollback_window_minutes", 240)
    monkeypatch.setattr(
        DefenseService,
        "_latest_executed_block_ip_action",
        lambda self, *, section_code, target: _original_block(minutes_ago=20),
    )
    monkeypatch.setattr(
        DefenseService,
        "_rollback_already_executed",
        lambda self, *, section_code, target, rollback_of_action_id: True,
    )

    status, details = svc._execute_single_action(
        action_type="rollback_block_ip",
        target="41.90.0.3",
        details={},
        section_code="telecom",
    )

    assert status == "failed"
    assert details["error"] == "already_rolled_back"


def test_rollback_block_ip_dispatches_unblock_ip(monkeypatch):
    svc = _service()
    monkeypatch.setattr("app.defense.service.settings.defense_rollback_window_minutes", 240)
    monkeypatch.setattr(
        DefenseService,
        "_latest_executed_block_ip_action",
        lambda self, *, section_code, target: _original_block(minutes_ago=10),
    )
    monkeypatch.setattr(
        DefenseService,
        "_rollback_already_executed",
        lambda self, *, section_code, target, rollback_of_action_id: False,
    )
    monkeypatch.setattr(
        "app.defense.service.dispatch_containment_action",
        lambda *, db, action_type, target, section_code: ("delivered", {"delivery_id": "d-1"}),
    )

    status, details = svc._execute_single_action(
        action_type="rollback_block_ip",
        target="41.90.0.4",
        details={"rollback_window_minutes": 30},
        section_code="telecom",
    )

    assert status == "executed"
    assert details["requested_action"] == "rollback_block_ip"
    assert details["dispatched_action"] == "unblock_ip"
    assert details["webhook_status"] == "delivered"
    assert details["delivery_id"] == "d-1"


def test_rollback_block_ip_reports_webhook_failures(monkeypatch):
    svc = _service()
    monkeypatch.setattr("app.defense.service.settings.defense_rollback_window_minutes", 240)
    monkeypatch.setattr(
        DefenseService,
        "_latest_executed_block_ip_action",
        lambda self, *, section_code, target: _original_block(minutes_ago=10),
    )
    monkeypatch.setattr(
        DefenseService,
        "_rollback_already_executed",
        lambda self, *, section_code, target, rollback_of_action_id: False,
    )
    monkeypatch.setattr(
        "app.defense.service.dispatch_containment_action",
        lambda *, db, action_type, target, section_code: ("failed", {"error": "timeout"}),
    )

    status, details = svc._execute_single_action(
        action_type="rollback_block_ip",
        target="41.90.0.5",
        details={},
        section_code="telecom",
    )

    assert status == "failed"
    assert details["webhook_status"] == "failed"
    assert details["dispatched_action"] == "unblock_ip"


def test_rate_limit_service_dispatches_remote_control(monkeypatch):
    svc = _service()
    monkeypatch.setattr(
        "app.defense.service.dispatch_containment_action",
        lambda *, db, action_type, target, section_code: (
            "delivered",
            {"delivery_id": "d-rate", "action_type": action_type, "target": target, "section_code": section_code},
        ),
    )

    status, details = svc._execute_single_action(
        action_type="rate_limit_service",
        target="service_id:kplc-auth",
        details={},
        section_code="telecom",
    )

    assert status == "executed"
    assert details["webhook_status"] == "delivered"
    assert details["delivery_id"] == "d-rate"

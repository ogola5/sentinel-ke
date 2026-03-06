from __future__ import annotations

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.api.defense import execute_incident_actions, snapshot_crypto_posture, upsert_vulnerability
from app.api.deps import AuthPrincipal
from app.defense.schemas import (
    ContainmentActionRequest,
    CryptoSnapshotRequest,
    IncidentRunActionBatchRequest,
    VulnerabilityUpsertRequest,
)


def _section_principal() -> AuthPrincipal:
    return AuthPrincipal(
        principal_type="user",
        actor_id="u-1",
        user_id="u-1",
        username="analyst",
        role="section_commander",
        access_level="section",
        section_code="telecom",
        scopes=["defense.read", "defense.write"],
        mfa_authenticated=True,
        mfa_at="2026-02-24T10:00:00+00:00",
    )


def _central_principal() -> AuthPrincipal:
    return AuthPrincipal(
        principal_type="user",
        actor_id="u-2",
        user_id="u-2",
        username="central",
        role="central_operator",
        access_level="central",
        section_code=None,
        scopes=["defense.read", "defense.write"],
        mfa_authenticated=True,
        mfa_at="2026-02-24T10:00:00+00:00",
    )


def test_upsert_vulnerability_forwards_to_service(monkeypatch):
    captured = {}

    class _Svc:
        def __init__(self, db):
            self.db = db

        def upsert_vulnerability(self, *, payload, principal):
            captured["asset_id"] = payload.asset_id
            captured["section"] = principal.section_code
            return {"status": "ok"}

    monkeypatch.setattr("app.api.defense.DefenseService", _Svc)

    out = upsert_vulnerability(
        payload=VulnerabilityUpsertRequest(asset_id="asset-1", cve_id="CVE-2026-1"),
        principal=_section_principal(),
        db=object(),
    )
    assert out["status"] == "ok"
    assert captured == {"asset_id": "asset-1", "section": "telecom"}


def test_execute_incident_actions_maps_not_found(monkeypatch):
    class _Svc:
        def __init__(self, db):
            self.db = db

        def execute_run_actions(self, *, run_id, payload, principal):
            del run_id, payload, principal
            raise ValueError("incident_run_not_found")

    monkeypatch.setattr("app.api.defense.DefenseService", _Svc)

    request = Request({"type": "http", "method": "POST", "path": "/v1/defense/incidents/runs/x/actions", "headers": []})

    with pytest.raises(HTTPException) as e:
        execute_incident_actions(
            request=request,
            run_id="55f2f2c5-8ab2-4b2f-8904-9e3adf674d58",
            payload=IncidentRunActionBatchRequest(
                actions=[ContainmentActionRequest(action_type="disable_source_key", target="safaricom")]
            ),
            principal=_section_principal(),
            db=object(),
        )
    assert e.value.status_code == 404
    assert e.value.detail == "incident_run_not_found"


def test_snapshot_crypto_posture_forwards_to_service(monkeypatch):
    captured = {}

    class _Svc:
        def __init__(self, db):
            self.db = db

        def snapshot_crypto_posture(self, *, payload, principal):
            captured["section_code"] = payload.section_code
            captured["actor_id"] = principal.actor_id
            return {"snapshot_id": "snap-1"}

    monkeypatch.setattr("app.api.defense.DefenseService", _Svc)

    out = snapshot_crypto_posture(
        payload=CryptoSnapshotRequest(details={"note": "daily"}, section_code="revenue"),
        principal=_central_principal(),
        db=object(),
    )
    assert out["snapshot_id"] == "snap-1"
    assert captured == {"section_code": "revenue", "actor_id": "u-2"}

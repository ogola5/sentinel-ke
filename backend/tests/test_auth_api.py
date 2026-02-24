from __future__ import annotations

from types import SimpleNamespace

from app.api.auth import create_user, login, me
from app.api.deps import AuthPrincipal
from app.auth.schemas import AuthLoginRequest, AuthUserCreateRequest


def test_login_forwards_request_context(monkeypatch):
    captured = {}

    class _Svc:
        def __init__(self, db):
            self.db = db

        def login(self, payload, *, ip_address, user_agent):
            captured["username"] = payload.username
            captured["ip"] = ip_address
            captured["ua"] = user_agent
            return {"status": "ok"}

    monkeypatch.setattr("app.api.auth.AuthService", _Svc)

    payload = AuthLoginRequest(username="alice", password="StrongPass!2026")
    request = SimpleNamespace(client=SimpleNamespace(host="10.10.10.10"), headers={"user-agent": "pytest"})

    out = login(payload=payload, request=request, db=object())
    assert out["status"] == "ok"
    assert captured == {"username": "alice", "ip": "10.10.10.10", "ua": "pytest"}


def test_create_user_passes_actor_identity(monkeypatch):
    captured = {}

    class _Svc:
        def __init__(self, db):
            self.db = db

        def create_user(self, payload, *, actor_id):
            captured["username"] = payload.username
            captured["actor_id"] = actor_id
            return {"username": payload.username, "created_by": actor_id}

    monkeypatch.setattr("app.api.auth.AuthService", _Svc)

    principal = AuthPrincipal(
        principal_type="user",
        actor_id="central-1",
        user_id="central-1",
        username="central",
        role="admin",
        access_level="central",
        section_code=None,
        scopes=["*"],
    )
    payload = AuthUserCreateRequest(
        username="new-user",
        password="VeryStrongPassword#2026",
        role="analyst",
        access_level="section",
        section_code="ops-east",
        scopes=["events.read"],
    )

    out = create_user(payload=payload, principal=principal, db=object())
    assert out["created_by"] == "central-1"
    assert captured["username"] == "new-user"


def test_me_returns_principal_payload():
    principal = AuthPrincipal(
        principal_type="user",
        actor_id="u-1",
        user_id="u-1",
        username="analyst-a",
        role="analyst",
        access_level="section",
        section_code="ops-east",
        scopes=["events.read"],
    )
    out = me(principal=principal)
    assert out["username"] == "analyst-a"
    assert out["access_level"] == "section"

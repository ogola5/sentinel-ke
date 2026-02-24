from __future__ import annotations

import pytest

from app.auth.service import AuthService


def test_enforce_scope_rules_defaults_to_allowed():
    svc = AuthService(db=None)
    out = svc._enforce_scope_rules(  # noqa: SLF001
        requested_scopes=[],
        allowed_scopes=["events.read", "ai.read"],
    )
    assert out == ["events.read", "ai.read"]


def test_enforce_scope_rules_rejects_unknown_scope():
    svc = AuthService(db=None)
    with pytest.raises(ValueError) as e:
        svc._enforce_scope_rules(  # noqa: SLF001
            requested_scopes=["events.read", "legal.write"],
            allowed_scopes=["events.read"],
        )
    assert str(e.value) == "scope_not_allowed_by_role_policy"

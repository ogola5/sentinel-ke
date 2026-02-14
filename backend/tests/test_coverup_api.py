from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.api.economy_coverup import run_coverup


def test_run_coverup_requires_legal_grant_token():
    with pytest.raises(HTTPException) as e:
        run_coverup(
            window_days=30,
            min_score=0.45,
            x_legal_grant_token=None,
            x_legal_target="economy:coverup",
            db=object(),
        )
    assert e.value.status_code == 401
    assert e.value.detail == "missing_legal_grant_token"


def test_run_coverup_authorized_flow(monkeypatch):
    class _LegalSvc:
        def __init__(self, db):
            self.db = db

        def verify_grant_token(self, **kwargs):
            assert kwargs["action_type"] == "coverup_risk_scan"
            return {"grant_id": "g-1", "status": "allow"}

    def _run_coverup_detection(db, *, window_days: int, min_score: float):
        assert window_days == 30
        assert min_score == 0.55
        return {"events": 10, "candidates": 3, "created": 3, "updated": 0}

    monkeypatch.setattr("app.api.economy_coverup.LegalAuthorizationService", _LegalSvc)
    monkeypatch.setattr("app.api.economy_coverup.run_coverup_detection", _run_coverup_detection)

    out = run_coverup(
        window_days=30,
        min_score=0.55,
        x_legal_grant_token="token-1",
        x_legal_target="economy:coverup",
        db=object(),
    )
    assert out["created"] == 3
    assert out["legal_authorization"]["status"] == "allow"

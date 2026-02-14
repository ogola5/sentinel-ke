from __future__ import annotations

from app.api.legal import get_evidence_anchor, refresh_evidence_anchor


def test_get_evidence_anchor_success(monkeypatch):
    class _Svc:
        def __init__(self, db):
            self.db = db

        def get_evidence_anchor(self, bundle_id: str):
            assert bundle_id == "b-1"
            return {"bundle_id": bundle_id, "anchor_status": "anchored"}

    monkeypatch.setattr("app.api.legal.LegalAuthorizationService", _Svc)
    out = get_evidence_anchor(bundle_id="b-1", db=object())
    assert out["anchor_status"] == "anchored"


def test_refresh_evidence_anchor_success(monkeypatch):
    class _Svc:
        def __init__(self, db):
            self.db = db

        def refresh_evidence_anchor(self, *, bundle_id: str, actor_id: str):
            assert bundle_id == "b-2"
            assert actor_id == "api"
            return {"bundle_id": bundle_id, "anchor_status": "partial"}

    monkeypatch.setattr("app.api.legal.LegalAuthorizationService", _Svc)
    out = refresh_evidence_anchor(bundle_id="b-2", actor_id="api", db=object())
    assert out["anchor_status"] == "partial"

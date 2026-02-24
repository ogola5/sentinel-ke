from app.api.legal import verify_grant


def test_verify_grant_passes_model_scope_params(monkeypatch):
    captured = {}

    class _Svc:
        def __init__(self, db):
            self.db = db

        def verify_grant_token(self, **kwargs):
            captured.update(kwargs)
            return {"status": "allow", "grant_id": "g1", "order_id": "o1", "action_type": "x", "target": "y", "valid_until": "z"}

    monkeypatch.setattr("app.api.legal.LegalAuthorizationService", _Svc)

    out = verify_grant(
        action_type="economic_leakage_scan",
        target="economy:procurement",
        model_action="risk_inference",
        model_version="gnn-sage-v2",
        x_legal_grant_token="token-1",
        mark_used=False,
        actor_id="api",
        db=object(),
    )

    assert out["status"] == "allow"
    assert captured["model_action"] == "risk_inference"
    assert captured["model_version"] == "gnn-sage-v2"

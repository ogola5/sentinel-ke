from app.legal.service import _model_scope_allowed


def test_model_scope_allowed_with_matching_action_and_version():
    scope = {
        "allowed_model_actions": ["risk_*"],
        "allowed_model_versions": ["gnn-sage-v2"],
    }
    assert _model_scope_allowed(
        scope=scope,
        model_action="risk_inference",
        model_version="gnn-sage-v2",
    )


def test_model_scope_denies_mismatch():
    scope = {
        "allowed_model_actions": ["risk_*"],
        "allowed_model_versions": ["gnn-sage-v2"],
    }
    assert not _model_scope_allowed(
        scope=scope,
        model_action="expand_graph",
        model_version="gnn-sage-v1",
    )


def test_model_scope_allows_when_scope_empty():
    assert _model_scope_allowed(scope={}, model_action="anything", model_version="v1")

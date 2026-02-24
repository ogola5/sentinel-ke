from app.analytics.layer3.ai_inference_worker import _select_model_version


def test_select_model_version_single_mode_uses_active():
    out = _select_model_version(
        rollout={
            "rollout_mode": "single",
            "active_model_version": "v2",
            "shadow_model_version": "v1",
            "canary_ratio": 0.2,
        },
        entity_key="service_id:abc",
    )
    assert out == "v2"


def test_select_model_version_canary_uses_shadow_for_some_entities():
    rollout = {
        "rollout_mode": "canary",
        "active_model_version": "v2",
        "shadow_model_version": "v1",
        "canary_ratio": 1.0,
    }
    out = _select_model_version(rollout=rollout, entity_key="service_id:any")
    assert out == "v1"

from app.analytics.layer3 import component_campaign_worker, decision_fusion_worker, drift_worker, path_risk_worker
from app.analytics.layer3.post_prediction_pipeline import run_post_prediction_pipeline


class _DummyDB:
    pass


def test_post_prediction_pipeline_runs_for_corruption(monkeypatch):
    monkeypatch.setattr(component_campaign_worker, "run_once", lambda **kwargs: {
        "campaigns_created": 1,
        "campaigns_updated": 0,
        "entities_upserted": 3,
        "components_considered": 1,
        "indicators_created": 1,
        "indicators_updated": 0,
    })
    monkeypatch.setattr(path_risk_worker, "run_once", lambda **kwargs: 4)
    monkeypatch.setattr(decision_fusion_worker, "run_once", lambda **kwargs: 2)
    monkeypatch.setattr(drift_worker, "run_once", lambda **kwargs: {"status": "ok", "upserted": 1})

    out = run_post_prediction_pipeline(
        db=_DummyDB(),
        prediction_type="corruption_risk",
        window_key="Wcorruption",
        window_end=None,
        model_version="corruption-gnn-v1",
        seed_legal_bundles=True,
    )

    assert out["component_campaigns"]["campaigns_created"] == 1
    assert out["path_scores_upserted"] == 4
    assert out["decision_fusions_upserted"] == 2
    assert out["drift_status"] == "ok"
    assert out["containment"]["status"] == "not_run"
    assert out["legal_bundle_seed"]["status"] == "not_run"

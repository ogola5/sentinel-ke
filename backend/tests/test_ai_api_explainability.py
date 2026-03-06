from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from app.api.ai import get_explanation, list_predictions


class _FakeQuery:
    def __init__(self, rows):
        self._rows = rows

    def filter(self, *args, **kwargs):
        del args, kwargs
        return self

    def order_by(self, *args, **kwargs):
        del args, kwargs
        return self

    def offset(self, _value: int):
        return self

    def limit(self, _value: int):
        return self

    def all(self):
        return list(self._rows)

    def first(self):
        return self._rows[0] if self._rows else None


class _FakeDB:
    def __init__(self, prediction, explanation):
        self._prediction = prediction
        self._explanation = explanation

    def query(self, model):
        name = getattr(model, "__name__", "")
        if name == "AIPrediction":
            return _FakeQuery([self._prediction])
        if name == "AIExplanation":
            return _FakeQuery([self._explanation])
        return _FakeQuery([])


def _prediction():
    return SimpleNamespace(
        id="pred-1",
        entity_key="ip:41.90.0.10",
        entity_type="ip",
        prediction_type="risk_gnn",
        model_version="gnn-sage-v1",
        window_key="Wmid",
        window_end=datetime(2026, 3, 1, 10, 0, tzinfo=timezone.utc),
        score=92.5,
        confidence=0.91,
        uncertainty=0.08,
        abstained=False,
        kill_chain_stage="impact",
        decision_source="gnn",
        reason_codes=["GNN_RISK_CRITICAL"],
        details_json={
            "explanation_method": "gradient_x_input",
            "feature_attributions": [
                {"feature": "event_count", "score": 0.74},
                {"feature": "source_count", "score": 0.41},
            ],
        },
        created_at=datetime(2026, 3, 1, 10, 1, tzinfo=timezone.utc),
    )


def _explanation():
    return SimpleNamespace(
        prediction_id="pred-1",
        reason_codes=["GNN_RISK_CRITICAL"],
        evidence_hashes=["e1"],
        evidence_paths=["/v1/events/e1"],
        recommended_controls_json=["block ip at perimeter"],
        counterfactual_json={"what_if": "event_count lower"},
        details_json={
            "explanation_method": "gradient_x_input",
            "feature_attributions": [
                {"feature": "event_count", "score": 0.74},
            ],
            "attribution_group_scores": [
                {"group": "volume", "score": 0.66},
            ],
        },
        created_at=datetime(2026, 3, 1, 10, 2, tzinfo=timezone.utc),
    )


def test_get_explanation_includes_model_attribution_fields():
    db = _FakeDB(_prediction(), _explanation())
    out = get_explanation("pred-1", db=db)

    assert out["explanation_method"] == "gradient_x_input"
    assert out["model_based"] is True
    assert out["top_feature"] == "event_count"
    assert out["feature_attributions"][0]["feature"] == "event_count"


def test_list_predictions_exposes_top_feature_and_method():
    db = _FakeDB(_prediction(), _explanation())
    out = list_predictions(pagination={"limit": 10, "offset": 0}, db=db)

    assert len(out["items"]) == 1
    row = out["items"][0]
    assert row["explanation_method"] == "gradient_x_input"
    assert row["top_feature"] == "event_count"

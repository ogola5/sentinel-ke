from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from app.api.ai import gnn_domain_health, latest_gnn_runs
from app.analytics.ai_models import AIPrediction, GNNTrainingRun


class _FakeQuery:
    def __init__(self, rows):
        self._rows = list(rows)

    def filter(self, *expressions):
        rows = list(self._rows)
        for expr in expressions:
            left = getattr(expr, "left", None)
            right = getattr(expr, "right", None)
            key = getattr(left, "key", None)
            value = getattr(right, "value", None)
            if key is None:
                continue
            rows = [row for row in rows if getattr(row, key, None) == value]
        return _FakeQuery(rows)

    def order_by(self, *args, **kwargs):
        del args, kwargs
        return self

    def all(self):
        return list(self._rows)

    def first(self):
        return self._rows[0] if self._rows else None


class _FakeDB:
    def __init__(self, runs, predictions):
        self._runs = list(runs)
        self._predictions = list(predictions)

    def query(self, model):
        if model is GNNTrainingRun:
            return _FakeQuery(self._runs)
        if model is AIPrediction:
            return _FakeQuery(self._predictions)
        return _FakeQuery([])


def _run() -> SimpleNamespace:
    return SimpleNamespace(
        id="run-1",
        model_version="gnn-sage-v1",
        prediction_type="risk_gnn",
        source_backend="neo4j+postgres",
        window_key="Wmid",
        window_end=datetime(2026, 3, 24, 20, 39, tzinfo=timezone.utc),
        node_count=97,
        edge_count=237,
        feature_dim=44,
        positive_count=44,
        epochs=8,
        train_loss=0.71,
        val_loss=0.92,
        auc=0.89,
        precision=1.0,
        recall=0.84,
        f1=0.91,
        artifact_path="/tmp/model.pt",
        params_json={},
        metrics_json={
            "fairness": {"fairness_flag": "PASS"},
            "fairness_gate": {"passed": True},
            "real_data_gate": {"passed": True},
            "operating_metrics": {"precision": 1.0, "recall": 0.84, "f1": 0.91},
            "provenance": {"real_ratio": 1.0},
        },
        created_at=datetime(2026, 3, 26, 9, 0, tzinfo=timezone.utc),
    )


def _prediction(
    entity_key: str,
    *,
    score: float,
    above_threshold: bool,
    abstained: bool,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=f"pred-{entity_key}",
        entity_key=entity_key,
        entity_type="ip",
        prediction_type="risk_gnn",
        model_version="gnn-sage-v1",
        window_key="Wmid",
        window_end=datetime(2026, 3, 25, 19, 0, tzinfo=timezone.utc),
        score=score,
        confidence=0.9,
        uncertainty=0.1,
        abstained=abstained,
        kill_chain_stage="impact",
        decision_source="gnn",
        reason_codes=["TEST"],
        details_json={
            "above_entity_threshold": above_threshold,
            "entity_threshold_score": 75.0,
        },
        created_at=datetime(2026, 3, 26, 10, 0, tzinfo=timezone.utc),
    )


def test_latest_gnn_runs_reports_live_prediction_counts():
    db = _FakeDB(
        runs=[_run()],
        predictions=[
            _prediction("ip:1", score=91.0, above_threshold=True, abstained=False),
            _prediction("ip:2", score=63.0, above_threshold=False, abstained=False),
            _prediction("ip:3", score=88.0, above_threshold=True, abstained=True),
        ],
    )

    out = latest_gnn_runs(prediction_type="risk_gnn", db=db)

    assert len(out["items"]) == 1
    row = out["items"][0]
    assert row["latest_run"]["prediction_type"] == "risk_gnn"
    assert row["latest_live_predictions"]["prediction_count"] == 3
    assert row["latest_live_predictions"]["flagged_count"] == 2
    assert row["latest_live_predictions"]["high_risk_count"] == 1
    assert row["run_prediction_alignment"]["window_matches"] is False
    assert "run_window_differs_from_live_window" in row["status_reasons"]


def test_gnn_domain_health_summarizes_alignment_and_gate_state():
    db = _FakeDB(
        runs=[_run()],
        predictions=[_prediction("ip:1", score=91.0, above_threshold=True, abstained=False)],
    )

    out = gnn_domain_health(prediction_type="risk_gnn", db=db)

    assert len(out["items"]) == 1
    row = out["items"][0]
    assert row["prediction_type"] == "risk_gnn"
    assert row["high_risk_count"] == 1
    assert row["real_data_gate_passed"] is True
    assert row["run_prediction_alignment"]["window_matches"] is False

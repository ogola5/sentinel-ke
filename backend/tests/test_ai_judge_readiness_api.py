from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from app.api.ai import judge_readiness_summary
from app.analytics.ai_models import (
    AIDriftReport,
    AIModelRollout,
    AIPrediction,
    AIRiskThreshold,
    EntityRiskBaseline,
    GNNTrainingRun,
)


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

    def offset(self, value: int):
        return _FakeQuery(self._rows[value:])

    def limit(self, value: int):
        return _FakeQuery(self._rows[:value])


class _FakeDB:
    def __init__(
        self,
        *,
        runs=None,
        predictions=None,
        drifts=None,
        rollouts=None,
        thresholds=None,
        baselines=None,
    ):
        self._rows = {
            GNNTrainingRun: list(runs or []),
            AIPrediction: list(predictions or []),
            AIDriftReport: list(drifts or []),
            AIModelRollout: list(rollouts or []),
            AIRiskThreshold: list(thresholds or []),
            EntityRiskBaseline: list(baselines or []),
        }

    def query(self, model):
        return _FakeQuery(self._rows.get(model, []))


def _run(*, window_end: datetime, model_version: str = "gnn-sage-v1", real_data_gate_passed: bool = True):
    return SimpleNamespace(
        id="run-1",
        model_version=model_version,
        prediction_type="risk_gnn",
        source_backend="neo4j+postgres",
        window_key="Wmid",
        window_end=window_end,
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
            "fairness": {
                "fairness_flag": "PASS",
                "max_positive_rate_disparity": 0.12,
            },
            "fairness_gate": {"passed": True},
            "real_data_gate": {"passed": real_data_gate_passed},
            "operating_metrics": {"precision": 0.93, "recall": 0.81, "f1": 0.87},
            "label_strategy": {"eval_caveat": "Evaluation still depends on weak-label coverage."},
            "evaluation_protocol": {
                "benchmarkable": True,
                "benchmark_reasons": [],
            },
        },
        created_at=datetime(2026, 3, 26, 9, 0, tzinfo=timezone.utc),
    )


def _prediction(
    entity_key: str,
    *,
    window_end: datetime,
    score: float,
    above_threshold: bool,
    abstained: bool,
    model_version: str = "gnn-sage-v1",
):
    return SimpleNamespace(
        id=f"pred-{entity_key}",
        entity_key=entity_key,
        entity_type="ip",
        prediction_type="risk_gnn",
        model_version=model_version,
        window_key="Wmid",
        window_end=window_end,
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


def _drift(*, model_version: str = "gnn-sage-v1", status: str = "warn"):
    return SimpleNamespace(
        model_version=model_version,
        prediction_type="risk_gnn",
        window_key="Wmid",
        window_end=datetime(2026, 3, 25, 20, 0, tzinfo=timezone.utc),
        drift_score=0.41,
        status=status,
        created_at=datetime(2026, 3, 26, 10, 30, tzinfo=timezone.utc),
    )


def _rollout():
    return SimpleNamespace(
        rollout_id="rollout-1",
        prediction_type="risk_gnn",
        active_model_version="gnn-sage-v1",
        shadow_model_version=None,
        rollout_mode="single",
        canary_ratio=0.0,
        status="active",
        created_at=datetime(2026, 3, 26, 8, 0, tzinfo=timezone.utc),
        updated_at=datetime(2026, 3, 26, 10, 45, tzinfo=timezone.utc),
    )


def _threshold(entity_type: str):
    return SimpleNamespace(
        id=f"thr-{entity_type}",
        model_version="gnn-sage-v1",
        prediction_type="risk_gnn",
        entity_type=entity_type,
        window_key="Wmid",
        window_end=datetime(2026, 3, 25, 20, 0, tzinfo=timezone.utc),
        threshold_score=75.0,
        method="f1_weak_label",
        sample_count=120,
        positive_count=12,
        cost_weight=1.0,
        metrics_json={},
        created_at=datetime(2026, 3, 26, 9, 15, tzinfo=timezone.utc),
    )


def _baseline(entity_key: str, *, updated_at: datetime):
    return SimpleNamespace(
        id=f"base-{entity_key}",
        entity_key=entity_key,
        entity_type="ip",
        window_key="Wmid",
        baseline_score=42.0,
        baseline_std=7.5,
        sample_count=15,
        last_window_end=datetime(2026, 3, 25, 20, 0, tzinfo=timezone.utc),
        updated_at=updated_at,
    )


def test_judge_readiness_summary_exposes_lane_evidence_and_pointers():
    db = _FakeDB(
        runs=[_run(window_end=datetime(2026, 3, 24, 20, 39, tzinfo=timezone.utc))],
        predictions=[
            _prediction(
                "ip:1",
                window_end=datetime(2026, 3, 25, 19, 0, tzinfo=timezone.utc),
                score=91.0,
                above_threshold=True,
                abstained=False,
            ),
            _prediction(
                "ip:2",
                window_end=datetime(2026, 3, 25, 19, 0, tzinfo=timezone.utc),
                score=63.0,
                above_threshold=False,
                abstained=True,
            ),
        ],
        drifts=[_drift(status="warn")],
        rollouts=[_rollout()],
        thresholds=[_threshold("ip"), _threshold("account")],
        baselines=[
            _baseline("ip:1", updated_at=datetime(2026, 3, 26, 8, 30, tzinfo=timezone.utc)),
            _baseline("ip:2", updated_at=datetime(2026, 3, 26, 8, 0, tzinfo=timezone.utc)),
        ],
    )

    out = judge_readiness_summary(prediction_type="risk_gnn", db=db)

    assert out["status"] == "warn"
    assert out["headline"] == "Judge-facing readiness evidence is available with caveats."
    lane = out["lanes"][0]
    assert lane["latest_run"]["model_version"] == "gnn-sage-v1"
    assert lane["live_prediction_alignment"]["prediction_count"] == 2
    assert lane["live_prediction_alignment"]["abstained_count"] == 1
    assert lane["kpi_evidence"]["thresholds"]["path"] == "/v1/ai/thresholds?prediction_type=risk_gnn&model_version=gnn-sage-v1"
    assert lane["kpi_evidence"]["thresholds"]["entity_type_count"] == 2
    assert lane["kpi_evidence"]["baselines"]["path"] == "/v1/ai/baselines?window_key=Wmid"
    assert lane["kpi_evidence"]["baselines"]["coverage_count"] == 2
    assert lane["robustness_trust_signals"]["drift_status"] == "warn"
    assert lane["robustness_trust_signals"]["rollout_status"] == "active"
    assert "Live predictions and the latest recorded run are from different windows." in lane["honest_caveats"]
    assert "Evaluation still depends on weak-label coverage." in lane["honest_caveats"]


def test_judge_readiness_summary_calls_out_missing_kpi_support():
    run = _run(
        window_end=datetime(2026, 3, 25, 20, 0, tzinfo=timezone.utc),
        real_data_gate_passed=False,
    )
    run.metrics_json["fairness_gate"] = {"passed": False}
    run.metrics_json["fairness"]["max_positive_rate_disparity"] = 0.81
    run.metrics_json["evaluation_protocol"] = {
        "benchmarkable": False,
        "benchmark_reasons": ["insufficient_negative_examples"],
    }
    db = _FakeDB(
        runs=[run],
        predictions=[
            _prediction(
                "ip:1",
                window_end=datetime(2026, 3, 25, 20, 0, tzinfo=timezone.utc),
                score=88.0,
                above_threshold=True,
                abstained=False,
            )
        ],
    )

    out = judge_readiness_summary(prediction_type="risk_gnn", db=db)

    assert out["status"] == "warn"
    lane = out["lanes"][0]
    assert lane["robustness_trust_signals"]["fairness_blocked"] is True
    assert lane["robustness_trust_signals"]["real_data_gate_passed"] is False
    assert lane["robustness_trust_signals"]["benchmarkable"] is False
    assert "The latest run is currently blocked by the fairness guard." in lane["honest_caveats"]
    assert "The latest run did not pass the real-data gate." in lane["honest_caveats"]
    assert "Benchmark readiness is not yet met: insufficient_negative_examples." in lane["honest_caveats"]
    assert "No threshold snapshot is recorded for this lane and model yet." in lane["honest_caveats"]
    assert "No entity baselines are recorded for window Wmid." in lane["honest_caveats"]

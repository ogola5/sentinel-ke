from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core import metrics_store
from app.ledger.db import get_db
from app.ledger.models import EventLog
from app.graph.models import GraphDeltaLog
from app.analytics.anomalies import AnomalyScore
from app.analytics.mitigations import Mitigation
from app.analytics.ai_models import AIDriftReport, AIFeedbackLabel, AIModelRollout, AIDecisionFusion


router = APIRouter(prefix="/v1/metrics", tags=["metrics"])


@router.get("")
def metrics(db: Session = Depends(get_db)):
    """
    Lightweight operational metrics for demo/debug (not Prometheus grade).
    """
    event_count = db.query(EventLog).count()
    delta_count = db.query(GraphDeltaLog).count()
    anomaly_count = db.query(AnomalyScore).count()
    mitigation_count = db.query(Mitigation).count()
    drift_count = db.query(AIDriftReport).count()
    feedback_count = db.query(AIFeedbackLabel).count()
    rollout_count = db.query(AIModelRollout).count()
    decision_fusion_count = db.query(AIDecisionFusion).count()
    perf = metrics_store.snapshot()
    return {
        # DB entity counts
        "events": event_count,
        "graph_deltas": delta_count,
        "anomalies": anomaly_count,
        "mitigations": mitigation_count,
        "ai_drift_reports": drift_count,
        "ai_feedback_labels": feedback_count,
        "ai_rollouts": rollout_count,
        "ai_decision_fusions": decision_fusion_count,
        # Runtime performance
        "uptime_seconds": perf["uptime_seconds"],
        "request_count": perf["request_count"],
        "error_count": perf["error_count"],
        "latency_sample_size": perf["sample_size"],
        "latency_p50_ms": perf["latency_p50_ms"],
        "latency_p95_ms": perf["latency_p95_ms"],
        "latency_p99_ms": perf["latency_p99_ms"],
    }

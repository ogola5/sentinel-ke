from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.ledger.db import get_db
from app.ledger.models import EventLog
from app.graph.models import GraphDeltaLog
from app.analytics.anomalies import AnomalyScore
from app.analytics.mitigations import Mitigation


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
    return {
        "events": event_count,
        "graph_deltas": delta_count,
        "anomalies": anomaly_count,
        "mitigations": mitigation_count,
    }

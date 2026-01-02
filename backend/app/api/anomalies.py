from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db, pagination_params
from app.analytics.anomalies import AnomalyScore

router = APIRouter(prefix="/v1/anomalies", tags=["anomalies"])


@router.get("")
def list_anomalies(
    pagination: dict = Depends(pagination_params),
    service_id: str | None = Query(default=None),
    endpoint: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    q = db.query(AnomalyScore)
    if service_id:
        q = q.filter(AnomalyScore.service_id == service_id)
    if endpoint:
        q = q.filter(AnomalyScore.endpoint == endpoint)

    rows = (
        q.order_by(AnomalyScore.window_end.desc(), AnomalyScore.score.desc())
        .offset(pagination["offset"])
        .limit(pagination["limit"])
        .all()
    )

    return {
        "limit": pagination["limit"],
        "offset": pagination["offset"],
        "items": [
            {
                "id": str(r.id),
                "service_id": r.service_id,
                "endpoint": r.endpoint,
                "window_start": r.window_start.isoformat(),
                "window_end": r.window_end.isoformat(),
                "score": r.score,
                "reason_codes": r.reason_codes,
                "indicators": r.indicators,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ]
    }

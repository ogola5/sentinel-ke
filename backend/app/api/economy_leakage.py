from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db, pagination_params
from app.analytics.economic_leakage import LeakageAlert
from app.economy.leakage import run_leakage_detection

router = APIRouter(prefix="/v1/economy/leakage", tags=["economy"])


@router.post("/run")
def run_leakage(
    window_days: int = Query(default=30, ge=1, le=365),
    db: Session = Depends(get_db),
):
    """
    Run leakage detection against recent procurement anomaly records.
    """
    return run_leakage_detection(db, window_days=window_days)


@router.get("/alerts")
def list_leakage_alerts(
    pagination: dict = Depends(pagination_params),
    detector_type: Optional[str] = Query(default=None),
    sector: Optional[str] = Query(default=None),
    agency: Optional[str] = Query(default=None),
    vendor_id: Optional[str] = Query(default=None),
    severity: Optional[str] = Query(default=None),
    min_score: Optional[float] = Query(default=None, ge=0.0, le=1.0),
    db: Session = Depends(get_db),
):
    q = db.query(LeakageAlert)
    if detector_type:
        q = q.filter(LeakageAlert.detector_type == detector_type)
    if sector:
        q = q.filter(LeakageAlert.sector == sector)
    if agency:
        q = q.filter(LeakageAlert.agency == agency)
    if vendor_id:
        q = q.filter(LeakageAlert.vendor_id == vendor_id)
    if severity:
        q = q.filter(LeakageAlert.severity == severity)
    if min_score is not None:
        q = q.filter(LeakageAlert.score >= min_score)

    rows = (
        q.order_by(LeakageAlert.window_end.desc(), LeakageAlert.score.desc())
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
                "signal_id": str(r.signal_id) if r.signal_id else None,
                "alert_key": r.alert_key,
                "detector_type": r.detector_type,
                "sector": r.sector,
                "agency": r.agency,
                "vendor_id": r.vendor_id,
                "project_id": r.project_id,
                "score": r.score,
                "severity": r.severity,
                "reason_codes": r.reason_codes,
                "indicators": r.indicators,
                "evidence": r.evidence,
                "window_start": r.window_start.isoformat(),
                "window_end": r.window_end.isoformat(),
                "created_at": r.created_at.isoformat(),
                "updated_at": r.updated_at.isoformat(),
            }
            for r in rows
        ],
    }


@router.get("/summary")
def leakage_summary(
    window_days: int = Query(default=30, ge=1, le=365),
    db: Session = Depends(get_db),
):
    end = datetime.now(timezone.utc)
    start = end.replace(microsecond=0) - timedelta(days=window_days)

    rows = (
        db.query(LeakageAlert)
        .filter(LeakageAlert.window_end >= start)
        .filter(LeakageAlert.window_end <= end)
        .all()
    )

    by_detector: dict[str, int] = {}
    by_severity: dict[str, int] = {}
    suspected_amount = 0.0
    top_vendors: dict[str, float] = {}

    for r in rows:
        by_detector[r.detector_type] = by_detector.get(r.detector_type, 0) + 1
        by_severity[r.severity] = by_severity.get(r.severity, 0) + 1
        amt = float((r.indicators or {}).get("suspected_amount") or 0.0)
        suspected_amount += amt
        if r.vendor_id:
            top_vendors[r.vendor_id] = top_vendors.get(r.vendor_id, 0.0) + amt

    top_vendor_items = sorted(top_vendors.items(), key=lambda x: x[1], reverse=True)[:10]

    return {
        "window_days": window_days,
        "total_alerts": len(rows),
        "by_detector": by_detector,
        "by_severity": by_severity,
        "suspected_amount_total": round(suspected_amount, 2),
        "top_vendors_by_suspected_amount": [
            {"vendor_id": vendor_id, "suspected_amount": round(amount, 2)}
            for vendor_id, amount in top_vendor_items
        ],
    }

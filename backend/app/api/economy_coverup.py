from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db, pagination_params
from app.analytics.coverup_risk import CoverupRiskAlert
from app.economy.coverup import run_coverup_detection
from app.legal.service import LegalAuthorizationService

router = APIRouter(prefix="/v1/economy/coverup", tags=["economy"])


@router.post("/run")
def run_coverup(
    window_days: int = Query(default=30, ge=1, le=365),
    min_score: float = Query(default=0.45, ge=0.0, le=1.0),
    x_legal_grant_token: str | None = Header(default=None, alias="X-Legal-Grant-Token"),
    x_legal_target: str | None = Header(default="economy:coverup"),
    db: Session = Depends(get_db),
):
    if not x_legal_grant_token:
        raise HTTPException(status_code=401, detail="missing_legal_grant_token")
    try:
        auth = LegalAuthorizationService(db).verify_grant_token(
            execution_token=x_legal_grant_token,
            action_type="coverup_risk_scan",
            target=x_legal_target or "economy:coverup",
            actor_id="coverup_risk_api",
        )
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))

    out = run_coverup_detection(db, window_days=window_days, min_score=min_score)
    out["legal_authorization"] = auth
    return out


@router.get("/alerts")
def list_coverup_alerts(
    pagination: dict = Depends(pagination_params),
    target_type: Optional[str] = Query(default=None),
    target_id: Optional[str] = Query(default=None),
    severity: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    min_score: Optional[float] = Query(default=None, ge=0.0, le=1.0),
    db: Session = Depends(get_db),
):
    q = db.query(CoverupRiskAlert)
    if target_type:
        q = q.filter(CoverupRiskAlert.target_type == target_type)
    if target_id:
        q = q.filter(CoverupRiskAlert.target_id == target_id)
    if severity:
        q = q.filter(CoverupRiskAlert.severity == severity)
    if status:
        q = q.filter(CoverupRiskAlert.status == status)
    if min_score is not None:
        q = q.filter(CoverupRiskAlert.score >= min_score)

    rows = (
        q.order_by(CoverupRiskAlert.window_end.desc(), CoverupRiskAlert.score.desc())
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
                "target_type": r.target_type,
                "target_id": r.target_id,
                "score": r.score,
                "severity": r.severity,
                "status": r.status,
                "reason_codes": r.reason_codes,
                "indicators": r.indicators,
                "evidence_hashes": r.evidence_hashes,
                "window_start": r.window_start.isoformat(),
                "window_end": r.window_end.isoformat(),
                "created_at": r.created_at.isoformat(),
                "updated_at": r.updated_at.isoformat(),
            }
            for r in rows
        ],
    }


@router.get("/summary")
def coverup_summary(
    window_days: int = Query(default=30, ge=1, le=365),
    db: Session = Depends(get_db),
):
    end = datetime.now(timezone.utc)
    start = end.replace(microsecond=0) - timedelta(days=window_days)

    rows = (
        db.query(CoverupRiskAlert)
        .filter(CoverupRiskAlert.window_end >= start)
        .filter(CoverupRiskAlert.window_end <= end)
        .all()
    )

    by_severity: dict[str, int] = {}
    by_target_type: dict[str, int] = {}
    top_targets: dict[str, float] = {}

    for r in rows:
        by_severity[r.severity] = by_severity.get(r.severity, 0) + 1
        by_target_type[r.target_type] = by_target_type.get(r.target_type, 0) + 1
        key = f"{r.target_type}:{r.target_id}"
        top_targets[key] = max(top_targets.get(key, 0.0), float(r.score))

    top_items = sorted(top_targets.items(), key=lambda x: x[1], reverse=True)[:10]
    return {
        "window_days": window_days,
        "total_alerts": len(rows),
        "by_severity": by_severity,
        "by_target_type": by_target_type,
        "top_targets": [
            {"target": target, "max_score": round(score, 4)}
            for target, score in top_items
        ],
    }

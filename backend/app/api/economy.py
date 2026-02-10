from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db, pagination_params
from app.analytics.economics import EconomicSignal, ProcurementAnomaly
from app.economy.schemas import EconomicSignalIn, ProcurementRecord
from app.economy.scoring import score_procurement, severity_from_score

router = APIRouter(prefix="/v1/economy", tags=["economy"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


@router.post("/procurement/analyze")
def analyze_procurement(
    record: ProcurementRecord,
    db: Session = Depends(get_db),
):
    """
    Score a procurement record and persist a normalized economic signal.
    """

    scored = score_procurement(record)
    occurred_at = record.occurred_at or _now()

    evidence = {
        "tender_id": record.tender_id,
        "project_id": record.project_id,
        "amount": record.amount,
        "baseline_amount": record.baseline_amount,
        "currency": record.currency,
    }
    if record.evidence:
        evidence.update(record.evidence)

    signal = EconomicSignal(
        signal_type="procurement_anomaly",
        sector=record.sector,
        agency=record.agency,
        entity_type="vendor",
        entity_id=record.vendor_id,
        window_start=occurred_at,
        window_end=occurred_at,
        score=scored.score,
        severity=scored.severity,
        reason_codes=scored.reason_codes,
        indicators=scored.indicators,
        evidence=evidence,
        source="system",
    )
    db.add(signal)
    db.flush()

    anomaly = ProcurementAnomaly(
        signal_id=signal.id,
        tender_id=record.tender_id,
        vendor_id=record.vendor_id,
        project_id=record.project_id,
        agency=record.agency,
        sector=record.sector,
        amount=record.amount,
        baseline_amount=record.baseline_amount,
        currency=record.currency,
        competitive_bids=record.competitive_bids,
        vendor_award_count_90d=record.vendor_award_count_90d,
        single_source=record.single_source,
        change_order_count=record.change_order_count,
        score=scored.score,
        severity=scored.severity,
        indicators=scored.indicators,
        evidence=evidence,
        occurred_at=occurred_at,
    )
    db.add(anomaly)
    db.commit()
    db.refresh(signal)
    db.refresh(anomaly)

    return {
        "signal_id": str(signal.id),
        "anomaly_id": str(anomaly.id),
        "score": scored.score,
        "severity": scored.severity,
        "reason_codes": scored.reason_codes,
        "indicators": scored.indicators,
    }


@router.post("/signals")
def create_signal(
    payload: EconomicSignalIn,
    db: Session = Depends(get_db),
):
    """
    Insert a generic economic integrity signal.
    """

    severity = payload.severity or severity_from_score(payload.score)
    source = payload.source or "manual"

    signal = EconomicSignal(
        signal_type=payload.signal_type,
        sector=payload.sector,
        agency=payload.agency,
        entity_type=payload.entity_type,
        entity_id=payload.entity_id,
        window_start=payload.window_start,
        window_end=payload.window_end,
        score=payload.score,
        severity=severity,
        source=source,
        reason_codes=payload.reason_codes,
        indicators=payload.indicators,
        evidence=payload.evidence,
    )
    db.add(signal)
    db.commit()
    db.refresh(signal)

    return {
        "signal_id": str(signal.id),
        "signal_type": signal.signal_type,
        "sector": signal.sector,
        "score": signal.score,
        "severity": signal.severity,
        "created_at": signal.created_at.isoformat(),
    }


@router.get("/signals")
def list_signals(
    signal_type: Optional[str] = Query(default=None),
    sector: Optional[str] = Query(default=None),
    agency: Optional[str] = Query(default=None),
    entity_type: Optional[str] = Query(default=None),
    entity_id: Optional[str] = Query(default=None),
    severity: Optional[str] = Query(default=None),
    min_score: Optional[float] = Query(default=None, ge=0.0, le=1.0),
    pagination: dict = Depends(pagination_params),
    db: Session = Depends(get_db),
):
    """
    List economic integrity signals with filters.
    """

    q = db.query(EconomicSignal)
    if signal_type:
        q = q.filter(EconomicSignal.signal_type == signal_type)
    if sector:
        q = q.filter(EconomicSignal.sector == sector)
    if agency:
        q = q.filter(EconomicSignal.agency == agency)
    if entity_type:
        q = q.filter(EconomicSignal.entity_type == entity_type)
    if entity_id:
        q = q.filter(EconomicSignal.entity_id == entity_id)
    if severity:
        q = q.filter(EconomicSignal.severity == severity)
    if min_score is not None:
        q = q.filter(EconomicSignal.score >= min_score)

    rows = (
        q.order_by(EconomicSignal.created_at.desc())
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
                "signal_type": r.signal_type,
                "sector": r.sector,
                "agency": r.agency,
                "entity_type": r.entity_type,
                "entity_id": r.entity_id,
                "window_start": r.window_start.isoformat(),
                "window_end": r.window_end.isoformat(),
                "score": r.score,
                "severity": r.severity,
                "reason_codes": r.reason_codes,
                "indicators": r.indicators,
                "evidence": r.evidence,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ],
    }


@router.get("/procurement/anomalies")
def list_procurement_anomalies(
    sector: Optional[str] = Query(default=None),
    agency: Optional[str] = Query(default=None),
    vendor_id: Optional[str] = Query(default=None),
    tender_id: Optional[str] = Query(default=None),
    min_score: Optional[float] = Query(default=None, ge=0.0, le=1.0),
    pagination: dict = Depends(pagination_params),
    db: Session = Depends(get_db),
):
    """
    List procurement anomalies with filters.
    """

    q = db.query(ProcurementAnomaly)
    if sector:
        q = q.filter(ProcurementAnomaly.sector == sector)
    if agency:
        q = q.filter(ProcurementAnomaly.agency == agency)
    if vendor_id:
        q = q.filter(ProcurementAnomaly.vendor_id == vendor_id)
    if tender_id:
        q = q.filter(ProcurementAnomaly.tender_id == tender_id)
    if min_score is not None:
        q = q.filter(ProcurementAnomaly.score >= min_score)

    rows = (
        q.order_by(ProcurementAnomaly.created_at.desc())
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
                "tender_id": r.tender_id,
                "vendor_id": r.vendor_id,
                "project_id": r.project_id,
                "agency": r.agency,
                "sector": r.sector,
                "amount": r.amount,
                "baseline_amount": r.baseline_amount,
                "currency": r.currency,
                "competitive_bids": r.competitive_bids,
                "vendor_award_count_90d": r.vendor_award_count_90d,
                "single_source": r.single_source,
                "change_order_count": r.change_order_count,
                "score": r.score,
                "severity": r.severity,
                "indicators": r.indicators,
                "evidence": r.evidence,
                "occurred_at": r.occurred_at.isoformat(),
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ],
    }

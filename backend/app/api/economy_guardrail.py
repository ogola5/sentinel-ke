from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db, pagination_params
from app.analytics.economy_guardrails import ProcurementGuardrailDecision, ExternalTamperAlert
from app.economy.guardrail import evaluate_and_persist_guardrail
from app.economy.integrity import ingest_integrity_snapshot
from app.economy.schemas import ProcurementRecord, IntegritySnapshotIn

router = APIRouter(prefix="/v1/economy", tags=["economy"])


@router.post("/guardrail/evaluate")
def evaluate_procurement_guardrail(
    record: ProcurementRecord,
    db: Session = Depends(get_db),
):
    """
    Evaluate procurement request and persist allow/review/block decision.
    """
    return evaluate_and_persist_guardrail(db, record=record)


@router.get("/guardrail/decisions")
def list_guardrail_decisions(
    pagination: dict = Depends(pagination_params),
    decision: str | None = Query(default=None),
    sector: str | None = Query(default=None),
    agency: str | None = Query(default=None),
    vendor_id: str | None = Query(default=None),
    min_score: float | None = Query(default=None, ge=0.0, le=1.0),
    db: Session = Depends(get_db),
):
    q = db.query(ProcurementGuardrailDecision)
    if decision:
        q = q.filter(ProcurementGuardrailDecision.decision == decision)
    if sector:
        q = q.filter(ProcurementGuardrailDecision.sector == sector)
    if agency:
        q = q.filter(ProcurementGuardrailDecision.agency == agency)
    if vendor_id:
        q = q.filter(ProcurementGuardrailDecision.vendor_id == vendor_id)
    if min_score is not None:
        q = q.filter(ProcurementGuardrailDecision.score >= min_score)

    rows = (
        q.order_by(ProcurementGuardrailDecision.created_at.desc())
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
                "decision": r.decision,
                "score": r.score,
                "severity": r.severity,
                "reason_codes": r.reason_codes,
                "indicators": r.indicators,
                "actions": r.actions,
                "evidence": r.evidence,
                "occurred_at": r.occurred_at.isoformat(),
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ],
    }


@router.post("/integrity/snapshot")
def create_integrity_snapshot(
    payload: IntegritySnapshotIn,
    db: Session = Depends(get_db),
):
    """
    Ingest external-system integrity snapshot and detect tamper/deletion.
    """
    return ingest_integrity_snapshot(db, payload=payload)


@router.get("/integrity/alerts")
def list_integrity_alerts(
    pagination: dict = Depends(pagination_params),
    source_system: str | None = Query(default=None),
    record_type: str | None = Query(default=None),
    alert_type: str | None = Query(default=None),
    severity: str | None = Query(default=None),
    status: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    q = db.query(ExternalTamperAlert)
    if source_system:
        q = q.filter(ExternalTamperAlert.source_system == source_system)
    if record_type:
        q = q.filter(ExternalTamperAlert.record_type == record_type)
    if alert_type:
        q = q.filter(ExternalTamperAlert.alert_type == alert_type)
    if severity:
        q = q.filter(ExternalTamperAlert.severity == severity)
    if status:
        q = q.filter(ExternalTamperAlert.status == status)

    rows = (
        q.order_by(ExternalTamperAlert.last_seen.desc())
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
                "source_system": r.source_system,
                "record_type": r.record_type,
                "record_id": r.record_id,
                "alert_type": r.alert_type,
                "severity": r.severity,
                "confidence": r.confidence,
                "status": r.status,
                "reason_codes": r.reason_codes,
                "details": r.details_json,
                "first_seen": r.first_seen.isoformat(),
                "last_seen": r.last_seen.isoformat(),
                "created_at": r.created_at.isoformat(),
                "updated_at": r.updated_at.isoformat(),
            }
            for r in rows
        ],
    }

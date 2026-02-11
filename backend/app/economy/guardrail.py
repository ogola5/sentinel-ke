from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from sqlalchemy.orm import Session

from app.analytics.economics import EconomicSignal, ProcurementAnomaly
from app.analytics.economy_guardrails import ProcurementGuardrailDecision
from app.analytics.mitigations import Mitigation
from app.economy.schemas import ProcurementRecord
from app.economy.scoring import score_procurement, severity_from_score


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


@dataclass(frozen=True)
class GuardrailOutcome:
    score: float
    severity: str
    decision: str
    reason_codes: List[str]
    indicators: Dict[str, Any]
    actions: List[str]


def evaluate_guardrail(
    *,
    record: ProcurementRecord,
    prior_anomaly_count_90d: int = 0,
    prior_high_count_180d: int = 0,
) -> GuardrailOutcome:
    """
    Deterministic allow/review/block decisioning for procurement controls.
    """
    base = score_procurement(record)
    score = float(base.score)
    reasons = list(base.reason_codes)
    indicators = dict(base.indicators)

    indicators["prior_anomaly_count_90d"] = int(prior_anomaly_count_90d)
    indicators["prior_high_count_180d"] = int(prior_high_count_180d)

    if prior_anomaly_count_90d >= 3:
        score += 0.15
        reasons.append("vendor_repeat_anomalies_90d")
    elif prior_anomaly_count_90d >= 1:
        score += 0.08
        reasons.append("vendor_recent_anomaly_90d")

    if prior_high_count_180d >= 2:
        score += 0.15
        reasons.append("vendor_high_risk_history_180d")
    elif prior_high_count_180d >= 1:
        score += 0.08
        reasons.append("vendor_high_risk_recent_180d")

    ratio = indicators.get("amount_to_baseline")
    if isinstance(ratio, (float, int)) and float(ratio) >= 2.0:
        score += 0.15
        reasons.append("amount_to_baseline_extreme")

    score = _clamp(score)
    severity = severity_from_score(score)

    decisive_block_pattern = (
        record.single_source
        and (record.competitive_bids is not None and record.competitive_bids <= 1)
        and (
            (isinstance(ratio, (float, int)) and float(ratio) >= 1.5)
            or prior_high_count_180d >= 1
        )
    )

    if score >= 0.8 or decisive_block_pattern:
        decision = "block"
        actions = [
            "Freeze award and require anti-fraud review",
            "Validate beneficial ownership and conflict disclosures",
            "Escalate to internal audit and ethics office",
        ]
    elif score >= 0.5:
        decision = "review"
        actions = [
            "Hold award pending independent procurement review",
            "Require budget and market-price validation",
            "Increase post-award monitoring frequency",
        ]
    else:
        decision = "allow"
        actions = [
            "Proceed with award",
            "Retain audit trail and continue continuous monitoring",
        ]

    return GuardrailOutcome(
        score=score,
        severity=severity,
        decision=decision,
        reason_codes=sorted(set(reasons)),
        indicators=indicators,
        actions=actions,
    )


def _history_counts(db: Session, *, record: ProcurementRecord, occurred_at: datetime) -> tuple[int, int]:
    q = db.query(ProcurementAnomaly)
    if record.vendor_id:
        q = q.filter(ProcurementAnomaly.vendor_id == record.vendor_id)
    if record.agency:
        q = q.filter(ProcurementAnomaly.agency == record.agency)
    if record.sector:
        q = q.filter(ProcurementAnomaly.sector == record.sector)

    prior_anomaly_count_90d = (
        q.filter(ProcurementAnomaly.occurred_at >= occurred_at - timedelta(days=90)).count()
    )
    prior_high_count_180d = (
        q.filter(ProcurementAnomaly.occurred_at >= occurred_at - timedelta(days=180))
        .filter(ProcurementAnomaly.severity.in_(["high", "critical"]))
        .count()
    )
    return prior_anomaly_count_90d, prior_high_count_180d


def evaluate_and_persist_guardrail(db: Session, *, record: ProcurementRecord) -> Dict[str, Any]:
    occurred_at = record.occurred_at or datetime.now(timezone.utc)
    prior_90d, prior_high_180d = _history_counts(db, record=record, occurred_at=occurred_at)
    outcome = evaluate_guardrail(
        record=record,
        prior_anomaly_count_90d=prior_90d,
        prior_high_count_180d=prior_high_180d,
    )

    evidence = {
        "tender_id": record.tender_id,
        "project_id": record.project_id,
        "vendor_id": record.vendor_id,
        "amount": record.amount,
        "baseline_amount": record.baseline_amount,
        "currency": record.currency,
        "competitive_bids": record.competitive_bids,
        "single_source": record.single_source,
        "change_order_count": record.change_order_count,
    }
    if record.evidence:
        evidence.update(record.evidence)

    signal = EconomicSignal(
        signal_type="procurement_guardrail",
        sector=record.sector,
        agency=record.agency,
        entity_type="vendor",
        entity_id=record.vendor_id,
        window_start=occurred_at,
        window_end=occurred_at,
        score=outcome.score,
        severity=outcome.severity,
        source="system",
        reason_codes=outcome.reason_codes,
        indicators=outcome.indicators,
        evidence=evidence,
    )
    db.add(signal)
    db.flush()

    decision = ProcurementGuardrailDecision(
        signal_id=signal.id,
        tender_id=record.tender_id,
        vendor_id=record.vendor_id,
        project_id=record.project_id,
        agency=record.agency,
        sector=record.sector,
        decision=outcome.decision,
        score=outcome.score,
        severity=outcome.severity,
        reason_codes=outcome.reason_codes,
        indicators=outcome.indicators,
        actions=outcome.actions,
        evidence=evidence,
        occurred_at=occurred_at,
    )
    db.add(decision)

    if outcome.decision in {"review", "block"}:
        ref = record.tender_id or record.project_id or record.vendor_id or f"unknown:{occurred_at.isoformat()}"
        ref_id = f"PROC_GUARDRAIL:{ref}"
        mit = (
            db.query(Mitigation)
            .filter(Mitigation.kind == "ECONOMY")
            .filter(Mitigation.ref_id == ref_id)
            .first()
        )
        payload = {
            "decision": outcome.decision,
            "severity": outcome.severity,
            "actions": outcome.actions,
            "reason_codes": outcome.reason_codes,
            "tender_id": record.tender_id,
            "project_id": record.project_id,
            "vendor_id": record.vendor_id,
        }
        if mit:
            mit.payload = payload
        else:
            db.add(
                Mitigation(
                    kind="ECONOMY",
                    ref_id=ref_id,
                    stakeholders=["PROCUREMENT", "AUDIT", "ETHICS"],
                    payload=payload,
                )
            )

    db.commit()
    db.refresh(signal)
    db.refresh(decision)

    return {
        "signal_id": str(signal.id),
        "decision_id": str(decision.id),
        "decision": decision.decision,
        "score": decision.score,
        "severity": decision.severity,
        "reason_codes": decision.reason_codes,
        "indicators": decision.indicators,
        "actions": decision.actions,
        "occurred_at": decision.occurred_at.isoformat(),
        "created_at": decision.created_at.isoformat(),
    }

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

from app.economy.schemas import ProcurementRecord


def _clamp(value: float, min_value: float = 0.0, max_value: float = 1.0) -> float:
    return max(min_value, min(max_value, value))


def severity_from_score(score: float) -> str:
    if score >= 0.8:
        return "critical"
    if score >= 0.6:
        return "high"
    if score >= 0.3:
        return "medium"
    return "low"


@dataclass(frozen=True)
class ProcurementScore:
    score: float
    severity: str
    reason_codes: List[str]
    indicators: Dict[str, Any]


def score_procurement(record: ProcurementRecord) -> ProcurementScore:
    """
    Lightweight, explainable procurement anomaly scoring.
    """

    score = 0.0
    reasons: List[str] = []
    indicators: Dict[str, Any] = {}

    if record.baseline_amount and record.baseline_amount > 0:
        ratio = record.amount / record.baseline_amount
        indicators["amount_to_baseline"] = round(ratio, 4)
        if ratio >= 1.5:
            score += 0.35
            reasons.append("amount_vs_baseline_high")
        elif ratio >= 1.2:
            score += 0.2
            reasons.append("amount_vs_baseline_elevated")

    if record.single_source:
        score += 0.2
        reasons.append("single_source_award")

    if record.competitive_bids is not None:
        indicators["competitive_bids"] = record.competitive_bids
        if record.competitive_bids <= 1:
            score += 0.2
            reasons.append("low_competition")
        elif record.competitive_bids <= 2:
            score += 0.1
            reasons.append("limited_competition")

    if record.vendor_award_count_90d is not None:
        indicators["vendor_award_count_90d"] = record.vendor_award_count_90d
        if record.vendor_award_count_90d >= 5:
            score += 0.2
            reasons.append("vendor_award_concentration_high")
        elif record.vendor_award_count_90d >= 3:
            score += 0.1
            reasons.append("vendor_award_concentration")

    if record.change_order_count is not None:
        indicators["change_order_count"] = record.change_order_count
        if record.change_order_count >= 3:
            score += 0.1
            reasons.append("excessive_change_orders")

    score = _clamp(score)
    severity = severity_from_score(score)

    return ProcurementScore(
        score=score,
        severity=severity,
        reason_codes=reasons,
        indicators=indicators,
    )

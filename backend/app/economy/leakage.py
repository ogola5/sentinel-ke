from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.analytics.economic_leakage import LeakageAlert
from app.analytics.economics import EconomicSignal, ProcurementAnomaly
from app.economy.scoring import severity_from_score


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def _hash_key(parts: Iterable[str]) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(str(p).encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()


@dataclass(frozen=True)
class LeakageCandidate:
    detector_type: str
    sector: str
    agency: Optional[str]
    vendor_id: Optional[str]
    project_id: Optional[str]
    score: float
    severity: str
    reason_codes: List[str]
    indicators: Dict[str, Any]
    evidence: Dict[str, Any]
    window_start: datetime
    window_end: datetime

    @property
    def signal_type(self) -> str:
        return f"economic_leakage_{self.detector_type}"

    @property
    def alert_key(self) -> str:
        return _hash_key(
            [
                self.detector_type,
                self.sector or "",
                self.agency or "",
                self.vendor_id or "",
                self.project_id or "",
                self.window_end.isoformat(),
            ]
        )[:40]


def _amount_ratio(amount: Optional[float], baseline: Optional[float]) -> Optional[float]:
    if baseline is None or baseline <= 0 or amount is None:
        return None
    return float(amount) / float(baseline)


def detect_split_tendering(
    rows: List[Dict[str, Any]],
    *,
    threshold: float = 1_000_000.0,
    near_threshold_ratio: float = 0.75,
    min_count: int = 3,
    window_start: datetime,
    window_end: datetime,
) -> List[LeakageCandidate]:
    grouped: Dict[Tuple[Optional[str], Optional[str], str], List[Dict[str, Any]]] = {}
    for r in rows:
        vendor_id = r.get("vendor_id")
        agency = r.get("agency")
        sector = r.get("sector") or "unknown"
        if not vendor_id or not agency:
            continue
        grouped.setdefault((agency, vendor_id, sector), []).append(r)

    out: List[LeakageCandidate] = []
    near_floor = threshold * near_threshold_ratio
    for (agency, vendor_id, sector), items in grouped.items():
        near = [
            x for x in items
            if x.get("amount") is not None and near_floor <= float(x["amount"]) < threshold
        ]
        if len(near) < min_count:
            continue

        total_amount = sum(float(x.get("amount") or 0.0) for x in near)
        avg_amount = total_amount / max(1, len(near))
        score = 0.55
        score += min(0.25, 0.05 * (len(near) - min_count + 1))
        if avg_amount >= (threshold * 0.9):
            score += 0.1
        if total_amount >= (threshold * min_count):
            score += 0.1
        score = _clamp(score)

        reason_codes = [
            "split_tender_pattern",
            "repeated_near_threshold_awards",
            "vendor_repeat_awards_same_window",
        ]
        evidence = {
            "tender_ids": [x.get("tender_id") for x in near if x.get("tender_id")][:30],
            "project_ids": list({x.get("project_id") for x in near if x.get("project_id")})[:30],
            "count": len(near),
        }
        indicators = {
            "threshold": threshold,
            "near_threshold_ratio": near_threshold_ratio,
            "award_count": len(near),
            "suspected_amount": round(total_amount, 2),
            "avg_amount": round(avg_amount, 2),
        }

        out.append(
            LeakageCandidate(
                detector_type="split_tendering",
                sector=sector,
                agency=agency,
                vendor_id=vendor_id,
                project_id=None,
                score=score,
                severity=severity_from_score(score),
                reason_codes=reason_codes,
                indicators=indicators,
                evidence=evidence,
                window_start=window_start,
                window_end=window_end,
            )
        )
    return out


def detect_vendor_concentration_capture(
    rows: List[Dict[str, Any]],
    *,
    min_award_count: int = 3,
    min_amount_share: float = 0.45,
    min_count_share: float = 0.4,
    window_start: datetime,
    window_end: datetime,
) -> List[LeakageCandidate]:
    by_agency: Dict[Tuple[Optional[str], str], List[Dict[str, Any]]] = {}
    for r in rows:
        agency = r.get("agency")
        sector = r.get("sector") or "unknown"
        if not agency:
            continue
        by_agency.setdefault((agency, sector), []).append(r)

    out: List[LeakageCandidate] = []
    for (agency, sector), items in by_agency.items():
        if len(items) < min_award_count:
            continue
        total_amount = sum(float(x.get("amount") or 0.0) for x in items)
        if total_amount <= 0:
            continue

        by_vendor: Dict[str, List[Dict[str, Any]]] = {}
        for x in items:
            vendor = x.get("vendor_id")
            if not vendor:
                continue
            by_vendor.setdefault(vendor, []).append(x)

        all_count = len(items)
        for vendor_id, vitems in by_vendor.items():
            v_count = len(vitems)
            v_amount = sum(float(x.get("amount") or 0.0) for x in vitems)
            amount_share = v_amount / total_amount if total_amount > 0 else 0.0
            count_share = v_count / all_count if all_count > 0 else 0.0

            if v_count < min_award_count:
                continue
            if amount_share < min_amount_share and count_share < min_count_share:
                continue

            score = 0.5
            score += min(0.25, amount_share * 0.4)
            score += min(0.2, count_share * 0.35)
            if v_count >= 5:
                score += 0.1
            score = _clamp(score)

            out.append(
                LeakageCandidate(
                    detector_type="vendor_concentration",
                    sector=sector,
                    agency=agency,
                    vendor_id=vendor_id,
                    project_id=None,
                    score=score,
                    severity=severity_from_score(score),
                    reason_codes=[
                        "vendor_capture_concentration",
                        "high_vendor_share_in_agency_window",
                    ],
                    indicators={
                        "award_count_vendor": v_count,
                        "award_count_total": all_count,
                        "count_share": round(count_share, 4),
                        "amount_share": round(amount_share, 4),
                        "suspected_amount": round(v_amount, 2),
                    },
                    evidence={
                        "tender_ids": [x.get("tender_id") for x in vitems if x.get("tender_id")][:30],
                        "project_ids": list({x.get("project_id") for x in vitems if x.get("project_id")})[:30],
                    },
                    window_start=window_start,
                    window_end=window_end,
                )
            )
    return out


def detect_change_order_inflation(
    rows: List[Dict[str, Any]],
    *,
    min_change_order_count: int = 2,
    min_ratio: float = 1.3,
    min_records: int = 2,
    window_start: datetime,
    window_end: datetime,
) -> List[LeakageCandidate]:
    grouped: Dict[Tuple[Optional[str], Optional[str], str], List[Dict[str, Any]]] = {}
    for r in rows:
        agency = r.get("agency")
        vendor_id = r.get("vendor_id")
        sector = r.get("sector") or "unknown"
        key = (agency, vendor_id, sector)
        grouped.setdefault(key, []).append(r)

    out: List[LeakageCandidate] = []
    for (agency, vendor_id, sector), items in grouped.items():
        flagged: List[Dict[str, Any]] = []
        for x in items:
            change_order_count = int(x.get("change_order_count") or 0)
            ratio = _amount_ratio(x.get("amount"), x.get("baseline_amount"))
            if ratio is None:
                continue
            if change_order_count >= min_change_order_count and ratio >= min_ratio:
                flagged.append({**x, "ratio": ratio})

        if len(flagged) < min_records:
            continue

        avg_ratio = sum(float(x["ratio"]) for x in flagged) / len(flagged)
        suspected_amount = sum(float(x.get("amount") or 0.0) for x in flagged)
        max_change_orders = max(int(x.get("change_order_count") or 0) for x in flagged)

        score = 0.52
        score += min(0.2, (avg_ratio - min_ratio) * 0.2)
        score += min(0.18, 0.06 * len(flagged))
        if max_change_orders >= 4:
            score += 0.1
        score = _clamp(score)

        out.append(
            LeakageCandidate(
                detector_type="change_order_inflation",
                sector=sector,
                agency=agency,
                vendor_id=vendor_id,
                project_id=None,
                score=score,
                severity=severity_from_score(score),
                reason_codes=[
                    "change_order_inflation_pattern",
                    "amount_growth_vs_baseline",
                ],
                indicators={
                    "records_flagged": len(flagged),
                    "avg_amount_to_baseline": round(avg_ratio, 4),
                    "max_change_order_count": max_change_orders,
                    "suspected_amount": round(suspected_amount, 2),
                },
                evidence={
                    "tender_ids": [x.get("tender_id") for x in flagged if x.get("tender_id")][:30],
                    "project_ids": list({x.get("project_id") for x in flagged if x.get("project_id")})[:30],
                },
                window_start=window_start,
                window_end=window_end,
            )
        )
    return out


def _query_procurement_rows(db: Session, *, window_start: datetime, window_end: datetime) -> List[Dict[str, Any]]:
    rows = (
        db.query(ProcurementAnomaly)
        .filter(ProcurementAnomaly.occurred_at >= window_start)
        .filter(ProcurementAnomaly.occurred_at <= window_end)
        .all()
    )
    out: List[Dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "id": str(r.id),
                "tender_id": r.tender_id,
                "vendor_id": r.vendor_id,
                "project_id": r.project_id,
                "agency": r.agency,
                "sector": r.sector,
                "amount": r.amount,
                "baseline_amount": r.baseline_amount,
                "competitive_bids": r.competitive_bids,
                "vendor_award_count_90d": r.vendor_award_count_90d,
                "single_source": r.single_source,
                "change_order_count": r.change_order_count,
                "score": r.score,
                "severity": r.severity,
                "occurred_at": r.occurred_at,
            }
        )
    return out


def detect_all_leakage_candidates(
    rows: List[Dict[str, Any]],
    *,
    window_start: datetime,
    window_end: datetime,
) -> List[LeakageCandidate]:
    candidates: List[LeakageCandidate] = []
    candidates.extend(
        detect_split_tendering(
            rows,
            window_start=window_start,
            window_end=window_end,
        )
    )
    candidates.extend(
        detect_vendor_concentration_capture(
            rows,
            window_start=window_start,
            window_end=window_end,
        )
    )
    candidates.extend(
        detect_change_order_inflation(
            rows,
            window_start=window_start,
            window_end=window_end,
        )
    )
    return candidates


def run_leakage_detection(
    db: Session,
    *,
    window_days: int = 30,
    as_of: Optional[datetime] = None,
) -> Dict[str, int]:
    window_end_raw = as_of or _now()
    # Stable hourly bucket for idempotent reruns within the same period.
    window_end = window_end_raw.replace(minute=0, second=0, microsecond=0)
    window_start = window_end - timedelta(days=window_days)

    rows = _query_procurement_rows(db, window_start=window_start, window_end=window_end)
    if not rows:
        return {"candidates": 0, "created": 0, "updated": 0}

    candidates = detect_all_leakage_candidates(rows, window_start=window_start, window_end=window_end)
    created = 0
    updated = 0

    for c in candidates:
        existing = db.query(LeakageAlert).filter(LeakageAlert.alert_key == c.alert_key).first()
        if existing:
            existing.score = c.score
            existing.severity = c.severity
            existing.reason_codes = c.reason_codes
            existing.indicators = c.indicators
            existing.evidence = c.evidence
            existing.window_start = c.window_start
            existing.window_end = c.window_end
            existing.updated_at = _now()
            alert = existing
            updated += 1
        else:
            alert = LeakageAlert(
                alert_key=c.alert_key,
                detector_type=c.detector_type,
                sector=c.sector,
                agency=c.agency,
                vendor_id=c.vendor_id,
                project_id=c.project_id,
                score=c.score,
                severity=c.severity,
                reason_codes=c.reason_codes,
                indicators=c.indicators,
                evidence=c.evidence,
                window_start=c.window_start,
                window_end=c.window_end,
            )
            db.add(alert)
            db.flush()
            created += 1

        signal = (
            db.query(EconomicSignal)
            .filter(EconomicSignal.signal_type == c.signal_type)
            .filter(EconomicSignal.agency == c.agency)
            .filter(EconomicSignal.entity_id == c.vendor_id)
            .filter(EconomicSignal.window_end == c.window_end)
            .first()
        )
        if signal:
            signal.score = c.score
            signal.severity = c.severity
            signal.reason_codes = c.reason_codes
            signal.indicators = c.indicators
            signal.evidence = c.evidence
        else:
            signal = EconomicSignal(
                signal_type=c.signal_type,
                sector=c.sector,
                agency=c.agency,
                entity_type="vendor" if c.vendor_id else None,
                entity_id=c.vendor_id,
                window_start=c.window_start,
                window_end=c.window_end,
                score=c.score,
                severity=c.severity,
                source="system",
                reason_codes=c.reason_codes,
                indicators=c.indicators,
                evidence=c.evidence,
            )
            db.add(signal)
            db.flush()
        alert.signal_id = signal.id

    db.commit()
    return {"candidates": len(candidates), "created": created, "updated": updated}

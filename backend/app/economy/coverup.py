from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy.orm import Session

from app.analytics.coverup_risk import CoverupRiskAlert
from app.analytics.economics import EconomicSignal
from app.economy.scoring import severity_from_score
from app.ledger.models import EventLog


RELEVANT_EVENT_TYPES = {
    "DB_AUDIT_EVENT",
    "FILE_INTEGRITY_EVENT",
    "DFIR_FINDING_EVENT",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def _to_list(v: Any) -> List[str]:
    if isinstance(v, list):
        return [str(x) for x in v if str(x).strip()]
    return []


def _norm_text(v: Any) -> str:
    if v is None:
        return ""
    return str(v).strip().lower()


def _is_off_hours(ts: datetime) -> bool:
    hh = ts.astimezone(timezone.utc).hour
    return hh >= 20 or hh < 6


def _contains_any(text: str, patterns: Sequence[str]) -> bool:
    t = _norm_text(text)
    if not t:
        return False
    return any(p in t for p in patterns)


def build_alert_key(*, target_type: str, target_id: str, window_end: datetime) -> str:
    h = hashlib.sha256()
    h.update(str(target_type).encode("utf-8"))
    h.update(b"\n")
    h.update(str(target_id).encode("utf-8"))
    h.update(b"\n")
    h.update(window_end.isoformat().encode("utf-8"))
    return h.hexdigest()[:48]


@dataclass(frozen=True)
class CoverupEventView:
    event_hash: str
    event_type: str
    occurred_at: datetime
    source_id: str
    anchors: Dict[str, Any]
    payload: Dict[str, Any]


@dataclass(frozen=True)
class CoverupScore:
    score: float
    severity: str
    reason_codes: List[str]
    indicators: Dict[str, Any]


@dataclass(frozen=True)
class CoverupCandidate:
    alert_key: str
    target_type: str
    target_id: str
    score: float
    severity: str
    reason_codes: List[str]
    indicators: Dict[str, Any]
    evidence_hashes: List[str]
    window_start: datetime
    window_end: datetime


def _target_from_event(event: CoverupEventView) -> Tuple[str, str]:
    anchors = event.anchors or {}
    service_id = anchors.get("service_id")
    if service_id:
        return "service", str(service_id)
    device_id = anchors.get("device_id")
    if device_id:
        return "device", str(device_id)
    return "source", str(event.source_id)


def score_coverup_events(events: Sequence[CoverupEventView]) -> CoverupScore:
    if not events:
        return CoverupScore(
            score=0.0,
            severity="low",
            reason_codes=["insufficient_evidence"],
            indicators={"event_count": 0},
        )

    exfiltration = 0.0
    privilege_abuse = 0.0
    audit_tamper = 0.0
    destruction = 0.0
    context = 0.0

    reason_hits: set[str] = set()
    event_types = {e.event_type for e in events}
    off_hours_count = 0

    for e in events:
        payload = e.payload or {}
        reason_codes = set(_to_list(payload.get("reason_codes")))
        statement_type = str(payload.get("statement_type") or "").upper()
        action = _norm_text(payload.get("action"))
        object_name = _norm_text(payload.get("object_name"))
        finding_type = _norm_text(payload.get("finding_type"))
        file_path = _norm_text(payload.get("file_path"))
        row_count = int(payload.get("row_count") or 0)

        if _is_off_hours(e.occurred_at):
            off_hours_count += 1

        if e.event_type == "DB_AUDIT_EVENT":
            if statement_type in {"COPY", "UNLOAD", "EXPORT", "SELECT INTO", "SELECT_INTO"}:
                exfiltration += 0.35
            if row_count >= 10_000:
                exfiltration += 0.2
            if "high_impact_db_statement" in reason_codes:
                exfiltration += 0.2

            if statement_type in {"GRANT", "REVOKE", "ALTER ROLE", "CREATE ROLE", "ALTER SYSTEM"}:
                privilege_abuse += 0.4
            if "audit_config_changed" in reason_codes:
                audit_tamper += 0.55
            if "backup_control_modified" in reason_codes:
                destruction += 0.5
            if statement_type == "ALTER SYSTEM" and _contains_any(object_name, ("audit", "log", "logging")):
                audit_tamper += 0.3

        elif e.event_type == "FILE_INTEGRITY_EVENT":
            if action == "permission_changed" or "permission_escalation_signal" in reason_codes:
                privilege_abuse += 0.4
            critical_path = bool(payload.get("is_critical_path") is True)
            if action == "deleted":
                destruction += 0.3
                if critical_path:
                    destruction += 0.35
            if _contains_any(file_path, ("/backup", "/wal", "/audit", "/log", "pg_wal", "ledger")):
                destruction += 0.2

        elif e.event_type == "DFIR_FINDING_EVENT":
            if "credential_access_signal" in reason_codes:
                privilege_abuse += 0.45
            if "log_tamper_signal" in reason_codes:
                audit_tamper += 0.5
            if finding_type in {"eventlog_cleared", "audit_log_deleted"}:
                audit_tamper += 0.35
            if finding_type in {"wiper_detected", "shadowcopy_deleted", "backup_catalog_deleted"}:
                destruction += 0.45

    exfiltration = _clamp(exfiltration)
    privilege_abuse = _clamp(privilege_abuse)
    audit_tamper = _clamp(audit_tamper)
    destruction = _clamp(destruction)

    total_events = len(events)
    off_hours_ratio = (off_hours_count / total_events) if total_events > 0 else 0.0
    if off_hours_ratio >= 0.6:
        context += 0.35
    elif off_hours_ratio >= 0.3:
        context += 0.2

    if total_events >= 10:
        context += 0.4
    elif total_events >= 5:
        context += 0.25

    if len(event_types) >= 3:
        context += 0.35
    elif len(event_types) >= 2:
        context += 0.2

    context = _clamp(context)

    score = (
        0.28 * exfiltration
        + 0.20 * privilege_abuse
        + 0.24 * audit_tamper
        + 0.20 * destruction
        + 0.08 * context
    )

    # Synergy bump when destructive and tamper patterns coincide.
    if destruction >= 0.6 and audit_tamper >= 0.6:
        score += 0.08
    if exfiltration >= 0.6 and privilege_abuse >= 0.6:
        score += 0.05
    score = _clamp(score)

    if exfiltration >= 0.5:
        reason_hits.add("exfiltration_signal_detected")
    if privilege_abuse >= 0.5:
        reason_hits.add("privilege_abuse_signal_detected")
    if audit_tamper >= 0.5:
        reason_hits.add("audit_tamper_signal_detected")
    if destruction >= 0.5:
        reason_hits.add("destruction_signal_detected")
    if context >= 0.4:
        reason_hits.add("high_risk_context_signal")
    if not reason_hits:
        reason_hits.add("low_signal_confidence")

    indicators = {
        "event_count": total_events,
        "event_type_count": len(event_types),
        "off_hours_ratio": round(off_hours_ratio, 4),
        "component_scores": {
            "exfiltration": round(exfiltration, 4),
            "privilege_abuse": round(privilege_abuse, 4),
            "audit_tamper": round(audit_tamper, 4),
            "destruction": round(destruction, 4),
            "context": round(context, 4),
        },
    }

    severity = severity_from_score(score)
    return CoverupScore(
        score=score,
        severity=severity,
        reason_codes=sorted(reason_hits),
        indicators=indicators,
    )


def build_coverup_candidates(
    events: Sequence[CoverupEventView],
    *,
    window_start: datetime,
    window_end: datetime,
    min_score: float = 0.45,
    max_evidence: int = 80,
) -> List[CoverupCandidate]:
    grouped: Dict[Tuple[str, str], List[CoverupEventView]] = {}
    for e in events:
        t = _target_from_event(e)
        grouped.setdefault(t, []).append(e)

    out: List[CoverupCandidate] = []
    for (target_type, target_id), items in grouped.items():
        ordered = sorted(items, key=lambda x: x.occurred_at)
        scored = score_coverup_events(ordered)
        if scored.score < min_score:
            continue

        evidence_hashes = [x.event_hash for x in reversed(ordered)]
        seen = set()
        deduped = []
        for h in evidence_hashes:
            if h in seen:
                continue
            seen.add(h)
            deduped.append(h)
            if len(deduped) >= max_evidence:
                break

        indicators = dict(scored.indicators)
        indicators["target_type"] = target_type
        indicators["target_id"] = target_id
        indicators["window_start"] = window_start.isoformat()
        indicators["window_end"] = window_end.isoformat()

        out.append(
            CoverupCandidate(
                alert_key=build_alert_key(
                    target_type=target_type,
                    target_id=target_id,
                    window_end=window_end,
                ),
                target_type=target_type,
                target_id=target_id,
                score=scored.score,
                severity=scored.severity,
                reason_codes=scored.reason_codes,
                indicators=indicators,
                evidence_hashes=deduped,
                window_start=window_start,
                window_end=window_end,
            )
        )
    return out


def _query_coverup_events(db: Session, *, window_start: datetime, window_end: datetime) -> List[CoverupEventView]:
    rows = (
        db.query(EventLog)
        .filter(EventLog.occurred_at >= window_start)
        .filter(EventLog.occurred_at <= window_end)
        .filter(EventLog.event_type.in_(RELEVANT_EVENT_TYPES))
        .all()
    )
    out: List[CoverupEventView] = []
    for r in rows:
        out.append(
            CoverupEventView(
                event_hash=str(r.event_hash),
                event_type=str(r.event_type),
                occurred_at=r.occurred_at,
                source_id=str(r.source_id),
                anchors=dict(r.anchors_json or {}),
                payload=dict(r.payload_json or {}),
            )
        )
    return out


def run_coverup_detection(
    db: Session,
    *,
    window_days: int = 30,
    as_of: Optional[datetime] = None,
    min_score: float = 0.45,
) -> Dict[str, int]:
    window_end_raw = as_of or _now()
    window_end = window_end_raw.replace(minute=0, second=0, microsecond=0)
    window_start = window_end - timedelta(days=window_days)

    events = _query_coverup_events(db, window_start=window_start, window_end=window_end)
    if not events:
        return {"events": 0, "candidates": 0, "created": 0, "updated": 0}

    candidates = build_coverup_candidates(
        events,
        window_start=window_start,
        window_end=window_end,
        min_score=min_score,
    )
    created = 0
    updated = 0

    for c in candidates:
        existing = db.query(CoverupRiskAlert).filter(CoverupRiskAlert.alert_key == c.alert_key).first()
        if existing:
            existing.score = c.score
            existing.severity = c.severity
            existing.reason_codes = c.reason_codes
            existing.indicators = c.indicators
            existing.evidence_hashes = c.evidence_hashes
            existing.window_start = c.window_start
            existing.window_end = c.window_end
            existing.updated_at = _now()
            alert = existing
            updated += 1
        else:
            alert = CoverupRiskAlert(
                alert_key=c.alert_key,
                target_type=c.target_type,
                target_id=c.target_id,
                score=c.score,
                severity=c.severity,
                status="open",
                reason_codes=c.reason_codes,
                indicators=c.indicators,
                evidence_hashes=c.evidence_hashes,
                window_start=c.window_start,
                window_end=c.window_end,
            )
            db.add(alert)
            db.flush()
            created += 1

        signal = (
            db.query(EconomicSignal)
            .filter(EconomicSignal.signal_type == "coverup_risk")
            .filter(EconomicSignal.entity_type == c.target_type)
            .filter(EconomicSignal.entity_id == c.target_id)
            .filter(EconomicSignal.window_end == c.window_end)
            .first()
        )
        if signal:
            signal.score = c.score
            signal.severity = c.severity
            signal.reason_codes = c.reason_codes
            signal.indicators = c.indicators
            signal.evidence = {
                "evidence_hashes": c.evidence_hashes,
                "target_type": c.target_type,
                "target_id": c.target_id,
            }
        else:
            signal = EconomicSignal(
                signal_type="coverup_risk",
                sector="public",
                agency=None,
                entity_type=c.target_type,
                entity_id=c.target_id,
                window_start=c.window_start,
                window_end=c.window_end,
                score=c.score,
                severity=c.severity,
                source="system",
                reason_codes=c.reason_codes,
                indicators=c.indicators,
                evidence={
                    "evidence_hashes": c.evidence_hashes,
                    "target_type": c.target_type,
                    "target_id": c.target_id,
                },
            )
            db.add(signal)
            db.flush()
        alert.signal_id = signal.id

    db.commit()
    return {
        "events": len(events),
        "candidates": len(candidates),
        "created": created,
        "updated": updated,
    }

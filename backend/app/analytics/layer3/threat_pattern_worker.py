from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Dict, List

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.analytics.mitigations import Mitigation
from app.analytics.threat_alerts import ThreatAlert
from app.ledger.models import EventLog


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _severity(score: float) -> str:
    if score >= 90:
        return "critical"
    if score >= 75:
        return "high"
    if score >= 55:
        return "medium"
    return "low"


def _upsert_alerts(db: Session, rows: List[Dict[str, object]]) -> int:
    if not rows:
        return 0
    stmt = insert(ThreatAlert).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["alert_type", "section_code", "entity_key", "window_end"],
        set_={
            "score": stmt.excluded.score,
            "severity": stmt.excluded.severity,
            "reason_codes": stmt.excluded.reason_codes,
            "indicators": stmt.excluded.indicators,
            "recommended_actions": stmt.excluded.recommended_actions,
            "updated_at": stmt.excluded.updated_at,
        },
    )
    res = db.execute(stmt)
    return int(res.rowcount or 0)


def _upsert_mitigation(db: Session, *, kind: str, ref_id: str, payload: Dict[str, object]) -> None:
    existing = (
        db.query(Mitigation)
        .filter(Mitigation.kind == kind)
        .filter(Mitigation.ref_id == ref_id)
        .first()
    )
    if existing:
        existing.payload = payload
        return
    db.add(
        Mitigation(
            kind=kind,
            ref_id=ref_id,
            stakeholders=["soc", "incident_response"],
            payload=payload,
        )
    )


def run_once(
    *,
    db: Session,
    minutes: int = 60,
    section_code: str | None = None,
) -> Dict[str, object]:
    end = _now()
    start = end - timedelta(minutes=max(1, int(minutes)))

    q = (
        db.query(EventLog)
        .filter(EventLog.occurred_at >= start)
        .filter(EventLog.occurred_at <= end)
    )
    sec = (section_code or "").strip()
    if sec:
        q = q.filter(EventLog.section_code == sec)
    rows = q.all()

    bec_counts: Dict[tuple[str | None, str], int] = defaultdict(int)
    web_counts: Dict[tuple[str | None, str], Dict[str, int]] = defaultdict(lambda: {"total": 0, "allowed": 0, "blocked": 0})
    vuln_overdue: Dict[tuple[str | None, str], int] = defaultdict(int)
    backup_risk: Dict[tuple[str | None, str], int] = defaultdict(int)

    for row in rows:
        payload = dict(row.payload_json or {})
        anchors = dict(row.anchors_json or {})
        section_code = row.section_code

        if row.event_type == "PHISHING_MESSAGE_EVENT":
            key = anchors.get("person_h") or anchors.get("domain") or "mail:unknown"
            bec_counts[(section_code, key)] += 1

        elif row.event_type == "WEB_ATTACK_EVENT":
            key = anchors.get("service_id") or payload.get("service_id") or "web:unknown"
            status = str(payload.get("status") or "detected").lower()
            bucket = web_counts[(section_code, key)]
            bucket["total"] += 1
            if status == "allowed":
                bucket["allowed"] += 1
            elif status == "blocked":
                bucket["blocked"] += 1

        elif row.event_type == "VULNERABILITY_EVENT":
            key = anchors.get("service_id") or payload.get("asset_id") or "asset:unknown"
            due = str(payload.get("patch_due_date") or "").strip()
            status = str(payload.get("status") or "open").lower()
            if status not in {"patched", "resolved", "closed"} and due:
                try:
                    due_dt = datetime.fromisoformat(due.replace("Z", "+00:00"))
                    if due_dt.tzinfo is None:
                        due_dt = due_dt.replace(tzinfo=timezone.utc)
                    if due_dt < end:
                        vuln_overdue[(section_code, key)] += 1
                except Exception:
                    vuln_overdue[(section_code, key)] += 1

        elif row.event_type == "BACKUP_ATTESTATION_EVENT":
            key = anchors.get("service_id") or payload.get("asset_id") or "asset:unknown"
            immutable = bool(payload.get("immutable") is True)
            status = str(payload.get("status") or "ok").lower()
            if (not immutable) or status in {"risk", "failed", "error"}:
                backup_risk[(section_code, key)] += 1

    alert_rows: List[Dict[str, object]] = []

    for (section_code, key), count in bec_counts.items():
        score = min(100.0, 40.0 + count * 12.0)
        sev = _severity(score)
        if score < 55.0:
            continue
        alert_rows.append(
            {
                "alert_type": "bec_risk",
                "section_code": section_code,
                "entity_key": key,
                "window_start": start,
                "window_end": end,
                "score": round(score, 4),
                "severity": sev,
                "reason_codes": ["bec_signal_surge"],
                "indicators": {"phishing_events": count},
                "recommended_actions": [
                    "enforce phishing-resistant MFA",
                    "block sender domain and URLs",
                    "trigger user comms verification",
                ],
            }
        )

    for (section_code, key), vals in web_counts.items():
        total = vals["total"]
        if total <= 0:
            continue
        bypass_ratio = vals["allowed"] / max(1, total)
        score = min(100.0, total * 3.0 + bypass_ratio * 60.0)
        sev = _severity(score)
        if score < 55.0:
            continue
        alert_rows.append(
            {
                "alert_type": "web_attack_surge",
                "section_code": section_code,
                "entity_key": key,
                "window_start": start,
                "window_end": end,
                "score": round(score, 4),
                "severity": sev,
                "reason_codes": ["web_attack_volume_high", "waf_bypass_risk" if bypass_ratio > 0.1 else "waf_under_pressure"],
                "indicators": {
                    "total_events": total,
                    "allowed_events": vals["allowed"],
                    "blocked_events": vals["blocked"],
                    "allowed_ratio": round(bypass_ratio, 6),
                },
                "recommended_actions": [
                    "tighten WAF managed rules",
                    "enable API schema validation",
                    "rate-limit abusive source patterns",
                ],
            }
        )

    for (section_code, key), count in vuln_overdue.items():
        score = min(100.0, 50.0 + count * 10.0)
        sev = _severity(score)
        alert_rows.append(
            {
                "alert_type": "vuln_overdue",
                "section_code": section_code,
                "entity_key": key,
                "window_start": start,
                "window_end": end,
                "score": round(score, 4),
                "severity": sev,
                "reason_codes": ["patch_sla_overdue"],
                "indicators": {"overdue_vulns": count},
                "recommended_actions": [
                    "apply emergency patch window",
                    "add compensating controls until patch",
                    "track exec risk acceptance",
                ],
            }
        )

    for (section_code, key), count in backup_risk.items():
        score = min(100.0, 55.0 + count * 8.0)
        sev = _severity(score)
        alert_rows.append(
            {
                "alert_type": "backup_risk",
                "section_code": section_code,
                "entity_key": key,
                "window_start": start,
                "window_end": end,
                "score": round(score, 4),
                "severity": sev,
                "reason_codes": ["immutable_backup_missing"],
                "indicators": {"risky_attestations": count},
                "recommended_actions": [
                    "enable object lock / immutable tier",
                    "run restore drill in 24h",
                    "validate offline backup copy",
                ],
            }
        )

    upserted = _upsert_alerts(db, alert_rows)

    mitigations = 0
    for row in alert_rows:
        if row["severity"] in {"high", "critical"}:
            ref_id = f"{row['alert_type']}:{row['entity_key']}:{end.isoformat()}"
            _upsert_mitigation(
                db,
                kind="THREAT_ALERT",
                ref_id=ref_id,
                payload={
                    "alert_type": row["alert_type"],
                    "severity": row["severity"],
                    "entity_key": row["entity_key"],
                    "reason_codes": row["reason_codes"],
                    "recommended_actions": row["recommended_actions"],
                },
            )
            mitigations += 1

    db.commit()
    return {
        "upserted_alerts": upserted,
        "mitigations_touched": mitigations,
        "section_code": sec or None,
    }


def main() -> None:
    import argparse
    from app.ledger.db import SessionLocal

    p = argparse.ArgumentParser()
    p.add_argument("--minutes", type=int, default=60)
    args = p.parse_args()

    db = SessionLocal()
    try:
        out = run_once(db=db, minutes=args.minutes)
        print(json.dumps(out))
    finally:
        db.close()


if __name__ == "__main__":
    main()

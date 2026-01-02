from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.analytics.ai_models import AIPrediction, AIExplanation, GraphFeatureSnapshot
from app.ledger.db import SessionLocal


def _latest_window_end(db: Session, window_key: str) -> Optional[datetime]:
    return (
        db.query(func.max(GraphFeatureSnapshot.window_end))
        .filter(GraphFeatureSnapshot.window_key == window_key)
        .scalar()
    )


def _event_hashes(
    db: Session,
    *,
    entity_key: str,
    window_start: datetime,
    window_end: datetime,
    limit: int = 20,
) -> List[str]:
    rows = db.execute(
        text(
            """
            SELECT ee.event_hash
            FROM event_entity_index ee
            JOIN event_log el ON el.event_hash = ee.event_hash
            WHERE ee.entity_key = :entity_key
              AND el.occurred_at >= :start
              AND el.occurred_at <= :end
            ORDER BY el.occurred_at DESC
            LIMIT :limit
            """
        ),
        {"entity_key": entity_key, "start": window_start, "end": window_end, "limit": limit},
    ).fetchall()
    return [str(r[0]) for r in rows]


def _score(snapshot: GraphFeatureSnapshot) -> Tuple[float, List[str], Dict[str, object]]:
    flags = set(snapshot.risk_flags or [])
    features = snapshot.features or {}
    event_count = int(snapshot.event_count or 0)
    source_count = int(features.get("source_count") or 0)
    last_seen_age = features.get("last_seen_age_sec")

    score = 0.0
    score += min(40.0, event_count * 2.0)
    if "DDOS_ALERT_SERVICE" in flags or "DDOS_ALERT_ENDPOINT" in flags:
        score += 30.0
    if "VPN_CLUSTER_MEMBER" in flags:
        score += 20.0
    if "CAMPAIGN_ENTITY" in flags:
        score += 15.0
    if "DDOS_CLUSTER_MEMBER" in flags:
        score += 10.0
    if source_count >= 3:
        score += 10.0
    if last_seen_age is not None and last_seen_age <= 300:
        score += 5.0

    score = min(100.0, score)

    reasons: List[str] = []
    if event_count >= 20:
        reasons.append("EVENT_VOLUME_HIGH")
    elif event_count >= 5:
        reasons.append("EVENT_VOLUME_MED")
    if source_count >= 3:
        reasons.append("MULTI_SOURCE")
    if last_seen_age is not None and last_seen_age <= 300:
        reasons.append("RECENT_ACTIVITY")
    if "DDOS_ALERT_SERVICE" in flags or "DDOS_ALERT_ENDPOINT" in flags:
        reasons.append("DDOS_ALERT_ACTIVE")
    if "VPN_CLUSTER_MEMBER" in flags:
        reasons.append("VPN_INFRA_REUSE")
    if "CAMPAIGN_ENTITY" in flags:
        reasons.append("CAMPAIGN_LINKED")
    if "DDOS_CLUSTER_MEMBER" in flags:
        reasons.append("DDOS_INFRA_REUSE")

    event_types = features.get("event_types") or {}
    if "DDOS_SIGNAL_EVENT" in event_types:
        reasons.append("DDOS_SIGNAL_SEEN")
    if "SIM_SWAP_EVENT" in event_types:
        reasons.append("SIM_SWAP_SIGNAL")
    if "TRANSACTION_EVENT" in event_types:
        reasons.append("TXN_ACTIVITY")
    if "PHISHING_MESSAGE_EVENT" in event_types:
        reasons.append("PHISHING_SIGNAL")

    if not reasons:
        reasons.append("LOW_SIGNAL")

    details = {
        "event_count": event_count,
        "source_count": source_count,
        "risk_flags": list(flags),
        "event_types": event_types,
    }
    return score, reasons, details


def run_once(
    *,
    db: Session,
    window_key: str = "Wshort",
    window_end: Optional[datetime] = None,
    prediction_type: str = "risk",
    max_entities: int = 5000,
    evidence_limit: int = 20,
) -> int:
    if window_end is None:
        window_end = _latest_window_end(db, window_key)
    if window_end is None:
        return 0

    snapshots = (
        db.query(GraphFeatureSnapshot)
        .filter(GraphFeatureSnapshot.window_key == window_key)
        .filter(GraphFeatureSnapshot.window_end == window_end)
        .limit(max_entities)
        .all()
    )
    if not snapshots:
        return 0

    created = 0
    for snap in snapshots:
        score, reasons, details = _score(snap)

        pred = (
            db.query(AIPrediction)
            .filter(AIPrediction.entity_key == snap.entity_key)
            .filter(AIPrediction.prediction_type == prediction_type)
            .filter(AIPrediction.window_key == window_key)
            .filter(AIPrediction.window_end == snap.window_end)
            .first()
        )

        if pred:
            pred.score = score
            pred.reason_codes = reasons
            pred.details_json = details
        else:
            pred = AIPrediction(
                entity_key=snap.entity_key,
                entity_type=snap.entity_type,
                prediction_type=prediction_type,
                window_key=window_key,
                window_end=snap.window_end,
                score=score,
                reason_codes=reasons,
                details_json=details,
            )
            db.add(pred)
            db.flush()
            created += 1

        evidence = _event_hashes(
            db,
            entity_key=snap.entity_key,
            window_start=snap.window_start,
            window_end=snap.window_end,
            limit=evidence_limit,
        )

        expl = (
            db.query(AIExplanation)
            .filter(AIExplanation.prediction_id == pred.id)
            .first()
        )
        expl_payload = {
            "window_start": snap.window_start.isoformat(),
            "window_end": snap.window_end.isoformat(),
        }
        if expl:
            expl.reason_codes = reasons
            expl.evidence_hashes = evidence
            expl.evidence_paths = []
            expl.details_json = expl_payload
        else:
            db.add(
                AIExplanation(
                    prediction_id=pred.id,
                    reason_codes=reasons,
                    evidence_hashes=evidence,
                    evidence_paths=[],
                    details_json=expl_payload,
                )
            )

    db.commit()
    return created


def main() -> None:
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--window-key", default="Wshort")
    p.add_argument("--window-end", default=None, help="ISO timestamp override")
    p.add_argument("--prediction-type", default="risk")
    p.add_argument("--max-entities", type=int, default=5000)
    p.add_argument("--evidence-limit", type=int, default=20)
    args = p.parse_args()

    window_end = None
    if args.window_end:
        window_end = datetime.fromisoformat(args.window_end.replace("Z", "+00:00"))

    db = SessionLocal()
    try:
        n = run_once(
            db=db,
            window_key=args.window_key,
            window_end=window_end,
            prediction_type=args.prediction_type,
            max_entities=args.max_entities,
            evidence_limit=args.evidence_limit,
        )
        print(json.dumps({"predictions_created": n}))
    finally:
        db.close()


if __name__ == "__main__":
    main()

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Dict, Iterable, List, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.analytics.ai_models import GraphFeatureSnapshot
from app.analytics.infra_windows import last_minutes
from app.analytics.ddos_alerts import DDoSAlert
from app.campaign.models import CampaignEntity
from app.ledger.infra_clusters import InfraCluster, InfraClusterMember
from app.ledger.db import SessionLocal
from app.db.base import utcnow


def _entity_parts(entity_key: str) -> Tuple[str, str]:
    if ":" not in entity_key:
        return entity_key, ""
    kind, raw = entity_key.split(":", 1)
    return kind, raw


def _window_defs(short_minutes: int, mid_minutes: int, long_minutes: int) -> Dict[str, object]:
    return {
        "Wshort": last_minutes(short_minutes),
        "Wmid": last_minutes(mid_minutes),
        "Wlong": last_minutes(long_minutes),
    }


def _ddos_alert_sets(db: Session, window) -> Tuple[set[str], set[str]]:
    rows = (
        db.query(DDoSAlert.service_id, DDoSAlert.endpoint)
        .filter(DDoSAlert.window_end >= window.start)
        .filter(DDoSAlert.window_end <= window.end)
        .all()
    )
    services = {r[0] for r in rows if r[0]}
    endpoints = {r[1] for r in rows if r[1]}
    return services, endpoints


def _campaign_entity_set(db: Session, window) -> set[str]:
    rows = (
        db.query(CampaignEntity.entity_key)
        .filter(CampaignEntity.last_seen >= window.start)
        .all()
    )
    return {r[0] for r in rows}


def _infra_member_kinds(db: Session) -> Dict[str, str]:
    rows = (
        db.query(InfraClusterMember.entity_key, InfraCluster.kind)
        .join(InfraCluster, InfraCluster.cluster_id == InfraClusterMember.cluster_id)
        .all()
    )
    return {r[0]: (r[1] or "") for r in rows}


def _event_type_counts(db: Session, window) -> Dict[str, Dict[str, int]]:
    rows = db.execute(
        text(
            """
            SELECT ee.entity_key, el.event_type, COUNT(*) AS cnt
            FROM event_entity_index ee
            JOIN event_log el ON el.event_hash = ee.event_hash
            WHERE el.occurred_at >= :start AND el.occurred_at <= :end
            GROUP BY ee.entity_key, el.event_type
            """
        ),
        {"start": window.start, "end": window.end},
    ).fetchall()

    out: Dict[str, Dict[str, int]] = defaultdict(dict)
    for entity_key, event_type, cnt in rows:
        out[str(entity_key)][str(event_type)] = int(cnt or 0)
    return out


def _entity_stats(db: Session, window, max_entities: int) -> Iterable[Dict[str, object]]:
    rows = db.execute(
        text(
            """
            SELECT
                ee.entity_key,
                COUNT(DISTINCT ee.event_hash) AS event_count,
                COUNT(DISTINCT el.source_id) AS source_count,
                MIN(el.occurred_at) AS first_seen,
                MAX(el.occurred_at) AS last_seen
            FROM event_entity_index ee
            JOIN event_log el ON el.event_hash = ee.event_hash
            WHERE el.occurred_at >= :start AND el.occurred_at <= :end
            GROUP BY ee.entity_key
            ORDER BY event_count DESC
            LIMIT :limit
            """
        ),
        {"start": window.start, "end": window.end, "limit": max_entities},
    ).fetchall()

    for r in rows:
        yield {
            "entity_key": str(r[0]),
            "event_count": int(r[1] or 0),
            "source_count": int(r[2] or 0),
            "first_seen": r[3],
            "last_seen": r[4],
        }


def run_once(
    *,
    db: Session,
    window_key: Optional[str] = None,
    short_minutes: int = 10,
    mid_minutes: int = 24 * 60,
    long_minutes: int = 30 * 24 * 60,
    max_entities: int = 5000,
) -> int:
    windows = _window_defs(short_minutes, mid_minutes, long_minutes)
    if window_key:
        if window_key not in windows:
            raise ValueError(f"unknown window_key: {window_key}")
        windows = {window_key: windows[window_key]}

    infra_kinds = _infra_member_kinds(db)
    total_upserts = 0

    for wkey, win in windows.items():
        ddos_services, ddos_endpoints = _ddos_alert_sets(db, win)
        campaign_entities = _campaign_entity_set(db, win)
        event_types = _event_type_counts(db, win)

        rows: List[Dict[str, object]] = []
        for stat in _entity_stats(db, win, max_entities):
            entity_key = str(stat["entity_key"])
            entity_type, raw = _entity_parts(entity_key)
            flags: List[str] = []

            if entity_key in campaign_entities:
                flags.append("CAMPAIGN_ENTITY")

            kind = infra_kinds.get(entity_key)
            if kind:
                if kind == "vpn_exit":
                    flags.append("VPN_CLUSTER_MEMBER")
                elif kind == "ddos":
                    flags.append("DDOS_CLUSTER_MEMBER")
                else:
                    flags.append("INFRA_CLUSTER_MEMBER")

            if entity_type == "service_id" and raw in ddos_services:
                flags.append("DDOS_ALERT_SERVICE")
            if entity_type == "endpoint" and raw in ddos_endpoints:
                flags.append("DDOS_ALERT_ENDPOINT")

            last_seen = stat["last_seen"]
            age_sec = None
            if isinstance(last_seen, datetime):
                age_sec = max(0.0, (win.end - last_seen).total_seconds())

            features = {
                "source_count": int(stat["source_count"]),
                "event_types": event_types.get(entity_key, {}),
                "last_seen_age_sec": age_sec,
            }

            rows.append(
                {
                    "entity_key": entity_key,
                    "entity_type": entity_type,
                    "window_key": wkey,
                    "window_start": win.start,
                    "window_end": win.end,
                    "degree": int(stat["event_count"]),
                    "weighted_degree": int(stat["event_count"]),
                    "event_count": int(stat["event_count"]),
                    "first_seen": stat["first_seen"],
                    "last_seen": stat["last_seen"],
                    "risk_flags": flags,
                    "features": features,
                    "created_at": utcnow(),
                }
            )

        if not rows:
            continue

        stmt = insert(GraphFeatureSnapshot).values(rows)
        update_cols = {
            "entity_type": stmt.excluded.entity_type,
            "window_start": stmt.excluded.window_start,
            "degree": stmt.excluded.degree,
            "weighted_degree": stmt.excluded.weighted_degree,
            "event_count": stmt.excluded.event_count,
            "first_seen": stmt.excluded.first_seen,
            "last_seen": stmt.excluded.last_seen,
            "risk_flags": stmt.excluded.risk_flags,
            "features": stmt.excluded.features,
        }
        stmt = stmt.on_conflict_do_update(
            index_elements=["entity_key", "window_key", "window_end"],
            set_=update_cols,
        )
        res = db.execute(stmt)
        total_upserts += res.rowcount or 0

    db.commit()
    return total_upserts


def main() -> None:
    import argparse
    import json

    p = argparse.ArgumentParser()
    p.add_argument("--window-key", default=None, choices=["Wshort", "Wmid", "Wlong"])
    p.add_argument("--short-minutes", type=int, default=10)
    p.add_argument("--mid-minutes", type=int, default=24 * 60)
    p.add_argument("--long-minutes", type=int, default=30 * 24 * 60)
    p.add_argument("--max-entities", type=int, default=5000)
    args = p.parse_args()

    db = SessionLocal()
    try:
        n = run_once(
            db=db,
            window_key=args.window_key,
            short_minutes=args.short_minutes,
            mid_minutes=args.mid_minutes,
            long_minutes=args.long_minutes,
            max_entities=args.max_entities,
        )
        print(json.dumps({"features_upserted": n}))
    finally:
        db.close()


if __name__ == "__main__":
    main()

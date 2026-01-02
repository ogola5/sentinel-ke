from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Set

from sqlalchemy.orm import Session
from sqlalchemy import text

from app.ledger.infra_clusters import InfraCluster, InfraClusterMember
from app.ledger.infra_evidence import InfraClusterEvidence
from app.ledger.db import SessionLocal
from app.db.base import utcnow


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def run_once(db: Session, minutes: int = 60, min_ips: int = 2) -> int:
    """
    Simple VPN/operator correlation:
    - Look at recent events with anchors ip + endpoint in the last `minutes`
    - Group IPs by endpoint and collect provider_id if present
    - For endpoints with >= min_ips distinct IPs, create an InfraCluster(kind=vpn_exit)
    - Evidence: ENDPOINT_OVERLAP (+ PROVIDER_MATCH if applicable) with list of IPs/providers
    """
    cutoff = _now_utc() - timedelta(minutes=minutes)

    rows = db.execute(
        text(
            """
            SELECT anchors_json->>'ip' AS ip,
                   anchors_json->>'endpoint' AS endpoint,
                   COALESCE(anchors_json->>'provider_id', payload_json->>'provider') AS provider_id,
                   occurred_at
            FROM event_log
            WHERE anchors_json ? 'ip'
              AND anchors_json ? 'endpoint'
              AND occurred_at >= :cutoff
            """
        ),
        {"cutoff": cutoff},
    ).fetchall()

    endpoint_to_ips: Dict[str, Set[str]] = {}
    endpoint_to_providers: Dict[str, Set[str]] = {}
    endpoint_to_times: Dict[str, List[datetime]] = {}
    for ip, endpoint, provider_id, occurred_at in rows:
        if not ip or not endpoint:
            continue
        endpoint = str(endpoint).strip()
        ip = str(ip).strip()
        if not endpoint or not ip:
            continue
        endpoint_to_ips.setdefault(endpoint, set()).add(ip)
        if provider_id:
            endpoint_to_providers.setdefault(endpoint, set()).add(str(provider_id).strip())
        if occurred_at:
            endpoint_to_times.setdefault(endpoint, []).append(occurred_at)

    created = 0
    for endpoint, ips in endpoint_to_ips.items():
        if len(ips) < min_ips:
            continue

        cluster_id = str(uuid.uuid4())
        tw_end = _now_utc()
        tw_start = tw_end - timedelta(minutes=minutes)

        # Create cluster
        cluster = InfraCluster(
            cluster_id=cluster_id,
            kind="vpn_exit",
            confidence=0.6,
            window_start=tw_start,
            window_end=tw_end,
            first_seen=tw_start,
            last_seen=tw_end,
            member_count=len(ips),
            summary_json={
                "endpoint": endpoint,
                "ip_count": len(ips),
                "reason": "endpoint_overlap",
                "window_minutes": minutes,
                "providers": sorted(list(endpoint_to_providers.get(endpoint, []))),
                "time_spread_seconds": None,
            },
        )
        times = endpoint_to_times.get(endpoint, [])
        if times:
            span = (max(times) - min(times)).total_seconds()
            cluster.summary_json["time_spread_seconds"] = span
        db.add(cluster)

        # Members
        for ip in ips:
            db.add(
                InfraClusterMember(
                    cluster_id=cluster_id,
                    entity_key=f"ip:{ip}",
                    first_seen=tw_start,
                    last_seen=tw_end,
                    event_count=1,
                    meta_json={"endpoint": endpoint, "role": "vpn_exit"},
                )
            )

        # Evidence
        reasons = ["ENDPOINT_OVERLAP"]
        provs = endpoint_to_providers.get(endpoint, set())
        if provs:
            reasons.append("PROVIDER_MATCH")
        if endpoint_to_times.get(endpoint):
            reasons.append("TIME_OVERLAP")

        db.add(
            InfraClusterEvidence(
                evidence_id=str(uuid.uuid4()),
                cluster_id=cluster_id,
                a_entity_key=None,
                b_entity_key=None,
                reason_code="ENDPOINT_OVERLAP",
                score=0.6,
                event_hashes=[],
                source_ids=[],
                details_json={
                    "endpoint": endpoint,
                    "ips": sorted(list(ips)),
                    "providers": sorted(list(provs)),
                    "reason_codes": reasons,
                    "window_minutes": minutes,
                },
                created_at=utcnow(),
            )
        )

        created += 1

    db.commit()
    return created


def main():
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--minutes", type=int, default=60)
    p.add_argument("--min-ips", type=int, default=2)
    args = p.parse_args()

    db = SessionLocal()
    try:
        n = run_once(db=db, minutes=args.minutes, min_ips=args.min_ips)
        print(f"vpn_cluster_worker created_clusters={n}")
    finally:
        db.close()


if __name__ == "__main__":
    main()

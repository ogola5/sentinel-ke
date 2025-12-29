# backend/app/api/infra_clusters.py
from __future__ import annotations

import uuid
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.search.opensearch import get_client
from app.search.bootstrap import ensure_events_index

from app.analytics.infra_windows import last_minutes, between
from app.analytics.infra_similarity import fetch_ip_profiles, build_clusters

from app.ledger.infra_clusters import InfraCluster, InfraClusterMember
from app.ledger.infra_evidence import InfraClusterEvidence


router = APIRouter(prefix="/v1/infra", tags=["infra-clusters"])


def _uuid() -> str:
    return str(uuid.uuid4())


@router.get("/clusters")
def list_clusters(
    kind: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    q = db.query(InfraCluster)
    if kind:
        q = q.filter(InfraCluster.kind == kind)
    rows = q.order_by(InfraCluster.created_at.desc()).limit(limit).all()

    return {
        "items": [
            {
                "cluster_id": r.cluster_id,
                "kind": r.kind,
                "confidence": r.confidence,
                "member_count": r.member_count,
                "window_start": r.window_start.isoformat() if r.window_start else None,
                "window_end": r.window_end.isoformat() if r.window_end else None,
                "first_seen": r.first_seen.isoformat() if r.first_seen else None,
                "last_seen": r.last_seen.isoformat() if r.last_seen else None,
                "summary": r.summary_json,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
    }


@router.get("/clusters/{cluster_id}")
def get_cluster(
    cluster_id: str,
    db: Session = Depends(get_db),
):
    cluster = db.query(InfraCluster).filter(InfraCluster.cluster_id == cluster_id).first()
    if not cluster:
        raise HTTPException(status_code=404, detail="cluster not found")

    members = (
        db.query(InfraClusterMember)
        .filter(InfraClusterMember.cluster_id == cluster_id)
        .order_by(InfraClusterMember.event_count.desc())
        .all()
    )

    evidence = (
        db.query(InfraClusterEvidence)
        .filter(InfraClusterEvidence.cluster_id == cluster_id)
        .order_by(InfraClusterEvidence.score.desc())
        .limit(200)
        .all()
    )

    return {
        "cluster": {
            "cluster_id": cluster.cluster_id,
            "kind": cluster.kind,
            "confidence": cluster.confidence,
            "member_count": cluster.member_count,
            "window_start": cluster.window_start.isoformat() if cluster.window_start else None,
            "window_end": cluster.window_end.isoformat() if cluster.window_end else None,
            "first_seen": cluster.first_seen.isoformat() if cluster.first_seen else None,
            "last_seen": cluster.last_seen.isoformat() if cluster.last_seen else None,
            "summary": cluster.summary_json,
            "created_at": cluster.created_at.isoformat() if cluster.created_at else None,
        },
        "members": [
            {
                "entity_key": m.entity_key,
                "first_seen": m.first_seen.isoformat() if m.first_seen else None,
                "last_seen": m.last_seen.isoformat() if m.last_seen else None,
                "event_count": m.event_count,
                "meta": m.meta_json,
            }
            for m in members
        ],
        "why_linked": [
            {
                "evidence_id": e.evidence_id,
                "reason_code": e.reason_code,
                "score": e.score,
                "details": e.details_json,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in evidence
        ],
    }


@router.post("/rebuild")
def rebuild_clusters(
    minutes: int = Query(60, ge=5, le=24 * 60),
    # Optional explicit window (ISO) if you want deterministic demo replays
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    kind: str = Query("vpn_exit"),
    max_ips: int = Query(120, ge=10, le=300),
    db: Session = Depends(get_db),
):
    # Choose window
    if start and end:
        tw = between(start, end)
    else:
        tw = last_minutes(minutes)

    # Pull IP profiles from OpenSearch
    client = get_client()
    index = ensure_events_index(client)
    profiles = fetch_ip_profiles(client, index=index, time_range=tw.to_opensearch_range(), max_ips=max_ips)

    if len(profiles) < 2:
        return {
            "window": {"start": tw.start.isoformat(), "end": tw.end.isoformat()},
            "clusters_created": 0,
            "note": "not enough IPs in window to cluster",
        }

    # Cluster from overlaps
    clusters, edge_evidence = build_clusters(profiles)

    created_ids: List[str] = []

    for ips in clusters:
        cluster_id = _uuid()

        # cluster summary
        endpoints_union = set()
        services_union = set()
        providers_union = set()
        domains_union = set()
        first_seen = None
        last_seen = None
        total_events = 0

        for ip in ips:
            p = profiles[ip]
            endpoints_union |= p.endpoints
            services_union |= p.services
            providers_union |= p.providers
            domains_union |= p.domains
            total_events += p.event_count

            # string timestamps from OpenSearch; keep them as strings in member meta
            # for cluster-level first/last, store the window bounds (safe + deterministic)
            # (You can improve this later when you store per-ip min/max as datetimes.)

        # confidence: simple function for MVP
        base = 0.45
        base += 0.15 if len(services_union) > 0 else 0.0
        base += 0.15 if len(endpoints_union) > 0 else 0.0
        base += 0.10 if len(providers_union) > 0 else 0.0
        base += 0.05 if len(ips) >= 5 else 0.0
        confidence = min(0.95, base)

        cluster_row = InfraCluster(
            cluster_id=cluster_id,
            kind=kind,
            confidence=confidence,
            window_start=tw.start,
            window_end=tw.end,
            first_seen=tw.start,
            last_seen=tw.end,
            member_count=len(ips),
            summary_json={
                "ip_count": len(ips),
                "total_events": total_events,
                "unique_endpoints": len(endpoints_union),
                "unique_services": len(services_union),
                "unique_domains": len(domains_union),
                "providers": sorted(list(providers_union))[:10],
                "top_endpoints": sorted(list(endpoints_union))[:10],
                "top_services": sorted(list(services_union))[:10],
            },
        )
        db.add(cluster_row)

        # members
        for ip in ips:
            p = profiles[ip]
            db.add(
                InfraClusterMember(
                    cluster_id=cluster_id,
                    entity_key=f"ip:{ip}",
                    first_seen=tw.start,
                    last_seen=tw.end,
                    event_count=p.event_count,
                    meta_json={
                        "endpoints": sorted(list(p.endpoints))[:20],
                        "services": sorted(list(p.services))[:20],
                        "domains": sorted(list(p.domains))[:20],
                        "providers": sorted(list(p.providers))[:10],
                        "first_seen": p.first_seen,
                        "last_seen": p.last_seen,
                    },
                )
            )

        # evidence (compress edge evidence into cluster evidence)
        # Keep it judge-safe: top overlaps + reason codes + small lists.
        kept = 0
        for ev in sorted(edge_evidence, key=lambda x: x.get("score", 0.0), reverse=True):
            if kept >= 50:
                break
            if ev["a"] in ips and ev["b"] in ips:
                db.add(
                    InfraClusterEvidence(
                        evidence_id=_uuid(),
                        cluster_id=cluster_id,
                        reason_code=ev.get("reason_code", "OVERLAP"),
                        score=float(ev.get("score", 0.0)),
                        details_json=ev.get("details", {}),
                    )
                )
                kept += 1

        created_ids.append(cluster_id)

    db.commit()

    return {
        "window": {"start": tw.start.isoformat(), "end": tw.end.isoformat()},
        "clusters_created": len(created_ids),
        "cluster_ids": created_ids,
        "inputs": {"max_ips": max_ips, "kind": kind},
    }

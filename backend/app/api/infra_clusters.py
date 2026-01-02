# backend/app/api/infra_clusters.py
from __future__ import annotations

import hashlib
import uuid
from typing import Optional, List, Dict, Any, Tuple
from app.graph.neo4j_driver import get_driver
from app.graph.neo4j_schema import ensure_schema
import os
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.api.deps import get_db, pagination_params
from app.search.opensearch import get_client
from app.search.bootstrap import ensure_events_index

from app.analytics.infra_windows import last_minutes, between
from app.analytics.infra_similarity import fetch_ip_profiles, build_clusters

from app.ledger.infra_clusters import InfraCluster, InfraClusterMember
from app.ledger.infra_evidence import InfraClusterEvidence
from app.infra.service import InfraClusterService
from app.graph.infra_projection import project_infra_cluster
import app.graph.neo4j_worker as neo4j_worker

router = APIRouter(prefix="/v1/infra", tags=["infra-clusters"])


def _uuid() -> str:
    return str(uuid.uuid4())


def _stable_fingerprint(parts: List[str]) -> str:
    """
    Deterministic fingerprint (stable across runs).
    """
    h = hashlib.sha256()
    for p in parts:
        h.update(p.encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()


def _compute_cluster_key(*, kind: str, ips: List[str], summary: Dict[str, Any]) -> str:
    """
    Semantic identity for 'seen before'. Should be mostly window-independent.

    MVP approach:
      key = sha256(kind + sorted_ips + top endpoints/services/providers + domains)
    """
    ips_sorted = sorted(set(ips))
    providers = summary.get("providers") or []
    top_endpoints = summary.get("top_endpoints") or []
    top_services = summary.get("top_services") or []
    # domains can be large; only include a capped set for fingerprint stability
    domains = summary.get("top_domains") or []

    parts = (
        [f"kind:{kind}"]
        + [f"ip:{ip}" for ip in ips_sorted]
        + [f"provider:{p}" for p in sorted(set(providers))[:20]]
        + [f"endpoint:{e}" for e in sorted(set(top_endpoints))[:50]]
        + [f"service:{s}" for s in sorted(set(top_services))[:50]]
        + [f"domain:{d}" for d in sorted(set(domains))[:50]]
    )
    return f"{kind}:{_stable_fingerprint(parts)[:32]}"


@router.get("/clusters")
def list_clusters(
    kind: Optional[str] = Query(None),
    pagination: dict = Depends(pagination_params),
    db: Session = Depends(get_db),
):
    q = db.query(InfraCluster)
    if kind:
        q = q.filter(InfraCluster.kind == kind)
    rows = (
        q.order_by(InfraCluster.created_at.desc())
        .offset(pagination["offset"])
        .limit(pagination["limit"])
        .all()
    )

    return {
        "limit": pagination["limit"],
        "offset": pagination["offset"],
        "items": [
            {
                "cluster_id": r.cluster_id,
                "cluster_key": r.cluster_key,
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
            "cluster_key": cluster.cluster_key,
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
                "a_entity_key": e.a_entity_key,
                "b_entity_key": e.b_entity_key,
                "reason_code": e.reason_code,
                "score": e.score,
                "event_hashes": e.event_hashes,
                "source_ids": e.source_ids,
                "details": e.details_json,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in evidence
        ],
    }


def _discover_clusters_layer3(
    *,
    minutes: int,
    start: Optional[str],
    end: Optional[str],
    max_ips: int,
) -> Tuple[Any, Dict[str, Any], Dict[str, Any]]:
    """
    LAYER-3 DISCOVERY (kept in repo for Option B):
      OpenSearch -> profiles -> clusters + edge evidence

    Returns:
      (time_window, profiles, discovery_result)
    """
    if start and end:
        tw = between(start, end)
    else:
        tw = last_minutes(minutes)

    client = get_client()
    index = ensure_events_index(client)
    profiles = fetch_ip_profiles(client, index=index, time_range=tw.to_opensearch_range(), max_ips=max_ips)

    if len(profiles) < 2:
        return tw, profiles, {"clusters": [], "edge_evidence": []}

    clusters, edge_evidence = build_clusters(profiles)
    return tw, profiles, {"clusters": clusters, "edge_evidence": edge_evidence}


def _materialize_cluster_layer2(
    *,
    db: Session,
    kind: str,
    tw,
    ips: List[str],
    profiles: Dict[str, Any],
    edge_evidence: List[Dict[str, Any]],
    confidence: float,
    max_member_meta: int = 20,
    max_cluster_evidence: int = 50,
) -> str:
    """
    LAYER-2 MATERIALIZATION:
      Persist cluster + members + why-linked evidence into Postgres.

    Idempotency:
      - compute cluster_key
      - if cluster_key exists: update + replace members/evidence deterministically
    """
    # summary
    endpoints_union = set()
    services_union = set()
    providers_union = set()
    domains_union = set()
    total_events = 0

    for ip in ips:
        p = profiles[ip]
        endpoints_union |= set(getattr(p, "endpoints", set()) or [])
        services_union |= set(getattr(p, "services", set()) or [])
        providers_union |= set(getattr(p, "providers", set()) or [])
        domains_union |= set(getattr(p, "domains", set()) or [])
        total_events += int(getattr(p, "event_count", 0) or 0)

    summary = {
        "ip_count": len(ips),
        "total_events": total_events,
        "unique_endpoints": len(endpoints_union),
        "unique_services": len(services_union),
        "unique_domains": len(domains_union),
        "providers": sorted(list(providers_union))[:10],
        "top_endpoints": sorted(list(endpoints_union))[:10],
        "top_services": sorted(list(services_union))[:10],
        "top_domains": sorted(list(domains_union))[:10],
    }

    cluster_key = _compute_cluster_key(kind=kind, ips=ips, summary=summary)

    # reuse if exists
    existing = db.query(InfraCluster).filter(InfraCluster.cluster_key == cluster_key).first()
    if existing:
        cluster_id = existing.cluster_id
        # update cluster metadata (keep created_at stable)
        existing.kind = kind
        existing.confidence = confidence
        existing.window_start = tw.start
        existing.window_end = tw.end
        existing.first_seen = tw.start
        existing.last_seen = tw.end
        existing.member_count = len(ips)
        existing.summary_json = summary

        # replace members/evidence deterministically (MVP)
        db.query(InfraClusterMember).filter(InfraClusterMember.cluster_id == cluster_id).delete(synchronize_session=False)
        db.query(InfraClusterEvidence).filter(InfraClusterEvidence.cluster_id == cluster_id).delete(synchronize_session=False)
    else:
        cluster_id = _uuid()
        db.add(
            InfraCluster(
                cluster_id=cluster_id,
                cluster_key=cluster_key,
                kind=kind,
                confidence=confidence,
                window_start=tw.start,
                window_end=tw.end,
                first_seen=tw.start,
                last_seen=tw.end,
                member_count=len(ips),
                summary_json=summary,
            )
        )

    # members
    for ip in ips:
        p = profiles[ip]
        db.add(
            InfraClusterMember(
                cluster_id=cluster_id,
                entity_key=f"ip:{ip}",
                first_seen=tw.start,
                last_seen=tw.end,
                event_count=int(getattr(p, "event_count", 0) or 0),
                meta_json={
                    "endpoints": sorted(list(getattr(p, "endpoints", set()) or []))[:max_member_meta],
                    "services": sorted(list(getattr(p, "services", set()) or []))[:max_member_meta],
                    "domains": sorted(list(getattr(p, "domains", set()) or []))[:max_member_meta],
                    "providers": sorted(list(getattr(p, "providers", set()) or []))[:10],
                    "first_seen": getattr(p, "first_seen", None),
                    "last_seen": getattr(p, "last_seen", None),
                    "role": "exit_node" if kind == "vpn_exit" else "bot_source",
                },
            )
        )

    # evidence: keep top-N, store pair context (a/b) and any event hashes if provided in details
    kept = 0
    for ev in sorted(edge_evidence, key=lambda x: float(x.get("score", 0.0) or 0.0), reverse=True):
        if kept >= max_cluster_evidence:
            break
        a = ev.get("a")
        b = ev.get("b")
        if a in ips and b in ips:
            details = ev.get("details", {}) or {}
            event_hashes = details.get("event_hashes") or []
            if not isinstance(event_hashes, list):
                event_hashes = []
            # cap
            event_hashes = [str(x) for x in event_hashes[:25]]

            db.add(
                InfraClusterEvidence(
                    evidence_id=_uuid(),
                    cluster_id=cluster_id,
                    a_entity_key=f"ip:{a}",
                    b_entity_key=f"ip:{b}",
                    reason_code=str(ev.get("reason_code", "OVERLAP") or "OVERLAP"),
                    score=float(ev.get("score", 0.0) or 0.0),
                    event_hashes=event_hashes,
                    source_ids=details.get("source_ids") or [],
                    details_json=details,
                )
            )
            kept += 1

    return cluster_id



@router.post("/rebuild")
def rebuild_clusters(
    minutes: int = Query(60, ge=5, le=24 * 60),
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    kind: str = Query("vpn_exit"),
    max_ips: int = Query(120, ge=10, le=300),
    db: Session = Depends(get_db),
):
    """
    OPTION B: KEEP endpoint, but treat it as LAYER-3 discovery + LAYER-2 materialization.

    - Discovery uses OpenSearch + similarity clustering
    - Materialization persists the output into Postgres
    - cluster_key enforces reuse and prevents duplicates across runs
    """
    tw, profiles, discovery = _discover_clusters_layer3(minutes=minutes, start=start, end=end, max_ips=max_ips)
    clusters: List[List[str]] = discovery["clusters"]
    edge_evidence: List[Dict[str, Any]] = discovery["edge_evidence"]

    if not clusters:
        return {
            "window": {"start": tw.start.isoformat(), "end": tw.end.isoformat()},
            "clusters_created": 0,
            "note": "not enough IPs in window to cluster",
        }

    created_ids: List[str] = []

    for ips in clusters:
        # confidence (still computed here; this endpoint is Layer-3)
        # minimal, stable scoring (no random)
        endpoints_union = set()
        services_union = set()
        providers_union = set()
        domains_union = set()
        total_events = 0
        for ip in ips:
            p = profiles[ip]
            endpoints_union |= set(getattr(p, "endpoints", set()) or [])
            services_union |= set(getattr(p, "services", set()) or [])
            providers_union |= set(getattr(p, "providers", set()) or [])
            domains_union |= set(getattr(p, "domains", set()) or [])
            total_events += int(getattr(p, "event_count", 0) or 0)

        base = 0.45
        base += 0.15 if len(services_union) > 0 else 0.0
        base += 0.15 if len(endpoints_union) > 0 else 0.0
        base += 0.10 if len(providers_union) > 0 else 0.0
        base += 0.05 if len(ips) >= 5 else 0.0
        confidence = min(0.95, base)

        try:
            cid = _materialize_cluster_layer2(
                db=db,
                kind=kind,
                tw=tw,
                ips=ips,
                profiles=profiles,
                edge_evidence=edge_evidence,
                confidence=confidence,
            )
            created_ids.append(cid)
            db.commit()
        except IntegrityError:
            db.rollback()
            # In case of a race/duplicate cluster_key. Safe to continue.
            continue

    return {
        "window": {"start": tw.start.isoformat(), "end": tw.end.isoformat()},
        "clusters_created": len(created_ids),
        "cluster_ids": created_ids,
        "inputs": {"max_ips": max_ips, "kind": kind},
    }
@router.post("/from-campaign/{campaign_id}")
def build_from_campaign(
    campaign_id: str,
    db: Session = Depends(get_db),
):
    svc = InfraClusterService(db)
    try:
        cluster_id = svc.materialize_from_campaign(campaign_id)
        db.commit()   # ✅ THIS WAS MISSING
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        db.rollback()
        raise

    return {
        "campaign_id": campaign_id,
        "cluster_id": cluster_id,
        "status": "created",
    }

# @router.post("/clusters/{cluster_id}/project")
# def project_cluster(
#     cluster_id: str,
#     db: Session = Depends(get_db),
# ):
#     # 1. Build graph delta from Postgres
#     delta = project_infra_cluster(db=db, cluster_id=cluster_id)

#     # 2. Prepare Neo4j context (same as worker)
#     database = os.getenv("NEO4J_DATABASE", "neo4j")
#     driver = get_driver()
#     ensure_schema(driver, database)

#     # 3. Apply delta
#     neo4j_worker.apply_delta(
#         driver,
#         database,
#         event_hash=delta.event_hash,
#         nodes=[n.__dict__ for n in delta.nodes],
#         edges=[e.__dict__ for e in delta.edges],
#         last_seen_iso=delta.created_at.replace(tzinfo=None).isoformat() + "Z",
#     )

#     driver.close()

#     return {
#         "cluster_id": cluster_id,
#         "status": "projected",
#     }

@router.post("/clusters/{cluster_id}/project")
def project_cluster(
    cluster_id: str,
    db: Session = Depends(get_db),
):
    # 1. Build graph delta from Postgres
    delta = project_infra_cluster(db=db, cluster_id=cluster_id)

    # 2. Neo4j context
    database = os.getenv("NEO4J_DATABASE", "neo4j")
    driver = get_driver()
    ensure_schema(driver, database)

    # 3. Apply delta
    neo4j_worker.apply_delta(
        driver,
        database,
        event_hash=delta.event_hash,
        nodes=[n.__dict__ for n in delta.nodes],
        edges=[e.__dict__ for e in delta.edges],
        last_seen_iso=datetime.now(timezone.utc)
        .isoformat()
        .replace("+00:00", "Z"),
    )

    driver.close()

    return {
        "cluster_id": cluster_id,
        "status": "projected",
    }

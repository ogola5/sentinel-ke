from __future__ import annotations

from sqlalchemy.orm import Session

from app.graph.ontology import (
    NodeRef,
    make_node,
    make_edge,
    dedupe_nodes,
    dedupe_edges,
)
from app.ledger.infra_clusters import InfraCluster, InfraClusterMember
from app.ledger.infra_evidence import InfraClusterEvidence
from app.graph.projector import GraphDelta


def project_infra_cluster(*, db: Session, cluster_id: str) -> GraphDelta:
    cluster = (
        db.query(InfraCluster)
        .filter(InfraCluster.cluster_id == cluster_id)
        .first()
    )
    if not cluster:
        raise ValueError("cluster not found")

    members = (
        db.query(InfraClusterMember)
        .filter(InfraClusterMember.cluster_id == cluster_id)
        .all()
    )

    evidence = (
        db.query(InfraClusterEvidence)
        .filter(InfraClusterEvidence.cluster_id == cluster_id)
        .all()
    )

    nodes = []
    edges = []

    # Cluster node
    cluster_ref = NodeRef("InfraCluster", cluster.cluster_id)
    nodes.append(
        make_node(
            cluster_ref,
            kind=cluster.kind,
            confidence=cluster.confidence,
            member_count=cluster.member_count,
            window_start=cluster.window_start.isoformat() if cluster.window_start else None,
            window_end=cluster.window_end.isoformat() if cluster.window_end else None,
        )
    )

    # Members
    for m in members:
        # entity_key = "ip:1.2.3.4"
        _, ip = m.entity_key.split(":", 1)
        ip_ref = NodeRef("IP", ip)

        nodes.append(make_node(ip_ref))

        edges.append(
            make_edge(
                "MEMBER_OF",
                ip_ref,
                cluster_ref,
                evidence=[],
                event_count=m.event_count,
                first_seen=m.first_seen.isoformat() if m.first_seen else None,
                last_seen=m.last_seen.isoformat() if m.last_seen else None,
            )
        )

    # Optional: evidence as edges (keep small)
    for e in evidence[:50]:
        edges.append(
            make_edge(
                "SUPPORTED_BY",
                cluster_ref,
                cluster_ref,
                evidence=[],
                reason_code=e.reason_code,
                score=e.score,
            )
        )

    return GraphDelta(
        event_hash=f"infra_cluster:{cluster_id}",
        nodes=dedupe_nodes(nodes),
        edges=dedupe_edges(edges),
    )

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Dict, List, Set

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.campaign.models import Campaign, CampaignEntity
from app.graph.repository import GraphDeltaRepository
from app.graph.ontology import NodeRef, make_node, make_edge, dedupe_nodes, dedupe_edges
from app.graph.projector import GraphDelta
from app.ledger.db import SessionLocal
from app.ledger.infra_clusters import InfraCluster
from app.db.base import utcnow


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _find_candidate_clusters(db: Session, min_campaigns: int = 2) -> List[Dict]:
    rows = db.execute(
        text(
            """
            SELECT
                replace(entity_key, 'infra_cluster:', '') AS cluster_id,
                array_agg(DISTINCT campaign_id) AS campaigns,
                min(last_seen) AS first_seen,
                max(last_seen) AS last_seen
            FROM campaign_entity
            WHERE entity_key LIKE 'infra_cluster:%'
            GROUP BY cluster_id
            HAVING count(DISTINCT campaign_id) >= :min_campaigns
            """
        ),
        {"min_campaigns": min_campaigns},
    ).fetchall()
    return [
        {
            "cluster_id": r[0],
            "campaign_ids": list(r[1] or []),
            "first_seen": r[2],
            "last_seen": r[3],
        }
        for r in rows
    ]


def _campaign_exists(db: Session, cluster_id: str) -> Campaign | None:
    return (
        db.query(Campaign)
        .filter(Campaign.type == "COORDINATED_INFRA", Campaign.primary_key == cluster_id)
        .first()
    )


def _project_campaign_delta(*, campaign: Campaign, cluster: InfraCluster) -> GraphDelta:
    nodes = [
        make_node(
            NodeRef("Campaign", str(campaign.id)),
            type=campaign.type,
            status=campaign.status,
            score=campaign.score,
            first_seen=campaign.first_seen.isoformat(),
            last_seen=campaign.last_seen.isoformat(),
        ),
        make_node(
            NodeRef("InfraCluster", cluster.cluster_id),
            kind=cluster.kind,
            confidence=cluster.confidence,
            member_count=cluster.member_count,
        ),
    ]
    edges = [
        make_edge(
            "USES_INFRA",
            NodeRef("Campaign", str(campaign.id)),
            NodeRef("InfraCluster", cluster.cluster_id),
            evidence=[],
            confidence=campaign.score,
        )
    ]
    return GraphDelta(
        event_hash=f"campaign_detect:{campaign.id}",
        nodes=dedupe_nodes(nodes),
        edges=dedupe_edges(edges),
    )


def run_once(db: Session, *, min_campaigns: int = 2, max_new: int = 50) -> int:
    candidates = _find_candidate_clusters(db, min_campaigns=min_campaigns)
    if not candidates:
        return 0

    created = 0
    repo = GraphDeltaRepository(db)

    for cand in candidates:
        if created >= max_new:
            break
        cluster_id = cand["cluster_id"]
        existing = _campaign_exists(db, cluster_id)
        if existing:
            continue

        cluster = db.query(InfraCluster).filter(InfraCluster.cluster_id == cluster_id).first()
        if not cluster:
            continue

        ts = _now()
        camp = Campaign(
            id=uuid.uuid4(),
            type="COORDINATED_INFRA",
            primary_key=cluster_id,
            status="active",
            rule_version="coord.infra.v1",
            first_seen=cand["first_seen"] or ts,
            last_seen=cand["last_seen"] or ts,
            event_count=0,
            score=0.75,
            stats={
                "member_campaigns": cand["campaign_ids"],
                "cluster_id": cluster_id,
            },
        )
        db.add(camp)
        db.flush()

        # Link the detected campaign to the infra cluster
        db.add(
            CampaignEntity(
                campaign_id=camp.id,
                entity_key=f"infra_cluster:{cluster_id}",
                entity_type="InfraCluster",
                role="infrastructure",
                last_seen=cand["last_seen"] or ts,
            )
        )

        # Project to Neo4j via GraphDeltaLog
        delta = _project_campaign_delta(campaign=camp, cluster=cluster)
        repo.insert_delta(
            event_hash=delta.event_hash,
            nodes=[n.__dict__ for n in delta.nodes],
            edges=[e.__dict__ for e in delta.edges],
        )

        created += 1

    db.commit()
    return created


def main():
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--min-campaigns", type=int, default=2)
    p.add_argument("--max-new", type=int, default=50)
    args = p.parse_args()

    db = SessionLocal()
    try:
        n = run_once(db=db, min_campaigns=args.min_campaigns, max_new=args.max_new)
        print(f"campaign_detect_worker created={n}")
    finally:
        db.close()


if __name__ == "__main__":
    main()

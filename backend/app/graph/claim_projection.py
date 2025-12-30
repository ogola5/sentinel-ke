# backend/app/graph/claim_projection.py
from __future__ import annotations

from sqlalchemy.orm import Session

from app.graph.ontology import NodeRef, make_node, make_edge, dedupe_nodes, dedupe_edges
from app.graph.projector import GraphDelta
from app.campaign.claims import CampaignClaim
from app.campaign.models import Campaign
from app.ledger.infra_clusters import InfraCluster


def project_claim_to_delta(*, db: Session, claim: CampaignClaim) -> GraphDelta:
    """
    Projection-only: Claim (canonical in Postgres) -> GraphDelta.
    """
    subj = db.query(Campaign).filter(Campaign.id == claim.subject_campaign_id).first()
    obj = db.query(Campaign).filter(Campaign.id == claim.object_campaign_id).first()

    if not subj or not obj:
        raise ValueError("campaign(s) missing for claim projection")

    nodes = []
    edges = []

    subj_ref = NodeRef("Campaign", str(subj.id))
    obj_ref = NodeRef("Campaign", str(obj.id))

    nodes.append(make_node(subj_ref, type=subj.type, status=subj.status, score=subj.score))
    nodes.append(make_node(obj_ref, type=obj.type, status=obj.status, score=obj.score))

    # Campaign↔Campaign support edge (the claim itself)
    edges.append(
        make_edge(
            "SUPPORTED_BY",
            subj_ref,
            obj_ref,
            evidence=list(claim.evidence_hashes or []),
            claim_type=claim.claim_type,
            confidence=claim.confidence,
            reason_codes=list(claim.reason_codes or []),
            window=claim.window,
            window_start=claim.window_start.isoformat(),
            window_end=claim.window_end.isoformat(),
        )
    )

    # Link campaigns to infra clusters referenced by the claim
    for cluster_id in (claim.infra_cluster_ids or []):
        cl = db.query(InfraCluster).filter(InfraCluster.cluster_id == str(cluster_id)).first()
        if not cl:
            continue
        cl_ref = NodeRef("InfraCluster", cl.cluster_id)
        nodes.append(
            make_node(
                cl_ref,
                kind=cl.kind,
                confidence=cl.confidence,
                member_count=cl.member_count,
                window_start=cl.window_start.isoformat() if cl.window_start else None,
                window_end=cl.window_end.isoformat() if cl.window_end else None,
            )
        )

        # Campaign -> InfraCluster
        edges.append(
            make_edge(
                "USES_INFRA",
                subj_ref,
                cl_ref,
                evidence=list(claim.evidence_hashes or []),
                claim_type=claim.claim_type,
                confidence=claim.confidence,
            )
        )
        edges.append(
            make_edge(
                "USES_INFRA",
                obj_ref,
                cl_ref,
                evidence=list(claim.evidence_hashes or []),
                claim_type=claim.claim_type,
                confidence=claim.confidence,
            )
        )

    return GraphDelta(
        event_hash=f"claim:{str(claim.id)}",
        nodes=dedupe_nodes(nodes),
        edges=dedupe_edges(edges),
    )

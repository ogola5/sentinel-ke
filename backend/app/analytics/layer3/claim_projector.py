# backend/app/analytics/layer3/claim_projector.py
from __future__ import annotations

from typing import List

from sqlalchemy.orm import Session

from app.graph.ontology import NodeRef, make_node, make_edge, dedupe_nodes, dedupe_edges
from app.graph.projector import GraphDelta


def project_campaign_claim(
    *,
    claim_row,
) -> GraphDelta:
    """
    campaign_claim -> GraphDelta
    """

    nodes = []
    edges = []

    a_ref = NodeRef("Campaign", str(claim_row.subject_campaign_id))
    b_ref = NodeRef("Campaign", str(claim_row.object_campaign_id))

    nodes.append(make_node(a_ref))
    nodes.append(make_node(b_ref))

    edges.append(
        make_edge(
            "SUPPORTED_BY",
            a_ref,
            b_ref,
            evidence=claim_row.evidence_hashes or [],
            claim_type=claim_row.claim_type,
            confidence=claim_row.confidence,
            window_key=claim_row.window_key,
        )
    )

    return GraphDelta(
        event_hash=f"campaign_claim:{claim_row.id}",
        nodes=dedupe_nodes(nodes),
        edges=dedupe_edges(edges),
    )

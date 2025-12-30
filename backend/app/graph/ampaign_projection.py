# backend/app/graph/campaign_projection.py
from __future__ import annotations

from sqlalchemy.orm import Session

from app.graph.projector import GraphDelta
from app.analytics.layer3.claim_projector import project_campaign_claim
from app.graph.models import GraphDeltaLog


def project_claims_to_deltas(*, db: Session, limit: int = 500) -> int:
    """
    Persist campaign_claim → GraphDeltaLog
    """

    rows = db.execute(
        """
        SELECT *
        FROM campaign_claim
        ORDER BY created_at ASC
        LIMIT :limit
        """,
        {"limit": limit},
    ).fetchall()

    written = 0

    for r in rows:
        delta = project_campaign_claim(claim_row=r)

        db.add(
            GraphDeltaLog(
                event_hash=delta.event_hash,
                nodes_json=[n.__dict__ for n in delta.nodes],
                edges_json=[e.__dict__ for e in delta.edges],
            )
        )
        written += 1

    return written

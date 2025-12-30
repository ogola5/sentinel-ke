# backend/app/analytics/layer3/claim_projection_worker.py
from __future__ import annotations

from sqlalchemy.orm import Session

from app.graph.delta_store import DeltaStore
from app.campaign.models_claim import CampaignClaim
from app.analytics.layer3.claim_projector import project_campaign_claim
from app.graph.models import GraphDeltaLog


CURSOR_NAME = "layer3_claims"


def project_claims_once(
    *,
    db: Session,
    batch_size: int = 200,
) -> int:
    """
    Project campaign_claim → GraphDeltaLog
    using monotonic created_at cursor.

    Idempotent.
    Replay-safe.
    """

    store = DeltaStore(db)
    after = store.get_cursor(CURSOR_NAME)

    q = (
        db.query(CampaignClaim)
        .order_by(CampaignClaim.created_at.asc())
        .limit(batch_size)
    )

    if after:
        q = q.filter(CampaignClaim.created_at > after)

    rows = q.all()
    if not rows:
        return 0

    processed = 0
    last_ts = None

    for claim in rows:
        delta = project_campaign_claim(claim_row=claim)

        db.add(
            GraphDeltaLog(
                event_hash=delta.event_hash,
                nodes_json=[n.__dict__ for n in delta.nodes],
                edges_json=[e.__dict__ for e in delta.edges],
            )
        )

        last_ts = claim.created_at
        processed += 1

    # advance cursor only after successful batch
    store.set_cursor(last_ts, CURSOR_NAME)

    return processed

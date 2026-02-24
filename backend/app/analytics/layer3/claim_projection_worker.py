# backend/app/analytics/layer3/claim_projection_worker.py
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.graph.delta_store import DeltaStore
from app.campaign.claims import CampaignClaim
from app.graph.claim_projection import project_claim_to_delta
from app.graph.models import GraphDeltaLog


CURSOR_NAME = "layer3_claims"
log = logging.getLogger("sentinel.claim_projection_worker")


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
        try:
            delta = project_claim_to_delta(db=db, claim=claim)
        except Exception as exc:
            log.warning("claim_projection_failed claim_id=%s error=%s", claim.id, exc)
            last_ts = claim.created_at
            continue

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

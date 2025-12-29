# app/api/campaign_evidence.py
from __future__ import annotations

from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.ledger.db import get_db
from app.campaign.models import Campaign, CampaignEvent, CampaignEntity

router = APIRouter(
    prefix="/v1/campaigns",
    tags=["campaign-evidence"],
)


@router.get("/{campaign_id}/evidence")
def campaign_evidence(
    campaign_id: UUID,
    limit: int = Query(default=200, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    campaign = (
        db.query(Campaign)
        .filter(Campaign.id == campaign_id)
        .first()
    )
    if not campaign:
        raise HTTPException(status_code=404, detail="campaign_not_found")

    events = (
        db.query(CampaignEvent)
        .filter(CampaignEvent.campaign_id == campaign_id)
        .order_by(CampaignEvent.occurred_at.asc())
        .limit(limit)
        .all()
    )

    entities = (
        db.query(CampaignEntity)
        .filter(CampaignEntity.campaign_id == campaign_id)
        .all()
    )

    # index entities by key
    entity_map = {}
    for e in entities:
        entity_map.setdefault(e.entity_key, []).append(
            {
                "type": e.entity_type,
                "role": e.role,
                "last_seen": e.last_seen.isoformat(),
            }
        )

    return {
        "campaign": {
            "id": str(campaign.id),
            "type": campaign.type,
            "primary_key": campaign.primary_key,
            "score": campaign.score,
            "status": campaign.status,
        },
        "evidence": [
            {
                "event_hash": ev.event_hash,
                "occurred_at": ev.occurred_at.isoformat(),
                "entities": entity_map,
            }
            for ev in events
        ],
        "count": len(events),
    }

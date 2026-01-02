# app/api/campaigns.py
from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.ledger.db import get_db
from app.api.deps import pagination_params
from app.campaign.models import Campaign, CampaignEvent, CampaignEntity
from app.campaign.risk import CampaignRisk

router = APIRouter(prefix="/v1/campaigns", tags=["campaigns"])


# -------------------------------------------------------------------
# List campaigns (frontend list view)
# -------------------------------------------------------------------
@router.get("")
def list_campaigns(
    status: Optional[str] = Query(
        default=None,
        description="Filter by status: active | dormant | closed",
    ),
    pagination: dict = Depends(pagination_params),
    db: Session = Depends(get_db),
):
    q = db.query(Campaign)

    if status:
        q = q.filter(Campaign.status == status)

    rows = q.order_by(Campaign.last_seen.desc()).offset(pagination["offset"]).limit(pagination["limit"]).all()

    return {
        "count": len(rows),
        "limit": pagination["limit"],
        "offset": pagination["offset"],
        "items": [
            {
                "campaign_id": str(c.id),
                "type": c.type,
                "primary_key": c.primary_key,
                "status": c.status,
                "score": c.score,
                "event_count": c.event_count,
                "first_seen": c.first_seen.isoformat(),
                "last_seen": c.last_seen.isoformat(),
                "stats": c.stats,
            }
            for c in rows
        ],
    }


# -------------------------------------------------------------------
# Campaign detail (summary + entities)
# -------------------------------------------------------------------
@router.get("/{campaign_id}")
def get_campaign(
    campaign_id: UUID,
    db: Session = Depends(get_db),
):
    c = (
        db.query(Campaign)
        .filter(Campaign.id == campaign_id)
        .first()
    )

    if not c:
        raise HTTPException(status_code=404, detail="campaign_not_found")

    # Deterministic entity listing
    entities = (
        db.query(
            CampaignEntity.entity_type,
            CampaignEntity.entity_key,
            CampaignEntity.last_seen,
        )
        .filter(CampaignEntity.campaign_id == campaign_id)
        .order_by(CampaignEntity.last_seen.desc())
        .limit(200)
        .all()
    )

    # Entity cardinalities (for UI charts / badges)
    counts = (
        db.query(
            CampaignEntity.entity_type,
            func.count().label("count"),
        )
        .filter(CampaignEntity.campaign_id == campaign_id)
        .group_by(CampaignEntity.entity_type)
        .all()
    )

    return {
        "campaign_id": str(c.id),
        "type": c.type,
        "primary_key": c.primary_key,
        "status": c.status,
        "score": c.score,
        "event_count": c.event_count,
        "first_seen": c.first_seen.isoformat(),
        "last_seen": c.last_seen.isoformat(),
        "stats": c.stats,
        "entity_counts": {t: n for (t, n) in counts},
        "entities": [
            {
                "type": t,
                "key": k,
                "last_seen": ls.isoformat(),
            }
            for (t, k, ls) in entities
        ],
    }


# -------------------------------------------------------------------
# Campaign events (timeline / drill-down)
# -------------------------------------------------------------------
@router.get("/{campaign_id}/events")
def campaign_events(
    campaign_id: UUID,
    pagination: dict = Depends(pagination_params),
    before: Optional[str] = Query(
        default=None,
        description="ISO timestamp cursor for pagination",
    ),
    db: Session = Depends(get_db),
):
    q = (
        db.query(CampaignEvent)
        .filter(CampaignEvent.campaign_id == campaign_id)
    )

    if before:
        q = q.filter(CampaignEvent.occurred_at < before)

    rows = q.order_by(CampaignEvent.occurred_at.desc()).offset(pagination["offset"]).limit(pagination["limit"]).all()

    return {
        "count": len(rows),
        "limit": pagination["limit"],
        "offset": pagination["offset"],
        "items": [
            {
                "event_hash": r.event_hash,
                "occurred_at": r.occurred_at.isoformat(),
            }
            for r in rows
        ],
    }


# -------------------------------------------------------------------
# Campaign risk (blast radius)
# -------------------------------------------------------------------
@router.get("/{campaign_id}/risk")
def campaign_risk(
    campaign_id: UUID,
    pagination: dict = Depends(pagination_params),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(CampaignRisk)
        .filter(CampaignRisk.campaign_id == campaign_id)
        .order_by(CampaignRisk.score.desc(), CampaignRisk.created_at.desc())
        .offset(pagination["offset"])
        .limit(pagination["limit"])
        .all()
    )
    return {
        "count": len(rows),
        "limit": pagination["limit"],
        "offset": pagination["offset"],
        "items": [
            {
                "entity_key": r.entity_key,
                "entity_type": r.entity_type,
                "score": r.score,
                "reason_codes": r.reason_codes,
                "details": r.details_json,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ],
    }

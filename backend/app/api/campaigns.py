# app/api/campaigns.py
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session

from app.ledger.db import SessionLocal
from app.campaign.models import Campaign, CampaignEvent, CampaignEntity


router = APIRouter(prefix="/v1/campaigns", tags=["campaigns"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("")
def list_campaigns(
    status: str = "active",
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(Campaign)
        .filter(Campaign.status == status)
        .order_by(Campaign.last_seen.desc())
        .limit(limit)
        .all()
    )
    return {
        "count": len(rows),
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


@router.get("/{campaign_id}")
def get_campaign(campaign_id: UUID, db: Session = Depends(get_db)):
    c = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="campaign_not_found")

    # top entities (cheap summary)
    entities = (
        db.query(CampaignEntity.entity_type, CampaignEntity.entity_key)
        .filter(CampaignEntity.campaign_id == campaign_id)
        .limit(200)
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
        "entities": [{"type": t, "key": k} for (t, k) in entities],
    }


@router.get("/{campaign_id}/events")
def campaign_events(
    campaign_id: UUID,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(CampaignEvent)
        .filter(CampaignEvent.campaign_id == campaign_id)
        .order_by(CampaignEvent.occurred_at.desc())
        .limit(limit)
        .all()
    )
    return {
        "count": len(rows),
        "items": [
            {"event_hash": r.event_hash, "occurred_at": r.occurred_at.isoformat()}
            for r in rows
        ],
    }

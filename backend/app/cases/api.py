from __future__ import annotations

from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.ledger.db import get_db
from app.cases.builders import build_case_packet
from app.campaign.models import Campaign

router = APIRouter(
    prefix="/v1/cases",
    tags=["cases"],
)


@router.get("/recent")
def list_recent_cases(
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """Return the most recent campaigns that are available for case-packet generation."""
    rows = (
        db.query(Campaign)
        .order_by(Campaign.last_seen.desc())
        .limit(limit)
        .all()
    )
    return {
        "items": [
            {
                "campaign_id": str(r.id),
                "type":        r.type,
                "primary_key": r.primary_key,
                "status":      r.status,
                "score":       float(r.score or 0),
                "event_count": r.event_count or 0,
                "first_seen":  r.first_seen.isoformat() if r.first_seen else None,
                "last_seen":   r.last_seen.isoformat()  if r.last_seen  else None,
            }
            for r in rows
        ],
        "total": len(rows),
    }


@router.post("/from-campaign/{campaign_id}")
def create_case_packet(campaign_id: UUID, db: Session = Depends(get_db)):
    try:
        packet = build_case_packet(campaign_id=campaign_id, db=db)
        return packet
    except KeyError:
        raise HTTPException(status_code=404, detail="campaign_not_found")

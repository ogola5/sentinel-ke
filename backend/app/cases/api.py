from __future__ import annotations

from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.ledger.db import get_db
from app.cases.builders import build_case_packet

router = APIRouter(
    prefix="/v1/cases",
    tags=["cases"],
)


@router.post("/from-campaign/{campaign_id}")
def create_case_packet(campaign_id: UUID, db: Session = Depends(get_db)):
    try:
        packet = build_case_packet(campaign_id=campaign_id, db=db)
        return packet
    except KeyError:
        raise HTTPException(status_code=404, detail="campaign_not_found")

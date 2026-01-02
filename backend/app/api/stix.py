# backend/app/api/stix.py
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.ledger.db import get_db
from app.stix.exporter import (
    build_stix_bundle_from_campaign,
    build_stix_bundle_from_case,
    build_stix_bundle_from_mitigations,
)

router = APIRouter(prefix="/v1/stix", tags=["stix"])


@router.get("/from-campaign/{campaign_id}")
def stix_from_campaign(campaign_id: UUID, db: Session = Depends(get_db)):
    try:
        return build_stix_bundle_from_campaign(db=db, campaign_id=campaign_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="campaign_not_found")


@router.get("/from-case/{campaign_id}")
def stix_from_case(campaign_id: UUID, db: Session = Depends(get_db)):
    try:
        return build_stix_bundle_from_case(db=db, campaign_id=campaign_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="campaign_not_found")


# Alias routes matching runbook wording
@router.get("/campaign/{campaign_id}")
def stix_campaign_alias(campaign_id: UUID, db: Session = Depends(get_db)):
    return stix_from_campaign(campaign_id=campaign_id, db=db)


@router.get("/case/{campaign_id}")
def stix_case_alias(campaign_id: UUID, db: Session = Depends(get_db)):
    return stix_from_case(campaign_id=campaign_id, db=db)


@router.get("/mitigations")
def stix_from_mitigations(kind: str | None = None, limit: int = 200, db: Session = Depends(get_db)):
    return build_stix_bundle_from_mitigations(db=db, kind=kind, limit=limit)

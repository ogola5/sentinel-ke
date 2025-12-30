# backend/app/api/campaign_claims.py
from __future__ import annotations

from uuid import UUID
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.campaign.claims import CampaignClaim

router = APIRouter(prefix="/v1/claims", tags=["claims"])


@router.get("")
def list_claims(
    window: str = Query(default="Wmid"),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(CampaignClaim)
        .filter(CampaignClaim.window == window)
        .order_by(CampaignClaim.window_end.desc(), CampaignClaim.confidence.desc())
        .limit(limit)
        .all()
    )
    return {
        "items": [
            {
                "id": str(r.id),
                "claim_type": r.claim_type,
                "subject_campaign_id": str(r.subject_campaign_id),
                "object_campaign_id": str(r.object_campaign_id),
                "window": r.window,
                "window_start": r.window_start.isoformat(),
                "window_end": r.window_end.isoformat(),
                "confidence": r.confidence,
                "reason_codes": r.reason_codes,
                "infra_cluster_ids": r.infra_cluster_ids,
                "evidence_hashes": r.evidence_hashes[:50],  # cap for response
                "created_at": r.created_at.isoformat(),
                "updated_at": r.updated_at.isoformat(),
            }
            for r in rows
        ]
    }


@router.get("/{claim_id}")
def get_claim(
    claim_id: UUID,
    db: Session = Depends(get_db),
):
    r = db.query(CampaignClaim).filter(CampaignClaim.id == claim_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="claim_not_found")

    return {
        "id": str(r.id),
        "claim_type": r.claim_type,
        "subject_campaign_id": str(r.subject_campaign_id),
        "object_campaign_id": str(r.object_campaign_id),
        "window": r.window,
        "window_start": r.window_start.isoformat(),
        "window_end": r.window_end.isoformat(),
        "confidence": r.confidence,
        "reason_codes": r.reason_codes,
        "infra_cluster_ids": r.infra_cluster_ids,
        "evidence_hashes": r.evidence_hashes,
        "details": r.details_json,
        "created_at": r.created_at.isoformat(),
        "updated_at": r.updated_at.isoformat(),
    }

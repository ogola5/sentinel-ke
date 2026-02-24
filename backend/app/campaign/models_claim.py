# backend/app/campaign/models_claim.py
from __future__ import annotations

# Backward-compat shim: older modules imported CampaignClaim from
# app.campaign.models_claim. Keep a single canonical model definition in
# app.campaign.claims to avoid divergent schemas.
from app.campaign.claims import CampaignClaim

__all__ = ["CampaignClaim"]

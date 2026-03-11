from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict

from app.campaign.models import Campaign
from app.legal.models import LegalEvidenceBundle, LegalOrder
from app.legal.schemas import LegalEvidenceExportRequest, LegalOrderCreate
from app.legal.service import LegalAuthorizationService


def seed_evidence_bundles_once(
    *,
    db,
    exported_by: str = "system-seed",
    include_stix: bool = True,
    limit: int = 50,
) -> Dict[str, Any]:
    svc = LegalAuthorizationService(db)
    now = datetime.now(timezone.utc)

    active_order = (
        db.query(LegalOrder)
        .filter(LegalOrder.status == "active")
        .filter(LegalOrder.valid_from <= now)
        .filter(LegalOrder.valid_until >= now)
        .first()
    )

    if not active_order:
        order_payload = LegalOrderCreate(
            order_number="SENTINEL-STANDING-ORDER-001",
            court_name="National Computer & Cybercrimes Court",
            case_reference="NCCC/SOC/2026/001",
            purpose=(
                "Standing legal authority for national SOC threat-intelligence "
                "evidence preservation and campaign attribution under the "
                "Computer Misuse and Cybercrimes Act 2018."
            ),
            authorized_by="Director of Public Prosecutions",
            issued_at=now,
            valid_from=now - timedelta(days=1),
            valid_until=now + timedelta(days=365),
            allowed_actions=["evidence_export", "campaign_attribution", "threat_intel_share"],
            allowed_targets=["*"],
            constraints={"classification": "RESTRICTED", "jurisdiction": "Kenya"},
            metadata={"auto_created": True, "seed_version": "v1"},
            created_by="system-seed",
        )
        try:
            order_result = svc.create_order(order_payload)
            order_id = order_result["order_id"]
        except Exception as exc:
            existing = db.query(LegalOrder).order_by(LegalOrder.created_at.desc()).first()
            if not existing:
                raise RuntimeError(f"legal_order_creation_failed: {exc}") from exc
            order_id = str(existing.order_id)
    else:
        order_id = str(active_order.order_id)

    campaigns = (
        db.query(Campaign)
        .filter(Campaign.status.in_(["active", "dormant", "closed"]))
        .order_by(Campaign.score.desc())
        .limit(limit)
        .all()
    )
    already_bundled = {
        str(row.campaign_id)
        for row in db.query(LegalEvidenceBundle.campaign_id).all()
    }

    created = []
    skipped = []
    errors = []

    for campaign in campaigns:
        cid = str(campaign.id)
        if cid in already_bundled:
            skipped.append({"campaign_id": cid, "reason": "already_bundled"})
            continue
        try:
            result = svc.export_evidence_bundle(
                LegalEvidenceExportRequest(
                    campaign_id=cid,
                    order_id=order_id,
                    grant_ids=[],
                    include_stix=include_stix,
                    exported_by=exported_by,
                    notes=f"Auto-seeded bundle for campaign {cid}",
                )
            )
            created.append(
                {
                    "campaign_id": cid,
                    "bundle_id": result.get("bundle_id"),
                    "chain_hash": result.get("chain_hash"),
                }
            )
            already_bundled.add(cid)
        except Exception as exc:  # noqa: BLE001
            errors.append({"campaign_id": cid, "error": str(exc)})

    return {
        "status": "ok",
        "order_id": order_id,
        "campaigns_considered": len(campaigns),
        "created": created,
        "created_count": len(created),
        "skipped": skipped,
        "skipped_count": len(skipped),
        "errors": errors,
        "error_count": len(errors),
    }

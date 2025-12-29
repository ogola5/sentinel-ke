from __future__ import annotations

from typing import Dict, List, Set
from uuid import UUID

from sqlalchemy.orm import Session

from app.campaign.models import Campaign, CampaignEntity, CampaignEvent
from app.stix.ids import stix_id
from app.stix.mapper import to_stix_object


# -------------------------
# HARDENED CAMPAIGN → STIX
# -------------------------

def build_stix_bundle_from_campaign(*, db: Session, campaign_id: UUID) -> Dict:
    """
    Export a SINGLE campaign as a STIX 2.1 bundle.

    Semantics:
    - Campaign == Report
    - Entities == Observables (SCOs)
    - Relationships encode attacker → target (for DDOS)
    - Events are evidence references only (bounded)
    """

    # ------------------------------------------------------------------
    # 1) Load campaign (source of truth)
    # ------------------------------------------------------------------
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not campaign:
        raise KeyError("campaign_not_found")

    entities = (
        db.query(CampaignEntity)
        .filter(CampaignEntity.campaign_id == campaign_id)
        .all()
    )

    events = (
        db.query(CampaignEvent)
        .filter(CampaignEvent.campaign_id == campaign_id)
        .order_by(CampaignEvent.occurred_at.asc())
        .all()
    )

    # ------------------------------------------------------------------
    # 2) Producer identity (stable)
    # ------------------------------------------------------------------
    producer = {
        "type": "identity",
        "spec_version": "2.1",
        "id": stix_id("identity", "sentinel-ke"),
        "name": "Sentinel-KE",
        "identity_class": "organization",
    }

    objects: List[Dict] = [producer]
    object_ids: Set[str] = {producer["id"]}

    # ------------------------------------------------------------------
    # 3) Resolve TARGET (campaign primary key)
    # ------------------------------------------------------------------
    target_obj = to_stix_object(campaign.primary_key)
    if target_obj:
        if target_obj["id"] not in object_ids:
            objects.append(target_obj)
            object_ids.add(target_obj["id"])
        target_id = target_obj["id"]
    else:
        # DDOS without a target makes no sense → explicit failure
        raise ValueError(f"primary_key not mappable to STIX: {campaign.primary_key}")

    # ------------------------------------------------------------------
    # 4) Build observable objects (entities)
    # ------------------------------------------------------------------
    obj_by_entity_key: Dict[str, Dict] = {}

    for e in entities:
        # Skip primary key duplicate
        if e.entity_key == campaign.primary_key:
            continue

        o = to_stix_object(e.entity_key)
        if not o:
            # Hardening: skip unmappable entity safely
            continue

        if o["id"] not in object_ids:
            objects.append(o)
            object_ids.add(o["id"])

        obj_by_entity_key[e.entity_key] = o

    # ------------------------------------------------------------------
    # 5) Evidence references (bounded, deterministic)
    # ------------------------------------------------------------------
    event_hashes = [ev.event_hash for ev in events[:200]]

    external_refs = [
        {
            "source_name": "sentinel-ke",
            "external_id": h,
            "description": "ledger_event_hash",
        }
        for h in event_hashes
    ]

    # ------------------------------------------------------------------
    # 6) Relationships (DDOS-aware)
    # ------------------------------------------------------------------
    relationships: List[Dict] = []

    for e in entities:
        src_obj = obj_by_entity_key.get(e.entity_key)
        if not src_obj:
            continue

        # No self-loops
        if src_obj["id"] == target_id:
            continue

        # HARDENED LOGIC:
        # DDOS → IPs TARGET the endpoint
        if campaign.type == "DDOS_ENDPOINT_FANIN":
            rel_type = "targets"
        else:
            # fallback for non-DDOS campaigns
            rel_type = "related-to"

        rel = {
            "type": "relationship",
            "spec_version": "2.1",
            "id": stix_id(
                "relationship",
                f"{src_obj['id']}|{rel_type}|{target_id}|campaign:{campaign.id}",
            ),
            "relationship_type": rel_type,
            "source_ref": src_obj["id"],
            "target_ref": target_id,
            "created_by_ref": producer["id"],
            "external_references": external_refs,
        }

        relationships.append(rel)

    # ------------------------------------------------------------------
    # 7) Report (campaign container)
    # ------------------------------------------------------------------
    report_id = stix_id("report", f"campaign:{campaign.id}")

    report = {
        "type": "report",
        "spec_version": "2.1",
        "id": report_id,
        "created_by_ref": producer["id"],
        "name": f"Sentinel-KE Campaign: {campaign.type} {campaign.primary_key}",
        "description": (
            f"Campaign type={campaign.type}, "
            f"events={campaign.event_count}, "
            f"window={campaign.first_seen.isoformat()} → {campaign.last_seen.isoformat()}"
        ),
        "report_types": ["threat-report"],
        "published": campaign.last_seen.isoformat(),
        "confidence": min(100, int(campaign.score * 100)),
        "object_refs": (
            list(object_ids) + [r["id"] for r in relationships]
        ),
        "external_references": [
            {
                "source_name": "sentinel-ke",
                "external_id": str(campaign.id),
                "description": "campaign_id",
            }
        ],
    }

    # ------------------------------------------------------------------
    # 8) Bundle assembly
    # ------------------------------------------------------------------
    objects.extend(relationships)
    objects.append(report)

    bundle = {
        "type": "bundle",
        "id": stix_id("bundle", f"campaign:{campaign.id}"),
        "objects": objects,
    }

    return bundle

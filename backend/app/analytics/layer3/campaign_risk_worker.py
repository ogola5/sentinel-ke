from __future__ import annotations

import uuid
from typing import List, Set

from sqlalchemy.orm import Session

from app.ledger.infra_clusters import InfraClusterMember
from app.campaign.models import CampaignEntity
from app.campaign.risk import CampaignRisk
from app.ledger.db import SessionLocal
from app.db.base import utcnow


def _campaign_infra_members(db: Session, campaign_id) -> List[InfraClusterMember]:
    # Find infra_cluster members for clusters linked to this campaign via campaign_entity entries.
    infra_ids: Set[str] = set()
    ents = (
        db.query(CampaignEntity)
        .filter(CampaignEntity.campaign_id == campaign_id)
        .all()
    )
    for e in ents:
        if e.entity_key.startswith("infra_cluster:"):
            infra_ids.add(e.entity_key.split("infra_cluster:", 1)[1])

    if not infra_ids:
        return []

    return (
        db.query(InfraClusterMember)
        .filter(InfraClusterMember.cluster_id.in_(list(infra_ids)))
        .all()
    )


def run_once(db: Session, score: float = 0.6) -> int:
    """
    Simple blast-radius risk: for each campaign with infra_cluster members, suggest member IPs/providers not already in the campaign.
    """
    created = 0

    # preload campaign entities per campaign for quick lookup
    camp_to_entities: dict = {}
    ents = db.query(CampaignEntity).all()
    for e in ents:
        camp_to_entities.setdefault(e.campaign_id, set()).add(e.entity_key)

    for cid, entity_keys in camp_to_entities.items():
        members = _campaign_infra_members(db, cid)
        if not members:
            continue

        for m in members:
            # Skip if already part of campaign
            if m.entity_key in entity_keys:
                continue

            # derive type from prefix
            if ":" in m.entity_key:
                etype, _ = m.entity_key.split(":", 1)
            else:
                etype = "Unknown"

            existing = (
                db.query(CampaignRisk)
                .filter(CampaignRisk.campaign_id == cid)
                .filter(CampaignRisk.entity_key == m.entity_key)
                .first()
            )
            reasons = ["USES_INFRA_CLUSTER"]
            details = {
                "cluster_id": m.cluster_id,
                "entity_key": m.entity_key,
                "event_count": m.event_count,
                "meta": m.meta_json,
            }

            if existing:
                existing.score = score
                existing.reason_codes = reasons
                existing.details_json = details
            else:
                db.add(
                    CampaignRisk(
                        campaign_id=cid,
                        entity_key=m.entity_key,
                        entity_type=etype,
                        score=score,
                        reason_codes=reasons,
                        details_json=details,
                        created_at=utcnow(),
                    )
                )
                created += 1

    db.commit()
    return created


def main():
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--score", type=float, default=0.6)
    args = p.parse_args()

    db = SessionLocal()
    try:
        n = run_once(db=db, score=args.score)
        print(f"campaign_risk_worker created_risks={n}")
    finally:
        db.close()


if __name__ == "__main__":
    main()

# app/infra/builder.py  (FIXED)

import uuid
from datetime import datetime
from sqlalchemy.orm import Session

from app.campaign.models import Campaign, CampaignEntity
from app.ledger.infra_clusters import InfraCluster, InfraClusterMember


class InfraClusterBuilder:
    def __init__(self, db: Session):
        self.db = db

    def build_from_campaign(self, campaign_id: str) -> str:
        campaign = (
            self.db.query(Campaign)
            .filter(Campaign.id == campaign_id)
            .first()
        )
        if not campaign:
            raise ValueError("campaign not found")

        entities = (
            self.db.query(CampaignEntity)
            .filter(CampaignEntity.campaign_id == campaign_id)
            .all()
        )

        cluster_id = str(uuid.uuid4())

        cluster = InfraCluster(
            cluster_id=cluster_id,
            kind=campaign.type.lower(),
            confidence=min(0.9, max(0.4, campaign.score)),
            first_seen=campaign.first_seen,
            last_seen=campaign.last_seen,
            window_start=campaign.first_seen,
            window_end=campaign.last_seen,
            member_count=len(entities),
            summary_json={
                "campaign_id": str(campaign.id),
                "campaign_type": campaign.type,
                "event_count": campaign.event_count,
            },
        )
        self.db.add(cluster)

        for e in entities:
            self.db.add(
                InfraClusterMember(
                    cluster_id=cluster_id,
                    entity_key=e.entity_key,
                    first_seen=campaign.first_seen,
                    last_seen=e.last_seen or campaign.last_seen,
                    event_count=1,
                    meta_json={
                        "role": e.role,
                        "entity_type": e.entity_type,
                        "source": "campaign",
                    },
                )
            )

        # ✅ THIS IS THE FIX
        self.db.commit()

        return cluster_id


    def _new_cluster_id(self) -> str:
        import uuid
        return str(uuid.uuid4())

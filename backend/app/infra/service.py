from __future__ import annotations

from datetime import datetime, timezone
from sqlalchemy.orm import Session

from app.infra.builder import InfraClusterBuilder
from app.campaign.models import CampaignEntity


class InfraClusterService:
    def __init__(self, db: Session):
        self.db = db
        self.builder = InfraClusterBuilder(db)

    def materialize_from_campaign(self, campaign_id: str) -> str:
        # 1. Build infra cluster
        cluster_id = self.builder.build_from_campaign(
            campaign_id=campaign_id
        )

        # 2. Link campaign -> infra cluster (THIS WAS MISSING)
        now = datetime.now(timezone.utc)
        self.db.add(
            CampaignEntity(
                campaign_id=campaign_id,
                entity_key=f"infra_cluster:{cluster_id}",
                entity_type="InfraCluster",
                role="infrastructure",
                last_seen=now,
            )
        )

        # 3. Commit once (atomic)
        self.db.commit()

        return cluster_id

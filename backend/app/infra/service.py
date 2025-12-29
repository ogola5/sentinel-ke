from __future__ import annotations

from sqlalchemy.orm import Session

from app.infra.builder import InfraClusterBuilder

class InfraClusterService:
    def __init__(self, db: Session):
        self.db = db
        self.builder = InfraClusterBuilder(db)

    def materialize_from_campaign(self, campaign_id: str) -> str:
        cluster_id = self.builder.build_from_campaign(campaign_id=campaign_id)

        # IMPORTANT: persist to Postgres
        self.db.commit()

        return cluster_id

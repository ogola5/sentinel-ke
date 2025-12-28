# app/campaign/engine.py
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict

from sqlalchemy.orm import Session

from app.campaign.repository import CampaignRepository
from app.campaign.rules import derive_primary_keys, extract_entities_for_stats


DEFAULT_WINDOW = timedelta(minutes=30)  # tune per key type later


class CampaignEngine:
    def __init__(self, db: Session, *, window: timedelta = DEFAULT_WINDOW):
        self.db = db
        self.repo = CampaignRepository(db)
        self.window = window

    def apply_event(
        self,
        *,
        event_hash: str,
        occurred_at: datetime,
        anchors: Dict,
    ) -> None:
        decision = derive_primary_keys(anchors)
        entities = extract_entities_for_stats(anchors)

        # no primary keys => no campaign work
        if not decision.primary_keys:
            return

        now = occurred_at  # use occurred_at as campaign time reference
        for pk in decision.primary_keys:
            # 1) find or create active campaign stream for this primary key
            camp = self.repo.find_active_campaign(primary_key=pk, window=self.window, now=now)
            if not camp:
                camp = self.repo.create_campaign(
                    type="INFRA_REUSE",
                    primary_key=pk,
                    occurred_at=occurred_at,
                )

            # 2) attach event evidence (idempotent per campaign)
            inserted = self.repo.upsert_campaign_event(
                campaign_id=camp.id,
                event_hash=event_hash,
                occurred_at=occurred_at,
            )
            if not inserted:
                # same event already attached to this campaign
                continue

            # 3) update counters
            self.repo.update_campaign_counters(campaign=camp, occurred_at=occurred_at)

            # 4) upsert entities
            for etype, ekey in entities:
                self.repo.upsert_entity(
                    campaign_id=camp.id,
                    entity_type=etype,
                    entity_key=ekey,
                    seen_at=occurred_at,
                )

            # 5) deterministic score + stats
            self.repo.recompute_and_store_stats(campaign=camp)

        self.db.commit()

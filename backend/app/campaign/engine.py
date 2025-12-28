# app/campaign/engine.py
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List

from sqlalchemy.orm import Session

from app.campaign.repository import CampaignRepository
from app.campaign.detectors import Signal


DEFAULT_WINDOW = timedelta(hours=6)  # MVP: campaign stays active if seen within this window


class CampaignEngine:
    """
    Stateful campaign updater.
    - Applies one event's signals to Postgres
    - Uses your existing repository + scoring
    """

    def __init__(self, db: Session):
        self.db = db
        self.repo = CampaignRepository(db)

    def apply_signals(
        self,
        *,
        event_hash: str,
        occurred_at: datetime,
        signals: List[Signal],
        window: timedelta = DEFAULT_WINDOW,
    ) -> int:
        now = datetime.now(timezone.utc)
        updated = 0

        for sig in signals:
            # 1) find or create campaign
            campaign = self.repo.find_active_campaign(
                primary_key=sig.primary_key,
                window=window,
                now=now,
            )
            if not campaign:
                campaign = self.repo.create_campaign(
                    type=sig.type,
                    primary_key=sig.primary_key,
                    occurred_at=occurred_at,
                )

            # 2) link event (idempotent)
            inserted = self.repo.upsert_campaign_event(
                campaign_id=campaign.id,
                event_hash=event_hash,
                occurred_at=occurred_at,
            )
            if not inserted:
                # already processed this event for this campaign
                continue

            # 3) update entities
            for entity_type, entity_key in sig.entities:
                self.repo.upsert_entity(
                    campaign_id=campaign.id,
                    entity_type=entity_type,
                    entity_key=entity_key,
                    seen_at=occurred_at,
                )

            # 4) counters + score
            self.repo.update_campaign_counters(campaign=campaign, occurred_at=occurred_at)
            self.repo.recompute_and_store_stats(campaign=campaign)

            updated += 1

        self.db.commit()
        return updated

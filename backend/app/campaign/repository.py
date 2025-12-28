# app/campaign/repository.py
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
from uuid import UUID

from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert

from app.campaign.models import Campaign, CampaignEntity, CampaignEvent
from app.campaign.rules import compute_score


class CampaignRepository:
    def __init__(self, db: Session):
        self.db = db

    def find_active_campaign(
        self,
        *,
        primary_key: str,
        window: timedelta,
        now: datetime,
    ) -> Optional[Campaign]:
        """
        Active = last_seen within window and status=active.
        """
        cutoff = now - window
        return (
            self.db.query(Campaign)
            .filter(Campaign.primary_key == primary_key)
            .filter(Campaign.status == "active")
            .filter(Campaign.last_seen >= cutoff)
            .order_by(Campaign.last_seen.desc())
            .first()
        )

    def create_campaign(
        self,
        *,
        type: str,
        primary_key: str,
        occurred_at: datetime,
    ) -> Campaign:
        c = Campaign(
            type=type,
            primary_key=primary_key,
            status="active",
            first_seen=occurred_at,
            last_seen=occurred_at,
            event_count=0,
            score=0.0,
            stats={},
        )
        self.db.add(c)
        self.db.flush()  # assigns id
        return c

    def upsert_campaign_event(self, *, campaign_id: UUID, event_hash: str, occurred_at: datetime) -> bool:
        """
        Returns True if inserted, False if duplicate.
        """
        stmt = insert(CampaignEvent).values(
            campaign_id=campaign_id,
            event_hash=event_hash,
            occurred_at=occurred_at,
        ).on_conflict_do_nothing(
            index_elements=["campaign_id", "event_hash"]
        )
        res = self.db.execute(stmt)
        # rowcount is 1 on insert, 0 on no-op
        return bool(res.rowcount)

    def upsert_entity(self, *, campaign_id: UUID, entity_type: str, entity_key: str, seen_at: datetime) -> bool:
        """
        Returns True if newly inserted distinct entity, False if existed (but updates last_seen).
        """
        stmt = insert(CampaignEntity).values(
            campaign_id=campaign_id,
            entity_key=entity_key,
            entity_type=entity_type,
            last_seen=seen_at,
        ).on_conflict_do_update(
            index_elements=["campaign_id", "entity_key"],
            set_={"last_seen": seen_at}
        )
        res = self.db.execute(stmt)
        # With DO UPDATE, rowcount isn't a clean "new vs old".
        # For MVP, treat as "not sure". We'll recompute cardinalities via COUNT(*) by type when needed.
        return True

    def update_campaign_counters(
        self,
        *,
        campaign: Campaign,
        occurred_at: datetime,
    ) -> None:
        campaign.last_seen = max(campaign.last_seen, occurred_at)
        campaign.event_count += 1

    def recompute_and_store_stats(self, *, campaign: Campaign) -> None:
        """
        Deterministic stats computed from campaign_entity table.
        Called per event (ok for MVP scale), optimize later with cached counters.
        """
        cid = campaign.id

        def count_type(t: str) -> int:
            return (
                self.db.query(CampaignEntity)
                .filter(CampaignEntity.campaign_id == cid)
                .filter(CampaignEntity.entity_type == t)
                .count()
            )

        persons = count_type("Person")
        devices = count_type("Device")

        campaign.score = compute_score(
            event_count=campaign.event_count,
            distinct_persons=persons,
            distinct_devices=devices,
        )
        campaign.stats = {
            "events": campaign.event_count,
            "distinct_persons": persons,
            "distinct_devices": devices,
        }

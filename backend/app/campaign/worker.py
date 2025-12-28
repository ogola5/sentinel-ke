# app/campaign/worker.py
from __future__ import annotations

from datetime import datetime
from typing import Optional

from app.core.config import settings
from app.ledger.db import SessionLocal  # or however you create sessions
from app.streaming.consumer import build_consumer

from app.campaign.detectors import build_signals_from_event
from app.campaign.engine import CampaignEngine


def _parse_dt(s: str) -> datetime:
    # expects ISO like "2025-12-28T11:46:50+00:00"
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def main() -> None:
    if not settings.kafka_enabled:
        print("campaign.worker: KAFKA_ENABLED=false; exiting")
        return

    consumer = build_consumer(
        brokers=settings.redpanda_brokers,
        group_id="campaign-worker-v1",
        topics=[settings.kafka_events_topic],
        auto_offset_reset="earliest",
    )

    processed = 0

    for msg in consumer:
        if msg is None:
            continue
        if msg.value is None:
            continue

        try:
            event_hash = msg.key
            payload = msg.value  # build_event_message output
            event_doc = payload.get("event") or {}
            occurred_at = _parse_dt(event_doc["occurred_at"])

            signals = build_signals_from_event(event_hash=event_hash, event_doc=event_doc)

            # open db session per message (safe MVP); batch later
            db = SessionLocal()
            try:
                engine = CampaignEngine(db)
                updated = engine.apply_signals(
                    event_hash=event_hash,
                    occurred_at=occurred_at,
                    signals=signals,
                )
            finally:
                db.close()

            processed += 1
            if processed % 100 == 0:
                print(f"campaign.worker processed={processed} campaigns_updated={updated}")

        except Exception as e:
            # MVP: swallow and continue. Later: DLQ + metrics.
            print(f"campaign.worker error: {e}")


if __name__ == "__main__":
    main()

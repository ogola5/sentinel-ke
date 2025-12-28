# app/campaign/worker.py
from __future__ import annotations

from datetime import datetime
from typing import Dict

from app.core.config import settings
from app.streaming.consumer import build_consumer


def handle_event(msg: Dict) -> None:
    """
    Phase A4 — Campaign State Engine (MVP)

    For now:
    - just log
    - later: correlation, scoring, campaign promotion
    """
    event_hash = msg.get("event_hash")
    event = msg.get("event", {})
    event_type = event.get("event_type")

    print(
        f"[CAMPAIGN] {datetime.utcnow().isoformat()} "
        f"event_hash={event_hash} type={event_type}"
    )


def main() -> None:
    if not settings.kafka_enabled:
        print("Kafka disabled — campaign worker exiting")
        return

    consumer = build_consumer(
        broker=settings.redpanda_brokers,
        group_id="sentinel-campaign-worker",
        topics=[settings.kafka_events_topic],
        auto_offset_reset="earliest",
    )

    print("Campaign worker started")

    for message in consumer:
        try:
            handle_event(message.value)
        except Exception as e:
            # Never crash the worker in MVP
            print("Campaign worker error:", e)


if __name__ == "__main__":
    main()

from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, Tuple

from kafka import KafkaConsumer

from app.core.config import settings
from app.ledger.db import SessionLocal
from app.ingestion.schemas import CanonicalEvent
from app.ingestion.service import IngestionService


def _build_consumer(topics: list[str]) -> KafkaConsumer:
    group_id = os.getenv("INGEST_CONSUMER_GROUP", "sentinel-ingest-consumer")
    auto_reset = os.getenv("INGEST_CONSUMER_OFFSET_RESET", "earliest")
    timeout_ms = int(os.getenv("INGEST_CONSUMER_TIMEOUT_MS", "1000"))

    return KafkaConsumer(
        *topics,
        bootstrap_servers=settings.redpanda_brokers.split(","),
        group_id=group_id,
        auto_offset_reset=auto_reset,
        enable_auto_commit=False,
        value_deserializer=lambda v: json.loads(v.decode("utf-8")) if v else None,
        key_deserializer=lambda v: v.decode("utf-8") if v else None,
        consumer_timeout_ms=timeout_ms,
    )


def process_message(db, msg) -> Tuple[bool, str]:
    try:
        payload: Dict[str, Any] = msg.value or {}
        ev = CanonicalEvent.model_validate(payload)
        svc = IngestionService(db, pseudonym_salt="stream-salt")
        svc.ingest_event(event=ev, source_api_key=settings.ingest_api_key)
        return True, ""
    except Exception as e:
        return False, str(e)


def run(topics: list[str]) -> None:
    consumer = _build_consumer(topics)
    db = SessionLocal()
    processed = 0
    failed = 0
    try:
        for msg in consumer:
            ok, err = process_message(db, msg)
            if ok:
                processed += 1
            else:
                failed += 1
                print(f"[ingest_consumer] failed key={msg.key} error={err}")
            consumer.commit()
    finally:
        print(f"[ingest_consumer] shutting down processed={processed} failed={failed}")
        db.close()
        try:
            consumer.close()
        except Exception:
            pass


def main():
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument(
        "--topics",
        nargs="+",
        default=os.getenv("INGEST_CONSUMER_TOPICS", "sentinel.ingest").split(","),
    )
    args = p.parse_args()

    while True:
        try:
            run(args.topics)
        except Exception as e:
            print(f"[ingest_consumer] restart after error: {e}")
            time.sleep(2.0)


if __name__ == "__main__":
    main()

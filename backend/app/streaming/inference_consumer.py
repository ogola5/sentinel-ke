"""
Sentinel-KE AI Inference Consumer
==================================

Bridges the Kafka event stream to the AI inference layer.

Design
------
* Subscribes to the ``sentinel.events.v1`` topic (configurable via
  ``INFERENCE_CONSUMER_TOPICS`` env var).
* Accumulates incoming events; triggers ``run_once()`` when either:
    - a configurable number of events has arrived (batch threshold), OR
    - the minimum interval since the last inference run has elapsed.
* This prevents ``run_once()`` from being called per-message (it is an
  expensive batch operation that re-scores all entities in a window).
* Falls back to heuristic when no trained artifact exists — so this consumer
  is safe to run before the first GNN training job.

Usage
-----
  python -m app.streaming.inference_consumer
  INFERENCE_CONSUMER_TOPICS=sentinel.events.v1 \
  INFERENCE_MIN_INTERVAL_SEC=60 \
  python -m app.streaming.inference_consumer
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import List

from kafka import KafkaConsumer

from app.analytics.layer3.ai_inference_worker import run_once
from app.core.config import settings
from app.ledger.db import SessionLocal

log = logging.getLogger("sentinel.inference_consumer")


# ---------------------------------------------------------------------------
# Configuration (all overridable via environment variables)
# ---------------------------------------------------------------------------

def _cfg_topics() -> List[str]:
    raw = os.getenv("INFERENCE_CONSUMER_TOPICS", settings.kafka_events_topic)
    return [t.strip() for t in raw.split(",") if t.strip()]


def _cfg_group_id() -> str:
    return os.getenv("INFERENCE_CONSUMER_GROUP", "sentinel-inference-consumer")


def _cfg_min_interval_sec() -> float:
    return float(os.getenv("INFERENCE_MIN_INTERVAL_SEC", "60"))


def _cfg_batch_threshold() -> int:
    return int(os.getenv("INFERENCE_BATCH_THRESHOLD", "50"))


def _cfg_window_key() -> str:
    return os.getenv("INFERENCE_WINDOW_KEY", settings.gnn_window_key or "Wshort")


def _cfg_prediction_type() -> str:
    return os.getenv("INFERENCE_PREDICTION_TYPE", settings.gnn_prediction_type or "risk_gnn")


def _cfg_max_entities() -> int:
    return int(os.getenv("INFERENCE_MAX_ENTITIES", "5000"))


def _cfg_offset_reset() -> str:
    return os.getenv("INFERENCE_CONSUMER_OFFSET_RESET", "latest")


# ---------------------------------------------------------------------------
# Consumer build
# ---------------------------------------------------------------------------

def _build_consumer(topics: List[str]) -> KafkaConsumer:
    return KafkaConsumer(
        *topics,
        bootstrap_servers=settings.redpanda_brokers.split(","),
        group_id=_cfg_group_id(),
        auto_offset_reset=_cfg_offset_reset(),
        enable_auto_commit=False,
        value_deserializer=lambda v: json.loads(v.decode("utf-8")) if v else None,
        key_deserializer=lambda v: v.decode("utf-8") if v else None,
        consumer_timeout_ms=int(os.getenv("INFERENCE_CONSUMER_TIMEOUT_MS", "2000")),
    )


# ---------------------------------------------------------------------------
# Inference trigger
# ---------------------------------------------------------------------------

def _trigger_inference(*, window_key: str, prediction_type: str, max_entities: int) -> int:
    """
    Open a DB session, call run_once(), close the session.
    Returns number of predictions written (0 on error).
    """
    db = SessionLocal()
    try:
        n = run_once(
            db=db,
            window_key=window_key,
            prediction_type=prediction_type,
            max_entities=max_entities,
        )
        log.info(
            "inference_triggered predictions_written=%d window_key=%s prediction_type=%s",
            n, window_key, prediction_type,
        )
        return n
    except Exception as exc:  # noqa: BLE001
        log.warning("inference_trigger_failed error=%s", exc)
        return 0
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def run(topics: List[str]) -> None:
    consumer = _build_consumer(topics)
    min_interval = _cfg_min_interval_sec()
    batch_threshold = _cfg_batch_threshold()
    window_key = _cfg_window_key()
    prediction_type = _cfg_prediction_type()
    max_entities = _cfg_max_entities()

    events_since_last_run: int = 0
    last_run_at: float = 0.0

    log.info(
        "inference_consumer_started topics=%s min_interval_sec=%.0f "
        "batch_threshold=%d window_key=%s",
        topics, min_interval, batch_threshold, window_key,
    )

    try:
        for msg in consumer:
            events_since_last_run += 1
            now = time.monotonic()

            should_run = (
                events_since_last_run >= batch_threshold
                or (events_since_last_run > 0 and (now - last_run_at) >= min_interval)
            )

            if should_run:
                _trigger_inference(
                    window_key=window_key,
                    prediction_type=prediction_type,
                    max_entities=max_entities,
                )
                last_run_at = now
                events_since_last_run = 0

            consumer.commit()

    finally:
        log.info("inference_consumer_shutting_down events_pending=%d", events_since_last_run)
        try:
            consumer.close()
        except Exception:  # noqa: BLE001
            pass


def main() -> None:
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    p = argparse.ArgumentParser(description="Sentinel-KE AI inference Kafka consumer")
    p.add_argument(
        "--topics",
        nargs="+",
        default=_cfg_topics(),
        help="Kafka topics to subscribe to (default: sentinel.events.v1)",
    )
    args = p.parse_args()

    while True:
        try:
            run(args.topics)
        except Exception as exc:  # noqa: BLE001
            log.warning("inference_consumer_restart error=%s", exc)
            time.sleep(3.0)


if __name__ == "__main__":
    main()

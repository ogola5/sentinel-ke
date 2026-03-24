"""
Sentinel-KE GNN Training Consumer
=================================

Runs micro-batch retraining from the Kafka event stream.

This is intentionally not event-by-event online learning. It accumulates
events and retrains on a cadence so the platform remains operationally safe
while still refreshing models continuously.
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import List

from kafka import KafkaConsumer

from app.analytics.layer3.gnn_train_worker import run_once
from app.core.config import settings
from app.ledger.db import SessionLocal

log = logging.getLogger("sentinel.training_consumer")


def _cfg_topics() -> List[str]:
    raw = os.getenv("TRAINING_CONSUMER_TOPICS", settings.kafka_events_topic)
    return [t.strip() for t in raw.split(",") if t.strip()]


def _cfg_group_id() -> str:
    return os.getenv("TRAINING_CONSUMER_GROUP", "sentinel-training-consumer")


def _cfg_min_interval_sec() -> float:
    return float(os.getenv("TRAINING_MIN_INTERVAL_SEC", "900"))


def _cfg_batch_threshold() -> int:
    return int(os.getenv("TRAINING_BATCH_THRESHOLD", "500"))


def _cfg_window_key() -> str:
    return os.getenv("TRAINING_WINDOW_KEY", settings.gnn_window_key or "Wmid")


def _cfg_max_entities() -> int:
    return int(os.getenv("TRAINING_MAX_ENTITIES", str(settings.gnn_max_entities)))


def _cfg_offset_reset() -> str:
    return os.getenv("TRAINING_CONSUMER_OFFSET_RESET", "latest")


def _build_consumer(topics: List[str]) -> KafkaConsumer:
    return KafkaConsumer(
        *topics,
        bootstrap_servers=settings.redpanda_brokers.split(","),
        group_id=_cfg_group_id(),
        auto_offset_reset=_cfg_offset_reset(),
        enable_auto_commit=False,
        value_deserializer=lambda v: json.loads(v.decode("utf-8")) if v else None,
        key_deserializer=lambda v: v.decode("utf-8") if v else None,
        consumer_timeout_ms=int(os.getenv("TRAINING_CONSUMER_TIMEOUT_MS", "2000")),
    )


def _trigger_training(*, window_key: str, max_entities: int) -> dict:
    db = SessionLocal()
    try:
        out = run_once(
            db=db,
            window_key=window_key,
            edge_backend=settings.gnn_edge_backend,
            max_entities=max_entities,
            max_edges=settings.gnn_max_edges,
            min_edge_weight=settings.gnn_min_edge_weight,
            negative_multiplier=settings.gnn_negative_multiplier,
            threshold_min_samples=settings.gnn_threshold_min_samples,
            component_discovery_enabled=settings.gnn_component_discovery_enabled,
            component_min_size=settings.gnn_component_min_size,
            component_min_indicator_ratio=settings.gnn_component_min_indicator_ratio,
            epochs=settings.gnn_epochs,
            hidden_dim=settings.gnn_hidden_dim,
            embed_dim=settings.gnn_embed_dim,
            dropout=settings.gnn_dropout,
            learning_rate=settings.gnn_learning_rate,
            weight_decay=settings.gnn_weight_decay,
            split_policy=settings.gnn_split_policy,
            val_ratio=settings.gnn_val_ratio,
            seed=settings.gnn_seed,
            model_version=settings.gnn_model_version,
            prediction_type=settings.gnn_prediction_type,
            artifact_dir=settings.gnn_artifact_dir,
            allow_demo_real_data_override=settings.gnn_demo_allow_real_data_override,
            allow_demo_fairness_override=settings.gnn_demo_allow_fairness_override,
        )
        log.info("training_triggered result=%s", out)
        return dict(out or {})
    except Exception as exc:  # noqa: BLE001
        log.warning("training_trigger_failed error=%s", exc)
        return {"status": "error", "detail": str(exc)}
    finally:
        db.close()


def run(topics: List[str]) -> None:
    consumer = _build_consumer(topics)
    min_interval = _cfg_min_interval_sec()
    batch_threshold = _cfg_batch_threshold()
    window_key = _cfg_window_key()
    max_entities = _cfg_max_entities()

    events_since_last_run = 0
    last_run_at = 0.0

    log.info(
        "training_consumer_started topics=%s min_interval_sec=%.0f batch_threshold=%d window_key=%s",
        topics,
        min_interval,
        batch_threshold,
        window_key,
    )

    try:
        for _msg in consumer:
            events_since_last_run += 1
            now = time.monotonic()
            should_run = (
                events_since_last_run >= batch_threshold
                or (events_since_last_run > 0 and (now - last_run_at) >= min_interval)
            )
            if should_run:
                _trigger_training(window_key=window_key, max_entities=max_entities)
                last_run_at = now
                events_since_last_run = 0
            consumer.commit()
    finally:
        try:
            consumer.close()
        except Exception:  # noqa: BLE001
            pass


def main() -> None:
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    p = argparse.ArgumentParser(description="Sentinel-KE GNN training Kafka consumer")
    p.add_argument("--topics", nargs="+", default=_cfg_topics())
    args = p.parse_args()

    while True:
        try:
            run(args.topics)
        except Exception as exc:  # noqa: BLE001
            log.warning("training_consumer_restart error=%s", exc)
            time.sleep(3.0)


if __name__ == "__main__":
    main()

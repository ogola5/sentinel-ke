# app/streaming/consumer.py
from __future__ import annotations

import json
from typing import Iterable, List, Optional

from kafka import KafkaConsumer


def build_consumer(
    *,
    brokers: str,
    group_id: str,
    topics: List[str],
    auto_offset_reset: str = "earliest",
    enable_auto_commit: bool = True,
) -> KafkaConsumer:
    """
    kafka-python consumer for Redpanda/Kafka.

    - brokers: "redpanda:9092" or comma-separated
    - topics: ["sentinel.events.v1", "sentinel.graph.delta.v1"]
    """
    broker_list = [b.strip() for b in brokers.split(",") if b.strip()]
    if not broker_list:
        raise ValueError("No Kafka brokers provided")

    consumer = KafkaConsumer(
        *topics,
        bootstrap_servers=broker_list,
        group_id=group_id,
        auto_offset_reset=auto_offset_reset,
        enable_auto_commit=enable_auto_commit,
        value_deserializer=lambda v: json.loads(v.decode("utf-8")) if v else None,
        key_deserializer=lambda v: v.decode("utf-8") if v else None,
        consumer_timeout_ms=0,  # block indefinitely
        request_timeout_ms=30000,
        session_timeout_ms=10000,
        max_poll_records=200,
    )
    return consumer

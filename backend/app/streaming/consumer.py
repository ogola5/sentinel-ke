# app/streaming/consumer.py
from __future__ import annotations

import json
from typing import List, Iterator, Tuple

from kafka import KafkaConsumer


def build_consumer(
    *,
    broker: str,
    group_id: str,
    topics: List[str],
    auto_offset_reset: str = "earliest",
) -> KafkaConsumer:
    """
    kafka-python consumer (Redpanda compatible)

    - JSON value decoding
    - UTF-8 key decoding
    - Safe defaults for backend workers
    """

    consumer = KafkaConsumer(
        *topics,
        bootstrap_servers=broker,
        group_id=group_id,
        auto_offset_reset=auto_offset_reset,
        enable_auto_commit=True,
        key_deserializer=lambda k: k.decode("utf-8") if k else None,
        value_deserializer=lambda v: json.loads(v.decode("utf-8")),
    )

    return consumer

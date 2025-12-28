# app/streaming/test_consume_cli.py
from __future__ import annotations

import json
from kafka import KafkaConsumer

from app.core.config import settings

def main() -> None:
    consumer = KafkaConsumer(
        settings.kafka_events_topic,
        settings.kafka_graph_topic,
        bootstrap_servers=settings.redpanda_brokers.split(","),
        group_id="sentinel-debug",
        auto_offset_reset="earliest",
        enable_auto_commit=False,
        value_deserializer=lambda b: json.loads(b.decode("utf-8")),
        key_deserializer=lambda b: b.decode("utf-8") if b else None,
    )

    print("Consuming from:", settings.kafka_events_topic, "and", settings.kafka_graph_topic)
    for msg in consumer:
        print("\nTOPIC:", msg.topic)
        print("KEY:", msg.key)
        print("VALUE:", json.dumps(msg.value, indent=2)[:2000])

if __name__ == "__main__":
    main()

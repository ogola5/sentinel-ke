# app/streaming/producer.py
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from kafka import KafkaProducer
from kafka.errors import KafkaError

from app.core.config import settings

log = logging.getLogger("sentinel.kafka")


def _json_dumps(obj: Any) -> bytes:
    return json.dumps(obj, separators=(",", ":"), sort_keys=True, default=str).encode("utf-8")


class SentinelProducer:
    """
    Thin wrapper around kafka-python producer.
    Non-fatal: publish failures should not break ingestion in MVP.
    """

    def __init__(self) -> None:
        self.enabled = bool(settings.kafka_enabled)
        self._producer: Optional[KafkaProducer] = None

        if not self.enabled:
            log.warning("Kafka disabled (KAFKA_ENABLED=false)")
            return

        self._producer = KafkaProducer(
            bootstrap_servers=settings.redpanda_brokers.split(","),
            client_id=settings.kafka_client_id,
            acks=settings.kafka_acks,
            linger_ms=settings.kafka_linger_ms,
            retries=settings.kafka_retries,
            value_serializer=_json_dumps,
            key_serializer=lambda k: k.encode("utf-8") if isinstance(k, str) else k,
        )

    def publish(self, *, topic: str, key: str, value: Dict[str, Any]) -> None:
        if not self.enabled or not self._producer:
            return
        try:
            fut = self._producer.send(topic, key=key, value=value)
            # do not block; we can optionally ensure send() accepted by client:
            fut.add_errback(lambda exc: log.error("Kafka publish failed topic=%s key=%s err=%s", topic, key, exc))
        except KafkaError as e:
            log.error("Kafka error topic=%s key=%s err=%s", topic, key, e)
        except Exception as e:
            log.error("Kafka unexpected error topic=%s key=%s err=%s", topic, key, e)

    def flush(self, timeout: float = 1.0) -> None:
        if self._producer:
            try:
                self._producer.flush(timeout=timeout)
            except Exception:
                pass

    def close(self) -> None:
        if self._producer:
            try:
                self._producer.flush(timeout=1.0)
                self._producer.close(timeout=1.0)
            except Exception:
                pass


# global singleton for FastAPI process
producer = SentinelProducer()

# app/streaming/producer.py
from __future__ import annotations

import json
import logging
import threading
from typing import Any, Dict, Optional

from kafka import KafkaProducer
from kafka.errors import KafkaError

from app.core.config import settings

log = logging.getLogger("sentinel.kafka")

# ------------------------------------------------------------------------------
# helpers
# ------------------------------------------------------------------------------

def _json_dumps(obj: Any) -> bytes:
    return json.dumps(
        obj,
        separators=(",", ":"),
        sort_keys=True,
        default=str,
    ).encode("utf-8")


# ------------------------------------------------------------------------------
# lazy singleton (CRITICAL FIX)
# ------------------------------------------------------------------------------

_lock = threading.Lock()
_instance: Optional["SentinelProducer"] = None


def get_producer() -> Optional["SentinelProducer"]:
    """
    Lazy accessor.
    Never connects to Kafka at import time.
    Safe if broker is unavailable.
    """
    global _instance

    if not settings.kafka_enabled:
        return None

    if _instance is not None:
        return _instance

    with _lock:
        if _instance is None:
            try:
                _instance = SentinelProducer()
            except Exception as e:
                # Do NOT crash FastAPI if Kafka is unavailable
                log.error("Kafka producer init failed (non-fatal): %s", e)
                _instance = None

    return _instance


# ------------------------------------------------------------------------------
# producer
# ------------------------------------------------------------------------------

class SentinelProducer:
    """
    Thin wrapper around kafka-python producer.

    IMPORTANT:
    - No Kafka connection at import time
    - Non-fatal on failures
    """

    def __init__(self) -> None:
        self._producer: Optional[KafkaProducer] = None

        brokers = settings.redpanda_brokers.split(",")
        log.info("Initializing Kafka producer brokers=%s", brokers)

        self._producer = KafkaProducer(
            bootstrap_servers=brokers,
            client_id=settings.kafka_client_id,
            acks=settings.kafka_acks,
            linger_ms=settings.kafka_linger_ms,
            retries=settings.kafka_retries,
            value_serializer=_json_dumps,
            key_serializer=lambda k: k.encode("utf-8") if isinstance(k, str) else k,
        )

    def publish(self, *, topic: str, key: str, value: Dict[str, Any]) -> None:
        if not self._producer:
            return

        try:
            fut = self._producer.send(topic, key=key, value=value)
            fut.add_errback(
                lambda exc: log.error(
                    "Kafka publish failed topic=%s key=%s err=%s",
                    topic,
                    key,
                    exc,
                )
            )
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

# app/core/config.py
from __future__ import annotations
import os


def env_bool(name: str, default: bool = False) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "y", "on")


class Settings:
    # ---------------------------------------------------------
    # Kafka / Redpanda
    # ---------------------------------------------------------
    redpanda_brokers = os.environ.get("REDPANDA_BROKERS", "redpanda:9092")
    kafka_client_id = os.environ.get("KAFKA_CLIENT_ID", "sentinel-backend")
    kafka_events_topic = os.environ.get("KAFKA_EVENTS_TOPIC", "sentinel.events.v1")
    kafka_graph_topic = os.environ.get("KAFKA_GRAPH_TOPIC", "sentinel.graph.delta.v1")
    kafka_acks = int(os.environ.get("KAFKA_ACKS", "1"))
    kafka_linger_ms = int(os.environ.get("KAFKA_LINGER_MS", "5"))
    kafka_retries = int(os.environ.get("KAFKA_RETRIES", "3"))
    kafka_enabled = env_bool("KAFKA_ENABLED", True)

    # ---------------------------------------------------------
    # Ingestion API Security
    # ---------------------------------------------------------
    # Single key for MVP / dev. Can be rotated to multi-key later.
    ingest_api_key = os.environ.get("INGEST_API_KEY", "dev-secret-key")

    # Allow bypass in local dev ONLY if explicitly enabled
    ingest_allow_unauthenticated = env_bool("INGEST_ALLOW_UNAUTH", False)


settings = Settings()

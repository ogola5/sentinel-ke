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
    # GNN / AI backbone
    # ---------------------------------------------------------
    gnn_enabled = env_bool("GNN_ENABLED", True)
    gnn_model_version = os.environ.get("GNN_MODEL_VERSION", "gnn-sage-v1")
    gnn_prediction_type = os.environ.get("GNN_PREDICTION_TYPE", "risk_gnn")
    gnn_window_key = os.environ.get("GNN_WINDOW_KEY", "Wmid")
    gnn_edge_backend = os.environ.get("GNN_EDGE_BACKEND", "hybrid")  # postgres|neo4j|hybrid
    gnn_max_entities = int(os.environ.get("GNN_MAX_ENTITIES", "3000"))
    gnn_max_edges = int(os.environ.get("GNN_MAX_EDGES", "30000"))
    gnn_min_edge_weight = int(os.environ.get("GNN_MIN_EDGE_WEIGHT", "1"))
    gnn_epochs = int(os.environ.get("GNN_EPOCHS", "60"))
    gnn_hidden_dim = int(os.environ.get("GNN_HIDDEN_DIM", "64"))
    gnn_embed_dim = int(os.environ.get("GNN_EMBED_DIM", "32"))
    gnn_dropout = float(os.environ.get("GNN_DROPOUT", "0.2"))
    gnn_learning_rate = float(os.environ.get("GNN_LEARNING_RATE", "0.001"))
    gnn_weight_decay = float(os.environ.get("GNN_WEIGHT_DECAY", "0.0001"))
    gnn_seed = int(os.environ.get("GNN_SEED", "7"))
    gnn_artifact_dir = os.environ.get("GNN_ARTIFACT_DIR", "/app/artifacts/gnn")

    # ---------------------------------------------------------
    # Ingestion API Security
    # ---------------------------------------------------------
    # Single key for MVP / dev. Can be rotated to multi-key later.
    ingest_api_key = os.environ.get("INGEST_API_KEY", "dev-secret-key")

    # Allow bypass in local dev ONLY if explicitly enabled
    ingest_allow_unauthenticated = env_bool("INGEST_ALLOW_UNAUTH", False)


settings = Settings()

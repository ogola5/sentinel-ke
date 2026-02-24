# app/core/config.py
from __future__ import annotations
import os


def env_bool(name: str, default: bool = False) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "y", "on")


def env_csv(name: str, default: str = "") -> list[str]:
    raw = os.environ.get(name, default)
    return [x.strip() for x in raw.split(",") if x.strip()]


class Settings:
    app_env = os.environ.get("APP_ENV", "development").lower()

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
    gnn_negative_multiplier = float(os.environ.get("GNN_NEGATIVE_MULTIPLIER", "1.5"))
    gnn_epochs = int(os.environ.get("GNN_EPOCHS", "60"))
    gnn_hidden_dim = int(os.environ.get("GNN_HIDDEN_DIM", "64"))
    gnn_embed_dim = int(os.environ.get("GNN_EMBED_DIM", "32"))
    gnn_dropout = float(os.environ.get("GNN_DROPOUT", "0.2"))
    gnn_learning_rate = float(os.environ.get("GNN_LEARNING_RATE", "0.001"))
    gnn_weight_decay = float(os.environ.get("GNN_WEIGHT_DECAY", "0.0001"))
    gnn_threshold_min_samples = int(os.environ.get("GNN_THRESHOLD_MIN_SAMPLES", "10"))
    gnn_component_discovery_enabled = env_bool("GNN_COMPONENT_DISCOVERY_ENABLED", True)
    gnn_component_min_size = int(os.environ.get("GNN_COMPONENT_MIN_SIZE", "3"))
    gnn_component_min_indicator_ratio = float(os.environ.get("GNN_COMPONENT_MIN_INDICATOR_RATIO", "0.5"))
    gnn_seed = int(os.environ.get("GNN_SEED", "7"))
    gnn_artifact_dir = os.environ.get("GNN_ARTIFACT_DIR", "/app/artifacts/gnn")
    ai_api_enabled = env_bool("AI_API_ENABLED", True)
    ai_uncertainty_abstain_threshold = float(os.environ.get("AI_UNCERTAINTY_ABSTAIN_THRESHOLD", "0.45"))
    ai_attack_technique_enabled = env_bool("AI_ATTACK_TECHNIQUE_ENABLED", True)
    ai_temporal_edge_decay = float(os.environ.get("AI_TEMPORAL_EDGE_DECAY", "0.015"))
    ai_drift_enabled = env_bool("AI_DRIFT_ENABLED", True)
    ai_drift_warn_threshold = float(os.environ.get("AI_DRIFT_WARN_THRESHOLD", "0.12"))
    ai_drift_critical_threshold = float(os.environ.get("AI_DRIFT_CRITICAL_THRESHOLD", "0.2"))
    ai_lineage_signing_secret = os.environ.get("AI_LINEAGE_SIGNING_SECRET", "").strip()
    ai_rollout_mode_default = os.environ.get("AI_ROLLOUT_MODE_DEFAULT", "single").strip().lower()
    ai_canary_ratio_default = float(os.environ.get("AI_CANARY_RATIO_DEFAULT", "0.1"))
    ai_feedback_enabled = env_bool("AI_FEEDBACK_ENABLED", True)

    # ---------------------------------------------------------
    # Platform hardening
    # ---------------------------------------------------------
    pseudonym_salt = os.environ.get("PSEUDONYM_SALT", "").strip()
    api_auth_disabled = env_bool("API_AUTH_DISABLED", False)
    api_auth_optional_dev = env_bool("API_AUTH_OPTIONAL_DEV", False)
    frontend_api_key = os.environ.get("FRONTEND_API_KEY", "").strip()
    db_auto_create = env_bool("DB_AUTO_CREATE", app_env == "development")
    cors_allow_origins = env_csv("CORS_ALLOW_ORIGINS", "")

    # ---------------------------------------------------------
    # User authentication / RBAC
    # ---------------------------------------------------------
    auth_enabled = env_bool("AUTH_ENABLED", True)
    auth_access_token_minutes = int(os.environ.get("AUTH_ACCESS_TOKEN_MINUTES", "20"))
    auth_refresh_token_minutes = int(os.environ.get("AUTH_REFRESH_TOKEN_MINUTES", "1440"))
    auth_password_iterations = int(os.environ.get("AUTH_PASSWORD_ITERATIONS", "450000"))
    auth_password_pepper = os.environ.get("AUTH_PASSWORD_PEPPER", "").strip()
    auth_login_max_failures = int(os.environ.get("AUTH_LOGIN_MAX_FAILURES", "5"))
    auth_lock_minutes = int(os.environ.get("AUTH_LOCK_MINUTES", "30"))
    auth_token_issuer = os.environ.get("AUTH_TOKEN_ISSUER", "sentinel-ke-auth").strip()
    auth_token_audience = os.environ.get("AUTH_TOKEN_AUDIENCE", "sentinel-ke-api").strip()
    _auth_token_secret = os.environ.get("AUTH_TOKEN_SECRET", "").strip()
    auth_token_secret = _auth_token_secret or (
        "dev-insecure-auth-token-secret-change-me" if app_env == "development" else ""
    )
    auth_mfa_issuer = os.environ.get("AUTH_MFA_ISSUER", "Sentinel-KE").strip()
    _auth_mfa_secret_key = os.environ.get("AUTH_MFA_SECRET_KEY", "").strip()
    auth_mfa_secret_key = _auth_mfa_secret_key or (
        "dev-insecure-auth-mfa-secret-key-change-me" if app_env == "development" else ""
    )
    auth_step_up_minutes = int(os.environ.get("AUTH_STEP_UP_MINUTES", "15"))
    auth_central_mfa_required = env_bool("AUTH_CENTRAL_MFA_REQUIRED", True)
    auth_bootstrap_admin_enabled = env_bool("AUTH_BOOTSTRAP_ADMIN_ENABLED", False)
    auth_bootstrap_admin_username = os.environ.get("AUTH_BOOTSTRAP_ADMIN_USERNAME", "central-admin").strip()
    auth_bootstrap_admin_password = os.environ.get("AUTH_BOOTSTRAP_ADMIN_PASSWORD", "").strip()
    auth_bootstrap_admin_display_name = os.environ.get(
        "AUTH_BOOTSTRAP_ADMIN_DISPLAY_NAME",
        "Central Admin",
    ).strip()

    # ---------------------------------------------------------
    # Crypto posture (quantum-readiness signaling)
    # ---------------------------------------------------------
    crypto_tls_mode = os.environ.get("CRYPTO_TLS_MODE", "tls1.3").strip().lower()
    crypto_pqc_mode = os.environ.get("CRYPTO_PQC_MODE", "hybrid").strip().lower()
    crypto_kms_provider = os.environ.get("CRYPTO_KMS_PROVIDER", "hsm").strip().lower()
    crypto_key_rotation_days = int(os.environ.get("CRYPTO_KEY_ROTATION_DAYS", "90"))

    # ---------------------------------------------------------
    # Ingestion API Security
    # ---------------------------------------------------------
    ingest_api_key = os.environ.get("INGEST_API_KEY", "").strip()

    # Allow bypass in local dev ONLY if explicitly enabled
    ingest_allow_unauthenticated = env_bool("INGEST_ALLOW_UNAUTH", False)


settings = Settings()

# app/core/config.py
from __future__ import annotations
import os

from app.core.env_contract import normalize_database_url

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
    database_url = normalize_database_url(os.environ.get("DATABASE_URL", ""))

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
    # Federation — shared national correlation salt
    # All registered edge agents receive this salt at registration.
    # They use it when computing entity_key_hash so that the SAME entity
    # hashed by two different partners produces the SAME hash on the hub,
    # enabling cross-partner threat correlation.
    # ---------------------------------------------------------
    federation_correlation_salt = os.environ.get(
        "FEDERATION_CORRELATION_SALT",
        "sentinel-ke-national-salt-CHANGE-IN-PRODUCTION",
    )
    federation_require_signed_requests = env_bool("FEDERATION_REQUIRE_SIGNED_REQUESTS", True)

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
    gnn_split_policy = os.environ.get("GNN_SPLIT_POLICY", "temporal_recency_holdout").strip().lower()
    gnn_val_ratio = float(os.environ.get("GNN_VAL_RATIO", "0.2"))
    gnn_min_negative_count = int(os.environ.get("GNN_MIN_NEGATIVE_COUNT", "5"))
    gnn_min_negative_ratio = float(os.environ.get("GNN_MIN_NEGATIVE_RATIO", "0.1"))
    gnn_benchmark_window_candidates = int(os.environ.get("GNN_BENCHMARK_WINDOW_CANDIDATES", "12"))
    gnn_min_real_ratio = float(os.environ.get("GNN_MIN_REAL_RATIO", "0.3"))
    gnn_demo_allow_real_data_override = env_bool(
        "GNN_DEMO_ALLOW_REAL_DATA_OVERRIDE",
        app_env == "development",
    )
    gnn_demo_allow_fairness_override = env_bool(
        "GNN_DEMO_ALLOW_FAIRNESS_OVERRIDE",
        app_env == "development",
    )
    gnn_threshold_min_samples = int(os.environ.get("GNN_THRESHOLD_MIN_SAMPLES", "10"))
    gnn_component_discovery_enabled = env_bool("GNN_COMPONENT_DISCOVERY_ENABLED", True)
    gnn_component_min_size = int(os.environ.get("GNN_COMPONENT_MIN_SIZE", "3"))
    gnn_component_min_indicator_ratio = float(os.environ.get("GNN_COMPONENT_MIN_INDICATOR_RATIO", "0.5"))
    gnn_seed = int(os.environ.get("GNN_SEED", "7"))
    gnn_artifact_dir = os.environ.get("GNN_ARTIFACT_DIR", "/app/artifacts/gnn")
    gnn_cpu_threads = int(os.environ.get("GNN_CPU_THREADS", "4"))
    gnn_pretrain_epochs = int(os.environ.get("GNN_PRETRAIN_EPOCHS", "3"))
    gnn_retrain_interval_sec = int(os.environ.get("GNN_RETRAIN_INTERVAL_SEC", "3600"))
    gnn_use_amp = env_bool("GNN_USE_AMP", True)
    gnn_deterministic_training = env_bool("GNN_DETERMINISTIC_TRAINING", True)
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
    ai_explainability_enabled = env_bool("AI_EXPLAINABILITY_ENABLED", True)
    ai_explainability_method = os.environ.get("AI_EXPLAINABILITY_METHOD", "integrated_gradients").strip().lower()
    ai_explainability_top_k = int(os.environ.get("AI_EXPLAINABILITY_TOP_K", "6"))
    ai_explainability_max_nodes = int(os.environ.get("AI_EXPLAINABILITY_MAX_NODES", "64"))
    ai_explainability_ig_steps = int(os.environ.get("AI_EXPLAINABILITY_IG_STEPS", "24"))
    ai_inference_allow_heuristic_fallback = env_bool(
        "AI_INFERENCE_ALLOW_HEURISTIC_FALLBACK",
        app_env == "development",
    )
    ai_auto_containment_enabled = env_bool("AI_AUTO_CONTAINMENT_ENABLED", False)
    ai_auto_containment_min_score = float(os.environ.get("AI_AUTO_CONTAINMENT_MIN_SCORE", "90.0"))
    ai_auto_containment_max_actions_per_run = int(
        os.environ.get("AI_AUTO_CONTAINMENT_MAX_ACTIONS_PER_RUN", "10")
    )
    ai_auto_containment_require_impact_stage = env_bool(
        "AI_AUTO_CONTAINMENT_REQUIRE_IMPACT_STAGE",
        True,
    )
    ai_auto_containment_allowed_actions = env_csv(
        "AI_AUTO_CONTAINMENT_ALLOWED_ACTIONS",
        "block_ip,isolate_host",
    )
    ai_auto_containment_dry_run = env_bool("AI_AUTO_CONTAINMENT_DRY_RUN", False)
    ai_auto_containment_require_section = env_bool("AI_AUTO_CONTAINMENT_REQUIRE_SECTION", True)
    ai_auto_containment_cooldown_minutes = int(
        os.environ.get("AI_AUTO_CONTAINMENT_COOLDOWN_MINUTES", "30")
    )
    ai_worker_warn_after_minutes = int(os.environ.get("AI_WORKER_WARN_AFTER_MINUTES", "15"))
    ai_worker_fail_after_minutes = int(os.environ.get("AI_WORKER_FAIL_AFTER_MINUTES", "60"))

    # ---------------------------------------------------------
    # Edge / station deployment
    # Set IS_EDGE_NODE=true on agency stations.
    # Central hub sets IS_EDGE_NODE=false (default).
    # ---------------------------------------------------------
    is_edge_node            = env_bool("IS_EDGE_NODE", False)
    edge_partner_id         = os.environ.get("EDGE_PARTNER_ID", "").strip()
    edge_hub_url            = os.environ.get("EDGE_HUB_URL", "").strip()
    edge_hub_api_key        = os.environ.get("EDGE_HUB_API_KEY", "").strip()
    edge_national_salt      = os.environ.get("EDGE_NATIONAL_SALT", "").strip()
    edge_sync_min_risk      = float(os.environ.get("EDGE_SYNC_MIN_RISK", "60.0"))  # AIPrediction.score is 0-100
    edge_sync_batch_size    = int(os.environ.get("EDGE_SYNC_BATCH_SIZE", "200"))
    edge_sync_lookback_hours = int(os.environ.get("EDGE_SYNC_LOOKBACK_HOURS", "4"))

    # ---------------------------------------------------------
    # NL Analyst Copilot (local in-house engine)
    # ---------------------------------------------------------
    ai_copilot_enabled = env_bool("AI_COPILOT_ENABLED", True)
    ai_copilot_model = os.environ.get("AI_COPILOT_MODEL", "sentinel-local-analyst-v1").strip()
    ai_copilot_max_tokens = int(os.environ.get("AI_COPILOT_MAX_TOKENS", "1024"))
    legal_auto_bundle_enabled = env_bool("LEGAL_AUTO_BUNDLE_ENABLED", True)
    legal_auto_bundle_limit = int(os.environ.get("LEGAL_AUTO_BUNDLE_LIMIT", "50"))

    # ---------------------------------------------------------
    # Platform hardening
    # ---------------------------------------------------------
    pseudonym_salt = os.environ.get("PSEUDONYM_SALT", "").strip()
    api_auth_disabled = env_bool("API_AUTH_DISABLED", False)
    api_auth_optional_dev = env_bool("API_AUTH_OPTIONAL_DEV", False)
    frontend_api_key = os.environ.get("FRONTEND_API_KEY", "").strip()
    db_auto_create = env_bool("DB_AUTO_CREATE", app_env == "development")
    cors_allow_origins = env_csv("CORS_ALLOW_ORIGINS", "")
    http_security_headers_enabled = env_bool("HTTP_SECURITY_HEADERS_ENABLED", True)
    http_request_logging_enabled = env_bool("HTTP_REQUEST_LOGGING_ENABLED", True)

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
    auth_central_mfa_enrollment_required = env_bool("AUTH_CENTRAL_MFA_ENROLLMENT_REQUIRED", True)
    auth_service_central_access = env_bool("AUTH_SERVICE_CENTRAL_ACCESS", False)
    auth_bootstrap_admin_enabled = env_bool("AUTH_BOOTSTRAP_ADMIN_ENABLED", False)
    auth_bootstrap_admin_username = os.environ.get("AUTH_BOOTSTRAP_ADMIN_USERNAME", "central-admin").strip()
    auth_bootstrap_admin_password = os.environ.get("AUTH_BOOTSTRAP_ADMIN_PASSWORD", "").strip()
    auth_bootstrap_admin_display_name = os.environ.get(
        "AUTH_BOOTSTRAP_ADMIN_DISPLAY_NAME",
        "Central Admin",
    ).strip()
    auth_intrusion_window_minutes = int(os.environ.get("AUTH_INTRUSION_WINDOW_MINUTES", "15"))
    auth_intrusion_max_failures_per_ip = int(os.environ.get("AUTH_INTRUSION_MAX_FAILURES_PER_IP", "20"))
    auth_intrusion_max_failures_per_username = int(
        os.environ.get("AUTH_INTRUSION_MAX_FAILURES_PER_USERNAME", "8")
    )
    auth_intrusion_min_distinct_usernames = int(
        os.environ.get("AUTH_INTRUSION_MIN_DISTINCT_USERNAMES", "5")
    )
    auth_breakglass_enabled = env_bool("AUTH_BREAKGLASS_ENABLED", False)
    auth_breakglass_password = os.environ.get("AUTH_BREAKGLASS_PASSWORD", "").strip()
    auth_breakglass_password_sha3_512 = os.environ.get("AUTH_BREAKGLASS_PASSWORD_SHA3_512", "").strip()
    auth_breakglass_local_only = env_bool("AUTH_BREAKGLASS_LOCAL_ONLY", True)
    auth_breakglass_allow_in_production = env_bool("AUTH_BREAKGLASS_ALLOW_IN_PRODUCTION", False)
    auth_breakglass_username = os.environ.get("AUTH_BREAKGLASS_USERNAME", "dev-breakglass").strip()

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

    # ---------------------------------------------------------
    # Webhook secret encryption
    # Fernet key for encrypting webhook signing secrets at rest.
    # Generate: python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    # MUST be set in production. Dev fallback is derived deterministically in executor.py.
    # ---------------------------------------------------------
    webhook_secret_encryption_key = os.environ.get("WEBHOOK_SECRET_ENCRYPTION_KEY", "").strip()
    defense_rollback_window_minutes = int(
        os.environ.get("DEFENSE_ROLLBACK_WINDOW_MINUTES", "240")
    )

    # ---------------------------------------------------------
    # Fairness policy
    # GNN runs with max_positive_rate_disparity above this threshold are
    # flagged fairness_blocked=True in the API response and logged as warnings.
    # Set FAIRNESS_DISPARITY_THRESHOLD=0.0 to block on any disparity.
    # ---------------------------------------------------------
    fairness_disparity_threshold = float(
        os.environ.get("FAIRNESS_DISPARITY_THRESHOLD", "0.4")
    )

    # ---------------------------------------------------------
    # Rate limiting  (slowapi)
    # RATE_LIMIT_ENABLED=false to disable globally (e.g. in tests).
    # Individual endpoint limits are set via @limiter.limit() decorators.
    # ---------------------------------------------------------
    rate_limit_enabled       = env_bool("RATE_LIMIT_ENABLED", True)
    rate_limit_global_per_min = int(os.environ.get("RATE_LIMIT_GLOBAL_PER_MIN", "200"))
    rate_limit_auth_per_min  = int(os.environ.get("RATE_LIMIT_AUTH_PER_MIN", "10"))
    rate_limit_ingest_per_min = int(os.environ.get("RATE_LIMIT_INGEST_PER_MIN", "300"))


settings = Settings()

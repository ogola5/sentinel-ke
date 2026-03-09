from __future__ import annotations

from types import SimpleNamespace

from app.core.runtime_hardening import evaluate_runtime_hardening


def _settings(**overrides):
    base = {
        "app_env": "development",
        "database_url": "postgresql+psycopg2://sentinel:sentinel@localhost:5433/sentinel",
        "frontend_api_key": "k" * 24,
        "ingest_api_key": "k" * 24,
        "pseudonym_salt": "s" * 16,
        "auth_token_secret": "t" * 32,
        "auth_password_pepper": "p" * 16,
        "auth_mfa_secret_key": "m" * 32,
        "api_auth_disabled": False,
        "ingest_allow_unauthenticated": False,
        "db_auto_create": False,
        "http_security_headers_enabled": True,
        "auth_enabled": True,
        "auth_password_iterations": 450000,
        "auth_service_central_access": False,
        "auth_intrusion_window_minutes": 15,
        "auth_intrusion_max_failures_per_ip": 20,
        "auth_intrusion_max_failures_per_username": 8,
        "auth_intrusion_min_distinct_usernames": 5,
        "cors_allow_origins": ["https://sentinel.example"],
        "crypto_tls_mode": "tls1.3",
        "crypto_pqc_mode": "hybrid",
        "crypto_kms_provider": "hsm",
        "crypto_key_rotation_days": 90,
        "auth_central_mfa_required": True,
        "auth_breakglass_enabled": False,
        "auth_breakglass_password": "",
        "auth_breakglass_password_sha3_512": "",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_runtime_hardening_passes_baseline_development_profile():
    report = evaluate_runtime_hardening(_settings())
    assert report.errors == ()


def test_runtime_hardening_flags_insecure_production_settings_as_errors():
    report = evaluate_runtime_hardening(
        _settings(
            app_env="production",
            api_auth_disabled=True,
            ingest_allow_unauthenticated=True,
            db_auto_create=True,
            cors_allow_origins=["*"],
            database_url="postgresql+psycopg2://sentinel:sentinel@postgres:5432/sentinel",
        )
    )
    assert "API_AUTH_DISABLED_true" in report.errors
    assert "INGEST_ALLOW_UNAUTH_true" in report.errors
    assert "DB_AUTO_CREATE_true" in report.errors
    assert "CORS_ALLOW_ORIGINS_wildcard" in report.errors
    assert "DATABASE_URL_host_not_deployable" in report.errors


def test_runtime_hardening_treats_missing_secret_as_warning_in_development():
    report = evaluate_runtime_hardening(_settings(auth_token_secret=""))
    assert report.errors == ()
    assert "AUTH_TOKEN_SECRET_missing" in report.warnings


def test_runtime_hardening_flags_invalid_database_scheme():
    report = evaluate_runtime_hardening(
        _settings(
            app_env="production",
            database_url="mysql://u:p@db/sentinel",
        )
    )
    assert "DATABASE_URL_scheme_invalid" in report.errors


def test_runtime_hardening_flags_breakglass_enabled_in_production():
    report = evaluate_runtime_hardening(
        _settings(
            app_env="production",
            auth_breakglass_enabled=True,
            auth_breakglass_password="dev-only-breakglass",
        )
    )
    assert "AUTH_BREAKGLASS_ENABLED_true" in report.errors

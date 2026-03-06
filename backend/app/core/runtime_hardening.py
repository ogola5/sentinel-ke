from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from app.core.env_contract import evaluate_database_url_contract

_DEV_ENVS = {"development", "dev", "local", "test", "testing"}
_TLS_ALLOWED = {"tls1.2", "tls1.3", "mtls-tls1.3"}
_PQC_ALLOWED = {"off", "classical", "hybrid", "pqc-only"}
_KMS_ALLOWED = {"hsm", "vault", "aws-kms", "gcp-kms", "azure-kv", "software"}


@dataclass(frozen=True)
class RuntimeHardeningReport:
    errors: tuple[str, ...]
    warnings: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.errors


def _as_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _is_strict_env(app_env: str) -> bool:
    return app_env not in _DEV_ENVS


def evaluate_runtime_hardening(settings_obj: Any) -> RuntimeHardeningReport:
    app_env = _as_str(getattr(settings_obj, "app_env", "development")).lower() or "development"
    strict = _is_strict_env(app_env)

    errors: list[str] = []
    warnings: list[str] = []

    def add_issue(message: str, *, strict_error: bool = True) -> None:
        if strict and strict_error:
            errors.append(message)
        else:
            warnings.append(message)

    secret_policies = (
        ("frontend_api_key", "FRONTEND_API_KEY", 24),
        ("ingest_api_key", "INGEST_API_KEY", 24),
        ("pseudonym_salt", "PSEUDONYM_SALT", 16),
        ("auth_token_secret", "AUTH_TOKEN_SECRET", 32),
        ("auth_password_pepper", "AUTH_PASSWORD_PEPPER", 16),
        ("auth_mfa_secret_key", "AUTH_MFA_SECRET_KEY", 32),
    )
    for attr, label, min_length in secret_policies:
        value = _as_str(getattr(settings_obj, attr, ""))
        if not value:
            add_issue(f"{label}_missing")
            continue
        if len(value) < min_length:
            add_issue(f"{label}_too_short")

    if _as_bool(getattr(settings_obj, "api_auth_disabled", False)):
        add_issue("API_AUTH_DISABLED_true")
    if _as_bool(getattr(settings_obj, "api_auth_optional_dev", False)):
        add_issue("API_AUTH_OPTIONAL_DEV_true")
    if not _as_bool(getattr(settings_obj, "rate_limit_enabled", True)):
        add_issue("RATE_LIMIT_ENABLED_false", strict_error=False)
    if _as_bool(getattr(settings_obj, "ingest_allow_unauthenticated", False)):
        add_issue("INGEST_ALLOW_UNAUTH_true")
    if _as_bool(getattr(settings_obj, "db_auto_create", False)):
        add_issue("DB_AUTO_CREATE_true")
    if not _as_bool(getattr(settings_obj, "http_security_headers_enabled", True)):
        add_issue("HTTP_SECURITY_HEADERS_ENABLED_false")
    if not _as_bool(getattr(settings_obj, "auth_enabled", True)):
        add_issue("AUTH_ENABLED_false")

    if _as_int(getattr(settings_obj, "auth_password_iterations", 0)) < 300_000:
        add_issue("AUTH_PASSWORD_ITERATIONS_low")

    cors_allow_origins = getattr(settings_obj, "cors_allow_origins", []) or []
    for origin in cors_allow_origins:
        if isinstance(origin, str) and origin.strip() == "*":
            add_issue("CORS_ALLOW_ORIGINS_wildcard")
            break

    tls_mode = _as_str(getattr(settings_obj, "crypto_tls_mode", "tls1.3")).lower()
    if tls_mode not in _TLS_ALLOWED:
        add_issue("CRYPTO_TLS_MODE_invalid")
    if strict and tls_mode != "tls1.3":
        warnings.append("CRYPTO_TLS_MODE_not_tls1_3")

    pqc_mode = _as_str(getattr(settings_obj, "crypto_pqc_mode", "hybrid")).lower()
    if pqc_mode not in _PQC_ALLOWED:
        add_issue("CRYPTO_PQC_MODE_invalid")

    kms_provider = _as_str(getattr(settings_obj, "crypto_kms_provider", "hsm")).lower()
    if kms_provider not in _KMS_ALLOWED:
        add_issue("CRYPTO_KMS_PROVIDER_invalid")

    rotation_days = _as_int(getattr(settings_obj, "crypto_key_rotation_days", 0))
    if rotation_days <= 0:
        add_issue("CRYPTO_KEY_ROTATION_DAYS_invalid")
    elif strict and rotation_days > 180:
        warnings.append("CRYPTO_KEY_ROTATION_DAYS_high")

    if strict and not _as_bool(getattr(settings_obj, "auth_central_mfa_required", True)):
        warnings.append("AUTH_CENTRAL_MFA_REQUIRED_false")

    db_report = evaluate_database_url_contract(
        _as_str(getattr(settings_obj, "database_url", "")),
        app_env=app_env,
    )
    errors.extend(list(db_report.errors))
    warnings.extend(list(db_report.warnings))

    return RuntimeHardeningReport(
        errors=tuple(errors),
        warnings=tuple(warnings),
    )


def enforce_runtime_hardening(settings_obj: Any, *, logger: logging.Logger | None = None) -> RuntimeHardeningReport:
    report = evaluate_runtime_hardening(settings_obj)
    target = logger or logging.getLogger("sentinel.runtime")

    for warning in report.warnings:
        target.warning("runtime_hardening_warning=%s", warning)

    if report.errors:
        joined = ",".join(report.errors)
        target.error("runtime_hardening_error=%s", joined)
        raise RuntimeError(f"runtime_hardening_failed:{joined}")

    target.info("runtime_hardening_ok")
    return report

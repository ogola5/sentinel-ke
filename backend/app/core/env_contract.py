from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple
from urllib.parse import urlparse


@dataclass(frozen=True)
class EnvContractReport:
    errors: Tuple[str, ...]
    warnings: Tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.errors


_STRICT_ENVS = {"production", "prod", "staging"}
_SUPPORTED_SCHEMES = {"postgres", "postgresql", "postgresql+psycopg2"}


def normalize_database_url(url: str) -> str:
    value = str(url or "").strip()
    if value.startswith("postgres://"):
        return f"postgresql+psycopg2://{value[len('postgres://'):]}"
    if value.startswith("postgresql://") and not value.startswith("postgresql+psycopg2://"):
        return f"postgresql+psycopg2://{value[len('postgresql://'):]}"
    return value


def evaluate_database_url_contract(database_url: str, *, app_env: str) -> EnvContractReport:
    value = normalize_database_url(database_url)
    strict = str(app_env or "").strip().lower() in _STRICT_ENVS
    errors: list[str] = []
    warnings: list[str] = []

    if not value:
        return EnvContractReport(errors=("DATABASE_URL_missing",), warnings=tuple())

    parsed = urlparse(value)
    scheme = str(parsed.scheme or "").strip().lower()
    host = str(parsed.hostname or "").strip().lower()

    if scheme not in _SUPPORTED_SCHEMES:
        errors.append("DATABASE_URL_scheme_invalid")
    if not host:
        errors.append("DATABASE_URL_host_missing")

    if strict and host in {"postgres", "localhost", "127.0.0.1"}:
        errors.append("DATABASE_URL_host_not_deployable")
    elif host == "postgres":
        warnings.append("DATABASE_URL_internal_docker_host")

    if strict and parsed.path in {"", "/"}:
        errors.append("DATABASE_URL_dbname_missing")

    return EnvContractReport(errors=tuple(errors), warnings=tuple(warnings))

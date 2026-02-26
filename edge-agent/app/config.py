"""
Sentinel-KE Edge Agent — Configuration
========================================

All settings are read from environment variables (or a .env file).
No sensitive values are hard-coded.
"""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # -----------------------------------------------------------------------
    # Identity
    # -----------------------------------------------------------------------
    partner_id:   str = "demo-partner"
    partner_name: str = "Demo Edge Partner"

    # -----------------------------------------------------------------------
    # National Hub connection
    # -----------------------------------------------------------------------
    hub_url:     str = "http://localhost:8000"
    hub_api_key: str = "REPLACE_ME"

    # -----------------------------------------------------------------------
    # GNN / inference settings
    # -----------------------------------------------------------------------
    # How many hours back the GNN window spans (default: 1 h rolling window)
    window_hours:   int   = 1
    # Run full GNN train + inference every N seconds (default: 300 = 5 min)
    run_interval_s: int   = 300
    # Only report entities with risk_score >= this threshold
    risk_threshold: float = 0.60
    # GNN model version tag embedded in every batch
    model_version:  str   = "edge-gnn-v1.0"

    # -----------------------------------------------------------------------
    # Local data source  (demo mode uses built-in synthetic data)
    # -----------------------------------------------------------------------
    # Options: demo | postgres | csv
    data_source: str = "demo"

    # If data_source == "postgres": local partner database URL
    local_db_url: str = ""

    # If data_source == "csv": path to event CSV file
    csv_path: str = ""

    # -----------------------------------------------------------------------
    # HMAC salt — partner-specific secret for entity key hashing.
    # The hub never sees raw entity keys; only HMAC-SHA256(key, salt).
    # Must be different for every partner (prevents cross-partner re-id).
    # -----------------------------------------------------------------------
    hmac_salt: str = "CHANGE_ME_PER_PARTNER"


settings = Settings()

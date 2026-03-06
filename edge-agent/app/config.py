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
    # Options: demo | db | csv
    #   demo     Built-in synthetic Kenya fraud profiles (no external deps)
    #   db       Query a live database (PostgreSQL, MySQL, MSSQL, Oracle, SQLite)
    #   csv      Read from a pre-exported CSV file
    data_source: str = "demo"

    # If data_source == "db": SQLAlchemy connection URL for the partner's database
    #   PostgreSQL: postgresql+psycopg2://user:pass@host:5432/dbname
    #   MySQL:      mysql+pymysql://user:pass@host:3306/dbname
    #   MSSQL:      mssql+pyodbc://user:pass@host/dbname?driver=ODBC+Driver+17+for+SQL+Server
    #   Oracle:     oracle+cx_oracle://user:pass@host:1521/SID
    #   SQLite:     sqlite:////absolute/path/to/file.db
    local_db_url: str = ""

    # Built-in query preset — populates db_query/column mapping automatically.
    # Options: kra_tax | ifmis_payments | kemsa_procurement | mpesa_core |
    #          ecitizen_logins | mpesa_agent | custom
    # Leave blank or set "custom" to use db_query directly.
    db_preset: str = ""

    # Custom SQL query — must include {window_start} and {window_end} placeholders.
    # Example:
    #   SELECT account_no, 'TRANSACTION_EVENT' AS event_type,
    #          transaction_date AS occurred_at, amount, risk_code
    #   FROM payments
    #   WHERE transaction_date BETWEEN '{window_start}' AND '{window_end}'
    db_query: str = ""

    # Column mapping — which column in query results maps to each EntityRecord field.
    # These are used when NOT using a built-in preset.
    db_entity_key_col:    str = "entity_key"      # uniquely identifies the entity
    db_entity_type_fixed: str = ""                # force all rows to this type (e.g. "account_h")
    db_entity_type_col:   str = "entity_type"     # or read from a column
    db_event_type_col:    str = "event_type"      # e.g. TRANSACTION_EVENT
    db_timestamp_col:     str = "occurred_at"     # ISO-8601 or datetime column
    db_risk_flags_col:    str = ""                # optional pipe-separated flags column
    db_amount_col:        str = ""                # optional KES amount column

    # Max rows fetched per window (safety cap)
    db_batch_size: int = 10_000

    # If data_source == "csv": path to event CSV file
    csv_path: str = ""

    # -----------------------------------------------------------------------
    # HMAC salts — two distinct roles:
    #
    # national_salt   Received from the hub at registration (same value for
    #                 ALL partners).  Used to compute entity_key_hash that
    #                 is sent in PatternBatch — enables cross-partner
    #                 correlation on the hub (same entity → same hash).
    #                 Set from the `correlation_salt` field in the register
    #                 response: NATIONAL_SALT=<value from hub>.
    #
    # hmac_salt       Partner-specific secret for local privacy processing.
    #                 NEVER sent to the hub.  Used for any internal hashing
    #                 that must remain opaque between partners.
    # -----------------------------------------------------------------------
    national_salt: str = "REPLACE_WITH_CORRELATION_SALT_FROM_HUB_REGISTRATION"
    hmac_salt: str     = "CHANGE_ME_PER_PARTNER"


settings = Settings()

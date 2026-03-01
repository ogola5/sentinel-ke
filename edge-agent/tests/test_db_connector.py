"""
Unit tests for DbConnector — uses SQLite in-memory, no live database needed.

Tests that need SQLAlchemy are automatically skipped when it is not installed.
Install 'sqlalchemy' to run the full suite: pip install sqlalchemy
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

# Allow running from edge-agent/ root or from tests/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Skip all sqlalchemy-dependent tests if the library is absent
pytest.importorskip(
    "sqlalchemy",
    reason="sqlalchemy not installed — skipping DbConnector tests",
)

from app.connector import (  # noqa: E402
    CsvConnector,
    DbConnector,
    DemoConnector,
    _map_flags,
    get_connector,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _utc(dt_str: str) -> datetime:
    return datetime.fromisoformat(dt_str).replace(tzinfo=timezone.utc)


def _custom_connector(rows: list[dict], query: str, **kwargs) -> DbConnector:
    """Build a DbConnector wired to an in-memory SQLite DB."""
    from sqlalchemy import create_engine, text  # noqa: PLC0415

    cols = list(rows[0].keys())
    engine = create_engine("sqlite:///:memory:", future=True)
    col_defs = ", ".join(f"{c} TEXT" for c in cols)
    with engine.begin() as conn:
        conn.execute(text(f"CREATE TABLE events ({col_defs})"))
        for row in rows:
            vals = ", ".join(
                repr(str(v) if v is not None else "") for v in row.values()
            )
            conn.execute(text(f"INSERT INTO events VALUES ({vals})"))

    connector = DbConnector(db_url="sqlite:///:memory:", query=query, **kwargs)
    connector._engine = engine  # inject pre-built engine
    return connector


_W_START = _utc("2025-01-01 08:00:00")
_W_END   = _utc("2025-01-01 09:00:00")

_WINDOW_SQL = (
    "SELECT * FROM events"
    " WHERE occurred_at >= '{window_start}'"
    " AND occurred_at < '{window_end}'"
    " LIMIT {batch_size}"
)


# ---------------------------------------------------------------------------
# _map_flags
# ---------------------------------------------------------------------------

def test_map_flags_known_value():
    assert _map_flags("NON_COMPLIANT", {"NON_COMPLIANT": "AUDIT_FINDING"}) == [
        "AUDIT_FINDING"
    ]


def test_map_flags_pipe_separated():
    flag_map = {"NON_COMPLIANT": "AUDIT_FINDING", "SUSPENDED": "AUDIT_FINDING"}
    assert set(_map_flags("NON_COMPLIANT|SUSPENDED", flag_map)) == {"AUDIT_FINDING"}


def test_map_flags_passthrough_unknown():
    assert _map_flags("CUSTOM_FLAG", {}) == ["CUSTOM_FLAG"]


def test_map_flags_skip_ok_values():
    for val in ("OK", "NORMAL", "COMPLIANT", "NONE", "NULL"):
        assert _map_flags(val, {}) == [], f"Expected [] for {val}"


def test_map_flags_empty_string():
    assert _map_flags("", {}) == []


def test_map_flags_none_input():
    assert _map_flags(None, {}) == []  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Basic aggregation
# ---------------------------------------------------------------------------

def test_single_entity_one_row():
    rows = [{
        "entity_key": "PIN001",
        "event_type": "VAT_RETURN",
        "occurred_at": "2025-01-01 08:30:00",
        "risk_flag": "",
        "amount": "50000",
    }]
    c = _custom_connector(
        rows,
        _WINDOW_SQL,
        entity_key_col="entity_key",
        entity_type_fixed="account_h",
        event_type_col="event_type",
        timestamp_col="occurred_at",
        risk_flags_col="risk_flag",
        amount_col="amount",
    )
    result = c.fetch(_W_START, _W_END)
    assert len(result) == 1
    r = result[0]
    assert r["entity_key"] == "account_h:PIN001"
    assert r["entity_type"] == "account_h"
    assert r["event_count"] == 1
    assert "VAT_RETURN" in r["features"]["event_types"]


def test_multiple_rows_same_entity_aggregated():
    """Three rows for the same entity_key must collapse into one EntityRecord."""
    rows = [
        {"entity_key": "A001", "event_type": "PAYMENT",
         "occurred_at": "2025-01-01 08:10:00", "flag": "", "amount": "1000"},
        {"entity_key": "A001", "event_type": "PAYMENT",
         "occurred_at": "2025-01-01 08:20:00", "flag": "", "amount": "2000"},
        {"entity_key": "A001", "event_type": "REFUND",
         "occurred_at": "2025-01-01 08:40:00", "flag": "", "amount": "500"},
    ]
    c = _custom_connector(
        rows, _WINDOW_SQL,
        entity_key_col="entity_key", entity_type_fixed="account_h",
        event_type_col="event_type", timestamp_col="occurred_at",
        risk_flags_col="flag", amount_col="amount",
    )
    result = c.fetch(_W_START, _W_END)
    assert len(result) == 1
    r = result[0]
    assert r["event_count"] == 3
    assert r["features"]["event_types"]["PAYMENT"] == 2
    assert r["features"]["event_types"]["REFUND"] == 1


def test_two_distinct_entities_not_merged():
    rows = [
        {"entity_key": "E1", "event_type": "LOGIN",
         "occurred_at": "2025-01-01 08:05:00", "flag": ""},
        {"entity_key": "E2", "event_type": "LOGIN",
         "occurred_at": "2025-01-01 08:15:00", "flag": ""},
    ]
    c = _custom_connector(
        rows, _WINDOW_SQL,
        entity_key_col="entity_key", entity_type_fixed="ip",
        event_type_col="event_type", timestamp_col="occurred_at",
        risk_flags_col="flag",
    )
    result = c.fetch(_W_START, _W_END)
    assert len(result) == 2


# ---------------------------------------------------------------------------
# Flag mapping via connector
# ---------------------------------------------------------------------------

def test_flag_mapping_applied():
    rows = [{
        "entity_key": "P001",
        "event_type": "TX",
        "occurred_at": "2025-01-01 08:00:30",
        "status": "NON_COMPLIANT",
    }]
    c = _custom_connector(
        rows, _WINDOW_SQL,
        entity_key_col="entity_key", entity_type_fixed="account_h",
        event_type_col="event_type", timestamp_col="occurred_at",
        risk_flags_col="status",
    )
    c._flag_map = {"NON_COMPLIANT": "AUDIT_FINDING"}
    result = c.fetch(_W_START, _W_END)
    assert "AUDIT_FINDING" in result[0]["risk_flags"]


def test_ok_status_produces_no_flags():
    rows = [{
        "entity_key": "P002",
        "event_type": "TX",
        "occurred_at": "2025-01-01 08:00:30",
        "status": "OK",
    }]
    c = _custom_connector(
        rows, _WINDOW_SQL,
        entity_key_col="entity_key", entity_type_fixed="account_h",
        event_type_col="event_type", timestamp_col="occurred_at",
        risk_flags_col="status",
    )
    result = c.fetch(_W_START, _W_END)
    assert result[0]["risk_flags"] == []


# ---------------------------------------------------------------------------
# Window filtering
# ---------------------------------------------------------------------------

def test_row_outside_window_excluded():
    rows = [
        {"entity_key": "X1", "event_type": "TX",
         "occurred_at": "2025-01-01 07:59:59"},  # before window
        {"entity_key": "X2", "event_type": "TX",
         "occurred_at": "2025-01-01 08:30:00"},  # inside
    ]
    c = _custom_connector(
        rows, _WINDOW_SQL,
        entity_key_col="entity_key", entity_type_fixed="ip",
        event_type_col="event_type", timestamp_col="occurred_at",
    )
    result = c.fetch(_W_START, _W_END)
    keys = {r["entity_key"] for r in result}
    assert "ip:X2" in keys
    assert "ip:X1" not in keys


# ---------------------------------------------------------------------------
# Entity key prefixing
# ---------------------------------------------------------------------------

def test_entity_key_gets_type_prefix():
    rows = [{"entity_key": "12345", "event_type": "TX",
             "occurred_at": "2025-01-01 08:30:00"}]
    c = _custom_connector(
        rows, _WINDOW_SQL,
        entity_key_col="entity_key", entity_type_fixed="phone_h",
        event_type_col="event_type", timestamp_col="occurred_at",
    )
    result = c.fetch(_W_START, _W_END)
    assert result[0]["entity_key"] == "phone_h:12345"


def test_entity_key_with_colon_not_double_prefixed():
    rows = [{"entity_key": "phone_h:99999", "event_type": "TX",
             "occurred_at": "2025-01-01 08:30:00"}]
    c = _custom_connector(
        rows, _WINDOW_SQL,
        entity_key_col="entity_key", entity_type_fixed="phone_h",
        event_type_col="event_type", timestamp_col="occurred_at",
    )
    result = c.fetch(_W_START, _W_END)
    assert result[0]["entity_key"] == "phone_h:99999"


# ---------------------------------------------------------------------------
# Missing entity_key rows skipped
# ---------------------------------------------------------------------------

def test_missing_entity_key_row_skipped():
    rows = [
        {"entity_key": "",    "event_type": "TX",
         "occurred_at": "2025-01-01 08:10:00"},
        {"entity_key": "E99", "event_type": "TX",
         "occurred_at": "2025-01-01 08:20:00"},
    ]
    c = _custom_connector(
        rows, _WINDOW_SQL,
        entity_key_col="entity_key", entity_type_fixed="ip",
        event_type_col="event_type", timestamp_col="occurred_at",
    )
    result = c.fetch(_W_START, _W_END)
    assert len(result) == 1
    assert result[0]["entity_key"] == "ip:E99"


# ---------------------------------------------------------------------------
# last_seen_age_sec populated
# ---------------------------------------------------------------------------

def test_last_seen_age_sec_positive():
    rows = [{"entity_key": "Z1", "event_type": "TX",
             "occurred_at": "2025-01-01 08:30:00"}]
    c = _custom_connector(
        rows, _WINDOW_SQL,
        entity_key_col="entity_key", entity_type_fixed="ip",
        event_type_col="event_type", timestamp_col="occurred_at",
    )
    result = c.fetch(_W_START, _W_END)
    age = result[0]["features"]["last_seen_age_sec"]
    assert age is not None and age > 0


# ---------------------------------------------------------------------------
# Error conditions
# ---------------------------------------------------------------------------

def test_connector_raises_without_query_or_preset():
    with pytest.raises(ValueError, match="db_preset or db_query"):
        DbConnector(db_url="sqlite:///:memory:")


def test_connector_raises_without_db_url():
    with pytest.raises(ValueError, match="local_db_url"):
        DbConnector(db_url="")


# ---------------------------------------------------------------------------
# get_connector() factory
# ---------------------------------------------------------------------------

def test_factory_returns_demo_by_default():
    with patch("app.connector.settings") as mock_cfg:
        mock_cfg.data_source = "demo"
        c = get_connector()
    assert isinstance(c, DemoConnector)


def test_factory_returns_db_connector_for_db_source():
    with patch("app.connector.settings") as mock_cfg:
        mock_cfg.data_source = "db"
        mock_cfg.local_db_url = "sqlite:///:memory:"
        mock_cfg.db_preset = ""
        mock_cfg.db_query = (
            "SELECT 1 AS entity_key FROM events LIMIT {batch_size}"
        )
        mock_cfg.db_entity_key_col = "entity_key"
        mock_cfg.db_entity_type_fixed = ""
        mock_cfg.db_entity_type_col = "entity_type"
        mock_cfg.db_event_type_col = "event_type"
        mock_cfg.db_timestamp_col = "occurred_at"
        mock_cfg.db_risk_flags_col = ""
        mock_cfg.db_amount_col = ""
        mock_cfg.db_batch_size = 1000
        c = get_connector()
    assert isinstance(c, DbConnector)


def test_factory_returns_csv_connector():
    with patch("app.connector.settings") as mock_cfg:
        mock_cfg.data_source = "csv"
        mock_cfg.csv_path = "/tmp/test.csv"
        c = get_connector()
    assert isinstance(c, CsvConnector)

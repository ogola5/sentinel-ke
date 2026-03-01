"""
Sentinel-KE Edge Agent — Data Source Connectors
=================================================

Connectors abstract WHERE the edge agent reads local event data from.
The GNN runner only sees a list of EntityRecord dicts — it never touches
the underlying data source directly.

Supported sources
-----------------
DemoConnector   Synthetic Kenya fraud data (no external deps, used for demos / CI).
CsvConnector    Reads events from a local CSV file (column mapping below).
DbConnector     Queries a live database (PostgreSQL, MySQL, MSSQL, Oracle, SQLite)
                using SQLAlchemy.  Includes built-in presets for common Kenyan
                government / telco systems (KRA, IFMIS, KEMSA, M-Pesa, eCitizen).

Each connector returns a list of EntityRecord dicts:

{
    "entity_key":    str,          # raw entity identifier (hashed BEFORE sending to hub)
    "entity_type":   str,          # ip / phone_h / account_h / domain / etc.
    "event_count":   int,
    "source_count":  int,
    "degree":        int,
    "weighted_degree": int,
    "risk_flags":    list[str],
    "features": {
        "event_types":            dict[str, int],  # event_type -> count
        "last_seen_age_sec":      float | None,
        "event_types_other_count": int,
    },
    "first_seen":    datetime | None,
    "last_seen":     datetime | None,
}
"""
from __future__ import annotations

import csv
import logging
import math
import random
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from app.config import settings

log = logging.getLogger("sentinel.edge.connector")


EntityRecord = Dict[str, Any]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Base connector
# ---------------------------------------------------------------------------

class BaseConnector(ABC):
    @abstractmethod
    def fetch(self, window_start: datetime, window_end: datetime) -> List[EntityRecord]:
        """Return entity records for the given time window."""


# ---------------------------------------------------------------------------
# Demo connector — generates synthetic Kenya fraud patterns
# ---------------------------------------------------------------------------

_DEMO_ENTITY_TYPES = [
    "ip", "phone_h", "account_h", "domain", "service_id",
    "provider_id", "device_id",
]

_DEMO_EVENT_TYPES = [
    "DDOS_SIGNAL_EVENT", "SIM_SWAP_EVENT", "TRANSACTION_EVENT",
    "PHISHING_MESSAGE_EVENT", "LOGIN_EVENT", "AIRTIME_TRANSFER_EVENT",
    "BILLING_FRAUD_EVENT", "DNS_RESOLUTION_EVENT", "SERVICE_HEALTH_EVENT",
]

_DEMO_FRAUD_PROFILES: List[Dict[str, Any]] = [
    {   # SIM-swap mule chain
        "entity_type": "phone_h",
        "event_types": {"SIM_SWAP_EVENT": 8, "TRANSACTION_EVENT": 15, "LOGIN_EVENT": 3},
        "risk_flags":  ["CAMPAIGN_ENTITY"],
        "fraud_family": "SIM_SWAP",
    },
    {   # DDoS C2 node
        "entity_type": "ip",
        "event_types": {"DDOS_SIGNAL_EVENT": 40, "DNS_RESOLUTION_EVENT": 5},
        "risk_flags":  ["DDOS_ALERT_SERVICE", "DDOS_CLUSTER_MEMBER"],
        "fraud_family": "DDOS_CAMPAIGN",
    },
    {   # Airtime siphoning (Safaricom/Airtel)
        "entity_type": "provider_id",
        "event_types": {"AIRTIME_TRANSFER_EVENT": 22, "BILLING_FRAUD_EVENT": 12},
        "risk_flags":  ["AIRTIME_SIPHON_MEMBER", "CAMPAIGN_ENTITY"],
        "fraud_family": "AIRTIME_SIPHON",
    },
    {   # Multi-stage phishing pivot
        "entity_type": "phone_h",
        "event_types": {
            "PHISHING_MESSAGE_EVENT": 5,
            "SIM_SWAP_EVENT": 3,
            "DDOS_SIGNAL_EVENT": 2,
            "TRANSACTION_EVENT": 7,
        },
        "risk_flags":  ["CAMPAIGN_ENTITY"],
        "fraud_family": "MULTI_STAGE_CHAIN",
    },
    {   # Money mule account
        "entity_type": "account_h",
        "event_types": {"TRANSACTION_EVENT": 18, "LOGIN_EVENT": 2},
        "risk_flags":  ["CAMPAIGN_ENTITY"],
        "fraud_family": "MONEY_MULE",
    },
    {   # VPN obfuscated node
        "entity_type": "ip",
        "event_types": {"LOGIN_EVENT": 10, "DNS_RESOLUTION_EVENT": 6},
        "risk_flags":  ["VPN_CLUSTER_MEMBER"],
        "fraud_family": "VPN_ANONYMISER",
    },
]


class DemoConnector(BaseConnector):
    """
    Generates synthetic Kenya fraud entity records for demo / CI use.

    Produces a mix of high-risk fraud profiles and low-risk benign entities,
    randomised enough to simulate a rolling time window.
    """

    def __init__(self, n_positive: int = 30, n_negative: int = 70, seed: int = 42):
        self._n_pos = n_positive
        self._n_neg = n_negative
        self._seed  = seed

    def fetch(self, window_start: datetime, window_end: datetime) -> List[EntityRecord]:
        rng = random.Random(self._seed + int(window_end.timestamp()))
        now = _utcnow()
        records: List[EntityRecord] = []

        # --- Positive (fraud) entities ---
        for i in range(self._n_pos):
            profile = _DEMO_FRAUD_PROFILES[i % len(_DEMO_FRAUD_PROFILES)]
            etype   = profile["entity_type"]
            et      = dict(profile["event_types"])
            ec      = sum(et.values())
            flags   = list(profile["risk_flags"])

            rec: EntityRecord = {
                "entity_key":    f"{etype}:demo_fraud_{i:04d}",
                "entity_type":   etype,
                "event_count":   ec,
                "source_count":  rng.randint(2, 8),
                "degree":        rng.randint(3, 20),
                "weighted_degree": ec + rng.randint(0, 10),
                "risk_flags":    flags,
                "fraud_family":  profile.get("fraud_family"),
                "features": {
                    "event_types":             et,
                    "last_seen_age_sec":        rng.uniform(0, 60),
                    "event_types_other_count":  rng.randint(0, 3),
                },
                "first_seen": window_start + timedelta(minutes=rng.randint(0, 10)),
                "last_seen":  window_end   - timedelta(seconds=rng.randint(0, 120)),
            }
            records.append(rec)

        # --- Negative (benign) entities ---
        for i in range(self._n_neg):
            etype = rng.choice(["ip", "domain", "service_id"])
            ec    = rng.randint(1, 8)
            rec   = {
                "entity_key":    f"{etype}:demo_benign_{i:04d}",
                "entity_type":   etype,
                "event_count":   ec,
                "source_count":  rng.randint(1, 2),
                "degree":        rng.randint(1, 5),
                "weighted_degree": ec,
                "risk_flags":    [],
                "fraud_family":  None,
                "features": {
                    "event_types":             {"LOGIN_EVENT": ec, "SERVICE_HEALTH_EVENT": 1},
                    "last_seen_age_sec":        rng.uniform(60, 600),
                    "event_types_other_count":  0,
                },
                "first_seen": window_start,
                "last_seen":  window_end,
            }
            records.append(rec)

        return records


# ---------------------------------------------------------------------------
# CSV connector
# ---------------------------------------------------------------------------

class CsvConnector(BaseConnector):
    """
    Reads pre-exported event data from a CSV file.

    Expected columns (others are silently ignored):
        entity_key, entity_type, event_type, event_count, source_count,
        risk_flags (pipe-separated), timestamp (ISO-8601)
    """

    def __init__(self, path: str):
        self._path = path

    def fetch(self, window_start: datetime, window_end: datetime) -> List[EntityRecord]:
        entity_map: Dict[str, EntityRecord] = {}

        with open(self._path, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                ts_str = row.get("timestamp", "")
                try:
                    ts = datetime.fromisoformat(ts_str).replace(tzinfo=timezone.utc)
                    if ts < window_start or ts > window_end:
                        continue
                except (ValueError, TypeError):
                    continue

                key   = row.get("entity_key", "")
                etype = row.get("entity_type", "unknown")
                et    = row.get("event_type",  "OTHER")
                ec    = int(row.get("event_count",  1) or 1)
                sc    = int(row.get("source_count", 1) or 1)
                flags = [f.strip() for f in (row.get("risk_flags") or "").split("|") if f.strip()]

                if key not in entity_map:
                    entity_map[key] = {
                        "entity_key":    key,
                        "entity_type":   etype,
                        "event_count":   0,
                        "source_count":  sc,
                        "degree":        sc,
                        "weighted_degree": 0,
                        "risk_flags":    [],
                        "fraud_family":  None,
                        "features":      {"event_types": {}, "last_seen_age_sec": None, "event_types_other_count": 0},
                        "first_seen":    ts,
                        "last_seen":     ts,
                    }

                r = entity_map[key]
                r["event_count"]  += ec
                r["weighted_degree"] += ec
                r["features"]["event_types"][et] = r["features"]["event_types"].get(et, 0) + ec
                r["risk_flags"]   = list(set(r["risk_flags"]) | set(flags))
                if ts < r["first_seen"]:
                    r["first_seen"] = ts
                if ts > r["last_seen"]:
                    r["last_seen"] = ts

        now = _utcnow()
        for r in entity_map.values():
            if r["last_seen"]:
                r["features"]["last_seen_age_sec"] = (now - r["last_seen"]).total_seconds()

        return list(entity_map.values())


# ---------------------------------------------------------------------------
# Database connector — queries a live partner database via SQLAlchemy
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Built-in query presets for common Kenyan government / telco systems.
#
# Each preset defines:
#   query       — SQL with {window_start} and {window_end} placeholders
#   entity_key  — column whose value uniquely identifies the entity
#   entity_type — fixed string OR column name (prefix with "@" to read from column)
#   event_type  — fixed event type string or "@column_name"
#   risk_flags  — optional column name for pipe-separated risk flags
#   amount_col  — optional KES amount column
# ---------------------------------------------------------------------------

_DB_PRESETS: Dict[str, Dict[str, Any]] = {

    # ── KRA iTax — tax return / payment records ───────────────────────────
    # Covers PIN-linked transactions: VAT, income tax, excise, customs.
    # Risk signals: repeated zero-returns, inconsistent turnover declarations.
    "kra_tax": {
        "query": """
            SELECT
                taxpayer_pin                          AS entity_key,
                'account_h'                           AS entity_type,
                obligation_type                       AS event_type,
                filing_date                           AS occurred_at,
                declared_tax_amount                   AS amount,
                compliance_status                     AS risk_flag_raw
            FROM tax_returns
            WHERE filing_date >= '{window_start}'
              AND filing_date <  '{window_end}'
            LIMIT {batch_size}
        """,
        "entity_key":   "entity_key",
        "entity_type":  "account_h",       # fixed — all KRA entities are PIN accounts
        "event_type":   "@event_type",     # read from column
        "risk_flags":   "risk_flag_raw",
        "amount_col":   "amount",
        # Map compliance_status values → Sentinel risk flags
        "flag_map": {
            "NON_COMPLIANT":   "AUDIT_FINDING",
            "ZERO_RETURN":     "AUDIT_FINDING",
            "SUSPENDED":       "AUDIT_FINDING",
        },
    },

    # ── IFMIS — integrated financial management / government payments ─────
    # Covers Exchequer releases, supplier payments, pending bills.
    # Risk signals: year-end surges, single-source payments, repeat payees.
    "ifmis_payments": {
        "query": """
            SELECT
                supplier_code                         AS entity_key,
                'account_h'                           AS entity_type,
                'PAYMENT_DISBURSEMENT'                AS event_type,
                payment_date                          AS occurred_at,
                net_amount                            AS amount,
                ministry_code                         AS ministry,
                payment_type                          AS pay_type
            FROM payment_transactions
            WHERE payment_date >= '{window_start}'
              AND payment_date <  '{window_end}'
              AND payment_status = 'PROCESSED'
            LIMIT {batch_size}
        """,
        "entity_key":   "entity_key",
        "entity_type":  "account_h",
        "event_type":   "PAYMENT_DISBURSEMENT",
        "risk_flags":   None,
        "amount_col":   "amount",
    },

    # ── KEMSA — Kenya Medical Supplies Authority procurement ──────────────
    # Covers supplier invoices, tender awards, emergency procurement.
    # Risk signals: price inflation, single-source emergency awards.
    "kemsa_procurement": {
        "query": """
            SELECT
                supplier_id                           AS entity_key,
                'account_h'                           AS entity_type,
                procurement_method                    AS event_type,
                award_date                            AS occurred_at,
                contract_value_kes                    AS amount,
                audit_flag                            AS risk_flag_raw
            FROM procurement_orders
            WHERE award_date >= '{window_start}'
              AND award_date <  '{window_end}'
            LIMIT {batch_size}
        """,
        "entity_key":   "entity_key",
        "entity_type":  "account_h",
        "event_type":   "TENDER_AWARD",
        "risk_flags":   "risk_flag_raw",
        "amount_col":   "amount",
        "flag_map": {
            "PRICE_INFLATION":     "PRICE_INFLATION",
            "SINGLE_SOURCE":       "AUDIT_FINDING",
            "EMERGENCY":           "AUDIT_FINDING",
            "DIRECTOR_CONFLICT":   "DIRECTOR_CONFLICT",
        },
    },

    # ── M-Pesa Core Banking — mobile money transactions ───────────────────
    # Covers P2P, Buy Goods, Paybill, Withdrawal.
    # Risk signals: mule account patterns, SIM-swap → immediate withdrawal.
    "mpesa_core": {
        "query": """
            SELECT
                msisdn                                AS entity_key,
                'phone_h'                             AS entity_type,
                transaction_type                      AS event_type,
                transaction_time                      AS occurred_at,
                amount                                AS amount,
                fraud_flag                            AS risk_flag_raw
            FROM mpesa_transactions
            WHERE transaction_time >= '{window_start}'
              AND transaction_time <  '{window_end}'
            LIMIT {batch_size}
        """,
        "entity_key":   "entity_key",
        "entity_type":  "phone_h",
        "event_type":   "@event_type",
        "risk_flags":   "risk_flag_raw",
        "amount_col":   "amount",
        "flag_map": {
            "FRAUD":      "CAMPAIGN_ENTITY",
            "SUSPICIOUS": "CAMPAIGN_ENTITY",
            "SIM_SWAP":   "CAMPAIGN_ENTITY",
        },
    },

    # ── M-Pesa Agent Network — airtime / float siphoning ─────────────────
    # Covers float movements, airtime top-up reversals, agent suspensions.
    "mpesa_agent": {
        "query": """
            SELECT
                agent_msisdn                          AS entity_key,
                'provider_id'                         AS entity_type,
                transaction_category                  AS event_type,
                txn_timestamp                         AS occurred_at,
                float_amount                          AS amount,
                suspension_reason                     AS risk_flag_raw
            FROM agent_transactions
            WHERE txn_timestamp >= '{window_start}'
              AND txn_timestamp <  '{window_end}'
            LIMIT {batch_size}
        """,
        "entity_key":   "entity_key",
        "entity_type":  "provider_id",
        "event_type":   "AIRTIME_TRANSFER_EVENT",
        "risk_flags":   "risk_flag_raw",
        "amount_col":   "amount",
        "flag_map": {
            "SUSPENDED":       "AIRTIME_SIPHON_MEMBER",
            "REVERSED":        "AIRTIME_SIPHON_MEMBER",
            "OVER_LIMIT":      "CAMPAIGN_ENTITY",
        },
    },

    # ── eCitizen / Huduma — government portal access logs ────────────────
    # Covers logins, service requests, failed auth attempts.
    # Risk signals: credential stuffing, account takeover patterns.
    "ecitizen_logins": {
        "query": """
            SELECT
                national_id                           AS entity_key,
                'person_h'                            AS entity_type,
                event_action                          AS event_type,
                event_time                            AS occurred_at,
                ip_address                            AS source_ip,
                login_result                          AS risk_flag_raw
            FROM audit_log
            WHERE event_time >= '{window_start}'
              AND event_time <  '{window_end}'
            LIMIT {batch_size}
        """,
        "entity_key":   "entity_key",
        "entity_type":  "person_h",
        "event_type":   "LOGIN_EVENT",
        "risk_flags":   "risk_flag_raw",
        "amount_col":   None,
        "flag_map": {
            "FAILED":          "CAMPAIGN_ENTITY",
            "LOCKED":          "CAMPAIGN_ENTITY",
            "SUSPICIOUS_IP":   "VPN_CLUSTER_MEMBER",
        },
    },
}


def _map_flags(raw: str, flag_map: Dict[str, str]) -> List[str]:
    """Convert a raw flag value (from a DB column) to Sentinel risk flags."""
    if not raw:
        return []
    out: List[str] = []
    for part in str(raw).upper().split("|"):
        part = part.strip()
        mapped = flag_map.get(part)
        if mapped:
            out.append(mapped)
        elif part and part not in ("NONE", "NULL", "OK", "NORMAL", "COMPLIANT"):
            # Pass through unknown flags directly — analyst can review
            out.append(part)
    return list(set(out))


class DbConnector(BaseConnector):
    """
    Queries a live partner database and returns EntityRecord dicts.

    Supports any SQLAlchemy-compatible database:
        PostgreSQL  postgresql+psycopg2://user:pass@host:5432/dbname
        MySQL       mysql+pymysql://user:pass@host:3306/dbname
        MSSQL       mssql+pyodbc://user:pass@dsn
        Oracle      oracle+cx_oracle://user:pass@host:1521/SID
        SQLite      sqlite:////abs/path/to/file.db

    Built-in presets for Kenyan government systems:
        kra_tax, ifmis_payments, kemsa_procurement,
        mpesa_core, mpesa_agent, ecitizen_logins

    Custom queries can use {window_start}, {window_end}, {batch_size}
    as template placeholders.
    """

    def __init__(
        self,
        db_url: str,
        preset:           str = "",
        query:            str = "",
        entity_key_col:   str = "entity_key",
        entity_type_fixed: str = "",
        entity_type_col:  str = "entity_type",
        event_type_col:   str = "event_type",
        timestamp_col:    str = "occurred_at",
        risk_flags_col:   str = "",
        amount_col:       str = "",
        batch_size:       int = 10_000,
    ):
        if not db_url:
            raise ValueError("DbConnector requires local_db_url to be set")

        self._db_url       = db_url
        self._batch_size   = batch_size
        self._timestamp_col = timestamp_col  # always stored; used in fetch()
        self._engine       = None  # lazy — created on first fetch()

        # Resolve preset vs custom query
        cfg = _DB_PRESETS.get(preset.lower()) if preset else None
        if cfg:
            self._query          = cfg["query"].strip()
            self._entity_key_col = cfg["entity_key"]
            et = cfg.get("entity_type", "")
            self._entity_type_fixed = "" if et.startswith("@") else et
            self._entity_type_col   = et[1:] if et.startswith("@") else ""
            et2 = cfg.get("event_type", "")
            self._event_type_fixed = "" if et2.startswith("@") else et2
            self._event_type_col   = et2[1:] if et2.startswith("@") else ""
            self._risk_flags_col   = cfg.get("risk_flags") or ""
            self._amount_col       = cfg.get("amount_col") or ""
            self._flag_map: Dict[str, str] = cfg.get("flag_map", {})
            log.info("db_connector preset=%s", preset)
        else:
            if not query:
                raise ValueError(
                    "DbConnector requires either db_preset or db_query to be set. "
                    f"Available presets: {list(_DB_PRESETS)}"
                )
            self._query            = query.strip()
            self._entity_key_col   = entity_key_col
            self._entity_type_fixed = entity_type_fixed
            self._entity_type_col  = entity_type_col
            self._event_type_fixed = ""
            self._event_type_col   = event_type_col
            self._risk_flags_col   = risk_flags_col
            self._amount_col       = amount_col
            self._flag_map         = {}
            log.info("db_connector custom query len=%d", len(self._query))

    def _get_engine(self):
        if self._engine is None:
            try:
                from sqlalchemy import create_engine  # noqa: PLC0415
                self._engine = create_engine(
                    self._db_url,
                    pool_pre_ping=True,
                    connect_args={"connect_timeout": 10}
                    if "postgresql" in self._db_url or "mysql" in self._db_url
                    else {},
                )
                log.info("db_connector engine created url_prefix=%s", self._db_url[:30])
            except ImportError as exc:
                raise RuntimeError(
                    "SQLAlchemy is required for DbConnector. "
                    "Install: pip install sqlalchemy psycopg2-binary  (or pymysql / cx_oracle)"
                ) from exc
        return self._engine

    def _render_query(self, window_start: datetime, window_end: datetime) -> str:
        fmt = "%Y-%m-%d %H:%M:%S"
        return self._query.format(
            window_start=window_start.strftime(fmt),
            window_end=window_end.strftime(fmt),
            batch_size=self._batch_size,
        )

    def _parse_ts(self, val: Any) -> Optional[datetime]:
        if val is None:
            return None
        if isinstance(val, datetime):
            return val.replace(tzinfo=timezone.utc) if val.tzinfo is None else val
        try:
            return datetime.fromisoformat(str(val)).replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            return None

    def fetch(self, window_start: datetime, window_end: datetime) -> List[EntityRecord]:
        from sqlalchemy import text  # noqa: PLC0415

        engine = self._get_engine()
        sql    = self._render_query(window_start, window_end)

        log.info("db_connector fetch window=%s→%s", window_start.isoformat(), window_end.isoformat())

        try:
            with engine.connect() as conn:
                rows = conn.execute(text(sql)).mappings().fetchall()
        except Exception as exc:
            log.error("db_connector query failed: %s", exc)
            return []

        log.info("db_connector rows_fetched=%d", len(rows))

        entity_map: Dict[str, EntityRecord] = {}
        now = _utcnow()

        for row in rows:
            row = dict(row)

            # ── entity key ─────────────────────────────────────────────
            key = str(row.get(self._entity_key_col) or "").strip()
            if not key:
                continue

            # ── entity type ────────────────────────────────────────────
            if self._entity_type_fixed:
                etype = self._entity_type_fixed
            elif self._entity_type_col and self._entity_type_col in row:
                etype = str(row[self._entity_type_col] or "unknown").strip()
            else:
                etype = "account_h"

            # Prefix entity_key with type if not already prefixed
            if ":" not in key:
                full_key = f"{etype}:{key}"
            else:
                full_key = key

            # ── event type ─────────────────────────────────────────────
            if self._event_type_fixed:
                evtype = self._event_type_fixed
            elif self._event_type_col and self._event_type_col in row:
                evtype = str(row[self._event_type_col] or "OTHER").strip().upper()
            else:
                evtype = "TRANSACTION_EVENT"

            # ── timestamps ─────────────────────────────────────────────
            ts = self._parse_ts(row.get(self._timestamp_col or "occurred_at"))
            if ts and (ts < window_start or ts > window_end):
                continue  # extra safety filter

            # ── risk flags ─────────────────────────────────────────────
            raw_flag = str(row.get(self._risk_flags_col) or "") if self._risk_flags_col else ""
            flags = _map_flags(raw_flag, self._flag_map)

            # ── amount (optional enrichment) ───────────────────────────
            amount_raw = row.get(self._amount_col) if self._amount_col else None
            try:
                amount = float(amount_raw) if amount_raw is not None else 0.0
            except (TypeError, ValueError):
                amount = 0.0

            # ── aggregate per entity ───────────────────────────────────
            if full_key not in entity_map:
                entity_map[full_key] = {
                    "entity_key":      full_key,
                    "entity_type":     etype,
                    "event_count":     0,
                    "source_count":    1,
                    "degree":          1,
                    "weighted_degree": 0,
                    "risk_flags":      [],
                    "fraud_family":    None,
                    "features": {
                        "event_types":             {},
                        "last_seen_age_sec":        None,
                        "event_types_other_count":  0,
                        "total_amount_ksh":         0.0,
                    },
                    "first_seen": ts,
                    "last_seen":  ts,
                }

            r = entity_map[full_key]
            r["event_count"]    += 1
            r["weighted_degree"] += max(1, math.ceil(math.log1p(amount))) if amount else 1
            r["features"]["event_types"][evtype] = r["features"]["event_types"].get(evtype, 0) + 1
            r["features"]["total_amount_ksh"]    += amount
            r["risk_flags"] = list(set(r["risk_flags"]) | set(flags))

            if ts:
                if r["first_seen"] is None or ts < r["first_seen"]:
                    r["first_seen"] = ts
                if r["last_seen"] is None or ts > r["last_seen"]:
                    r["last_seen"] = ts

        # Fill in last_seen_age_sec
        for r in entity_map.values():
            if r["last_seen"]:
                r["features"]["last_seen_age_sec"] = (now - r["last_seen"]).total_seconds()
            r["degree"] = max(1, len(r["features"]["event_types"]))

        result = list(entity_map.values())
        log.info("db_connector entities_built=%d", len(result))
        return result


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def get_connector() -> BaseConnector:
    src = settings.data_source.lower()
    if src == "csv":
        return CsvConnector(settings.csv_path)
    if src in ("db", "postgres", "database"):
        return DbConnector(
            db_url            = settings.local_db_url,
            preset            = settings.db_preset,
            query             = settings.db_query,
            entity_key_col    = settings.db_entity_key_col,
            entity_type_fixed = settings.db_entity_type_fixed,
            entity_type_col   = settings.db_entity_type_col,
            event_type_col    = settings.db_event_type_col,
            timestamp_col     = settings.db_timestamp_col,
            risk_flags_col    = settings.db_risk_flags_col,
            amount_col        = settings.db_amount_col,
            batch_size        = settings.db_batch_size,
        )
    # Default → demo
    return DemoConnector()

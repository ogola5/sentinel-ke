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
DbConnector     Reads from a local PostgreSQL database (partner's own schema).

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
import math
import random
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from app.config import settings


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
# Factory
# ---------------------------------------------------------------------------

def get_connector() -> BaseConnector:
    src = settings.data_source.lower()
    if src == "csv":
        return CsvConnector(settings.csv_path)
    # Default → demo
    return DemoConnector()

"""
ThreatFox IOC ingestor (layer3).

Pulls recent IOCs from the ThreatFox API and writes:
  - EventLog rows  (event_type=THREAT_INTEL_IOC)
  - EventEntityIndex rows
  - GraphFeatureSnapshot rows  (window_key="Wthreatfox")

Usage:
    python -m app.analytics.layer3.threatfox_ingest
"""
from __future__ import annotations

import hashlib
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence
from urllib.parse import urlsplit

import requests
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

import app.db.registry  # noqa: F401 – registers all ORM models before create_all
from app.analytics.ai_models import GraphFeatureSnapshot
from app.core.security import hash_api_key
from app.db.base import Base
from app.ledger.db import SessionLocal, engine
from app.ledger.models import EventEntityIndex, EventLog, SourceRegistry
from app.ledger.repository import _key_lookup_hash

log = logging.getLogger("sentinel.layer3.threatfox_ingest")

_THREATFOX_API_URL = "https://threatfox-api.abuse.ch/api/v1/"
_SOURCE_ID = "threatfox_ioc"
_SOURCE_API_KEY = "threatfox-live-secret-key"
_CLASSIFICATION = "RESTRICTED"
_WINDOW_KEY = "Wthreatfox"
_SECTION_CODE = "KE-CIRT"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _event_hash(*parts: str) -> str:
    return "tf:" + hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:56]


def _extract_ip_from_ip_port(value: str) -> str:
    """Extract the IP from 'ip:port' format, handling IPv6 brackets."""
    value = value.strip()
    if value.startswith("["):
        # IPv6 bracket notation: [::1]:443
        end = value.find("]")
        return value[1:end] if end != -1 else value
    if ":" in value:
        parts = value.rsplit(":", 1)
        return parts[0]
    return value


def _extract_domain_from_url(url: str) -> Optional[str]:
    try:
        parsed = urlsplit(url.strip())
        host = (parsed.hostname or "").strip().lower()
        return host or None
    except Exception:
        return None


def _map_ioc_to_entity(ioc_type: str, ioc_value: str):
    """Return (entity_type, entity_key) for a given ThreatFox IOC."""
    t = ioc_type.strip().lower()
    v = ioc_value.strip()
    if t == "ip:port":
        ip = _extract_ip_from_ip_port(v)
        return "ip", f"ip:{ip}"
    if t == "domain":
        return "domain", f"domain:{v.lower()}"
    if t == "url":
        return "url", f"url:{v}"
    # Fallback: treat as domain if it looks like one, else url
    if "/" not in v and "." in v:
        return "domain", f"domain:{v.lower()}"
    return "url", f"url:{v}"


# ---------------------------------------------------------------------------
# Source registration
# ---------------------------------------------------------------------------

def _ensure_source(db: Session) -> None:
    stmt = (
        pg_insert(SourceRegistry)
        .values(
            source_id=_SOURCE_ID,
            source_type="cyber_threat_intel",
            section_code=_SECTION_CODE,
            classification_level=_CLASSIFICATION,
            api_key_hash=hash_api_key(_SOURCE_API_KEY),
            api_key_lookup=_key_lookup_hash(_SOURCE_API_KEY),
            is_active=True,
        )
        .on_conflict_do_nothing(index_elements=["source_id"])
    )
    db.execute(stmt)
    db.flush()


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------

def fetch_threatfox_iocs(
    *,
    days: int = 7,
    api_url: str = _THREATFOX_API_URL,
    auth_key: Optional[str] = None,
    timeout_sec: int = 30,
    poster=None,
) -> List[Dict[str, Any]]:
    """Call the ThreatFox API and return a flat list of IOC dicts."""
    if poster is None:
        poster = requests.post
    key = (
        auth_key
        or os.environ.get("THREATFOX_AUTH_KEY")
        or os.environ.get("ABUSECH_AUTH_KEY")
        or os.environ.get("URLHAUS_AUTH_KEY")
        or ""
    ).strip()
    headers = {"Auth-Key": key} if key else None
    resp = poster(
        api_url,
        json={"query": "get_iocs", "days": days},
        headers=headers,
        timeout=timeout_sec,
    )
    resp.raise_for_status()
    payload = resp.json()
    if not isinstance(payload, dict):
        raise ValueError("ThreatFox response is not a JSON object")
    data = payload.get("data")
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    return []


# ---------------------------------------------------------------------------
# Ingest
# ---------------------------------------------------------------------------

def run_ingest(
    db: Session,
    *,
    days: int = 7,
    api_url: str = _THREATFOX_API_URL,
    auth_key: Optional[str] = None,
    timeout_sec: int = 30,
    max_records: Optional[int] = None,
    poster=None,
    iocs: Optional[Sequence[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Fetch recent ThreatFox IOCs and write EventLog + GraphFeatureSnapshot rows.

    Parameters
    ----------
    iocs : pre-fetched list of IOC dicts (skips the HTTP call; useful in tests).
    """
    Base.metadata.create_all(bind=engine)
    _ensure_source(db)

    if iocs is None:
        try:
            iocs = fetch_threatfox_iocs(
                days=days,
                api_url=api_url,
                auth_key=auth_key,
                timeout_sec=timeout_sec,
                poster=poster,
            )
        except Exception as exc:
            log.warning("threatfox_fetch_failed err=%s", exc)
            return {"status": "fetch_error", "error": str(exc), "events": 0, "snapshots": 0}

    if max_records is not None:
        iocs = list(iocs)[: max(0, int(max_records))]

    if not iocs:
        return {"status": "no_data", "events": 0, "snapshots": 0}

    now = _utcnow()
    window_start = now - timedelta(days=days)
    window_end = now

    # entity_key -> first/last seen, event_count
    entity_stats: Dict[str, Dict[str, Any]] = {}

    event_count = 0
    for idx, ioc in enumerate(iocs):
        ioc_type = str(ioc.get("ioc_type") or ioc.get("indicator_type") or "").strip()
        ioc_value = str(ioc.get("ioc") or ioc.get("indicator") or ioc.get("value") or "").strip()
        if not ioc_type or not ioc_value:
            continue

        entity_type, entity_key = _map_ioc_to_entity(ioc_type, ioc_value)
        malware = str(ioc.get("malware") or ioc.get("malware_printable") or ioc.get("threat_type") or "").strip() or None
        tags = ioc.get("tags") or []
        first_seen_raw = ioc.get("first_seen") or ioc.get("date_added") or ioc.get("created")
        try:
            if first_seen_raw:
                first_seen = datetime.fromisoformat(str(first_seen_raw).replace("Z", "+00:00"))
                if first_seen.tzinfo is None:
                    first_seen = first_seen.replace(tzinfo=timezone.utc)
            else:
                first_seen = now
        except Exception:
            first_seen = now

        ev_hash = _event_hash("THREAT_INTEL_IOC", entity_key, ioc_type, ioc_value, str(idx))

        stmt = pg_insert(EventLog).values(
            event_hash=ev_hash,
            event_type="THREAT_INTEL_IOC",
            source_id=_SOURCE_ID,
            section_code=_SECTION_CODE,
            classification=_CLASSIFICATION,
            occurred_at=first_seen,
            received_at=now,
            schema_version="v1",
            signature_valid=False,
            anchors_json={entity_type: entity_key.split(":", 1)[-1] if ":" in entity_key else entity_key},
            payload_json={
                "ioc": ioc_value,
                "ioc_type": ioc_type,
                "entity_type": entity_type,
                "entity_key": entity_key,
                "malware": malware,
                "tags": tags,
                "source": "threatfox",
            },
        ).on_conflict_do_nothing(index_elements=["event_hash"])
        db.execute(stmt)

        stmt2 = pg_insert(EventEntityIndex).values(
            event_hash=ev_hash,
            entity_key=entity_key,
            entity_type=entity_type,
        ).on_conflict_do_nothing(index_elements=["event_hash", "entity_key"])
        db.execute(stmt2)

        event_count += 1

        if entity_key not in entity_stats:
            entity_stats[entity_key] = {
                "entity_type": entity_type,
                "first_seen": first_seen,
                "last_seen": first_seen,
                "event_count": 0,
            }
        s = entity_stats[entity_key]
        s["event_count"] += 1
        if first_seen < s["first_seen"]:
            s["first_seen"] = first_seen
        if first_seen > s["last_seen"]:
            s["last_seen"] = first_seen

    # Upsert GraphFeatureSnapshot rows
    snap_rows = []
    for entity_key, s in entity_stats.items():
        snap_rows.append(
            {
                "entity_key": entity_key,
                "entity_type": s["entity_type"],
                "window_key": _WINDOW_KEY,
                "window_start": window_start,
                "window_end": window_end,
                "degree": s["event_count"],
                "weighted_degree": s["event_count"],
                "event_count": s["event_count"],
                "first_seen": s["first_seen"],
                "last_seen": s["last_seen"],
                "risk_flags": ["THREAT_INTEL_HIT", "MALWARE_INDICATOR"],
                "features": {"source": "threatfox", "ioc_count": s["event_count"]},
                "created_at": now,
            }
        )

    if snap_rows:
        stmt3 = pg_insert(GraphFeatureSnapshot).values(snap_rows)
        stmt3 = stmt3.on_conflict_do_update(
            index_elements=["entity_key", "window_key", "window_end"],
            set_={
                "event_count": stmt3.excluded.event_count,
                "degree": stmt3.excluded.degree,
                "weighted_degree": stmt3.excluded.weighted_degree,
                "first_seen": stmt3.excluded.first_seen,
                "last_seen": stmt3.excluded.last_seen,
                "risk_flags": stmt3.excluded.risk_flags,
                "features": stmt3.excluded.features,
            },
        )
        db.execute(stmt3)

    db.commit()
    return {
        "status": "ok",
        "events": event_count,
        "snapshots": len(snap_rows),
        "entities": len(entity_stats),
    }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    import argparse
    import json

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Ingest ThreatFox IOCs into Sentinel-KE graph tables.")
    parser.add_argument("--days", type=int, default=7, help="Number of days of IOC history to pull.")
    parser.add_argument("--api-url", default=_THREATFOX_API_URL, help="ThreatFox API endpoint.")
    parser.add_argument("--auth-key", default=None, help="abuse.ch Auth-Key. Falls back to THREATFOX_AUTH_KEY, ABUSECH_AUTH_KEY, or URLHAUS_AUTH_KEY.")
    parser.add_argument("--timeout-sec", type=int, default=30)
    parser.add_argument("--max-records", type=int, default=None)
    args = parser.parse_args()

    db = SessionLocal()
    try:
        result = run_ingest(
            db,
            days=args.days,
            api_url=args.api_url,
            auth_key=args.auth_key,
            timeout_sec=args.timeout_sec,
            max_records=args.max_records,
        )
        print(json.dumps(result))
    finally:
        db.close()


if __name__ == "__main__":
    main()

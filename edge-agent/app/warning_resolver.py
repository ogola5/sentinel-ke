"""
Sentinel-KE Edge Agent — Local warning resolution
=================================================

The hub only sees hashed entity identifiers. This module keeps a local hash
index on the edge node so hub warning envelopes can be resolved back to the
agency's raw identifiers without leaking them off the node.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from app.config import settings
from app.gnn_runner import GNNResult


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _hash_entity_key(raw_key: str) -> str:
    return hmac.new(
        settings.national_salt.encode(),
        raw_key.encode(),
        hashlib.sha256,
    ).hexdigest()


def _safe_iso(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _load_json(path_str: str, *, default: Dict[str, Any]) -> Dict[str, Any]:
    path = Path(path_str).expanduser()
    if not path.exists():
        return dict(default)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return dict(default)
    return payload if isinstance(payload, dict) else dict(default)


def _write_json(path_str: str, payload: Dict[str, Any]) -> None:
    path = Path(path_str).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )


def load_hash_index() -> Dict[str, Any]:
    return _load_json(
        settings.hash_index_path,
        default={
            "partner_id": settings.partner_id,
            "updated_at": None,
            "retention_days": int(settings.hash_index_retention_days),
            "entries": {},
        },
    )


def save_hash_index(payload: Dict[str, Any]) -> None:
    _write_json(settings.hash_index_path, payload)


def load_warning_cache() -> Dict[str, Any]:
    return _load_json(
        settings.warning_cache_path,
        default={
            "partner_id": settings.partner_id,
            "last_synced_at": None,
            "warning_count": 0,
            "warnings": [],
        },
    )


def save_warning_cache(payload: Dict[str, Any]) -> None:
    _write_json(settings.warning_cache_path, payload)


def _prune_hash_entries(entries: Dict[str, Dict[str, Any]], *, now: datetime) -> Dict[str, Dict[str, Any]]:
    cutoff = now - timedelta(days=max(1, int(settings.hash_index_retention_days)))
    kept: Dict[str, Dict[str, Any]] = {}
    for entity_hash, entry in entries.items():
        last_seen_raw = entry.get("last_seen")
        if not isinstance(last_seen_raw, str):
            kept[entity_hash] = entry
            continue
        try:
            last_seen = datetime.fromisoformat(last_seen_raw)
        except ValueError:
            kept[entity_hash] = entry
            continue
        if last_seen.tzinfo is None:
            last_seen = last_seen.replace(tzinfo=timezone.utc)
        if last_seen >= cutoff:
            kept[entity_hash] = entry
    return kept


def update_hash_index(
    results: Iterable[GNNResult],
    *,
    observed_at: Optional[datetime] = None,
) -> Dict[str, Any]:
    now = observed_at or _utcnow()
    payload = load_hash_index()
    raw_entries = payload.get("entries")
    entries: Dict[str, Dict[str, Any]] = raw_entries if isinstance(raw_entries, dict) else {}
    entries = _prune_hash_entries(entries, now=now)

    updated = 0
    for result in results:
        entity_hash = _hash_entity_key(result.entity_key)
        existing = dict(entries.get(entity_hash) or {})
        first_seen = existing.get("first_seen") or _safe_iso(now)
        observed_count = int(existing.get("observed_count") or 0) + 1
        flags = sorted(set(list(existing.get("risk_flags") or []) + list(result.risk_flags or [])))
        entries[entity_hash] = {
            "entity_key_hash": entity_hash,
            "entity_key": result.entity_key,
            "entity_type": result.entity_type,
            "first_seen": first_seen,
            "last_seen": _safe_iso(now),
            "observed_count": observed_count,
            "last_risk_score": round(float(result.risk_score or 0.0), 4),
            "last_uncertainty": round(float(result.uncertainty or 0.0), 4),
            "chain_score": round(float(result.chain_score or 0.0), 4),
            "fraud_family": result.fraud_family,
            "risk_flags": flags,
        }
        updated += 1

    payload["partner_id"] = settings.partner_id
    payload["updated_at"] = _safe_iso(now)
    payload["retention_days"] = int(settings.hash_index_retention_days)
    payload["entries"] = entries
    save_hash_index(payload)
    return {
        "updated": updated,
        "entry_count": len(entries),
        "updated_at": payload["updated_at"],
    }


def resolve_warning(warning: Dict[str, Any], *, hash_index: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    payload = dict(warning or {})
    hash_index = hash_index or load_hash_index()
    entries = hash_index.get("entries")
    entry = None
    if isinstance(entries, dict):
        entry = entries.get(str(payload.get("entity_key_hash") or ""))

    if isinstance(entry, dict):
        payload["locally_resolved"] = True
        payload["resolution_state"] = "resolved_local_match"
        payload["local_matches"] = [dict(entry)]
        payload["local_match_count"] = 1
    else:
        payload["locally_resolved"] = False
        payload["resolution_state"] = "hash_not_seen_locally"
        payload["local_matches"] = []
        payload["local_match_count"] = 0
    return payload


def sync_warning_cache(
    warnings: Iterable[Dict[str, Any]],
    *,
    fetched_at: Optional[datetime] = None,
) -> Dict[str, Any]:
    now = fetched_at or _utcnow()
    hash_index = load_hash_index()
    resolved_warnings = [
        resolve_warning(dict(warning or {}), hash_index=hash_index)
        for warning in warnings
    ]
    payload = {
        "partner_id": settings.partner_id,
        "last_synced_at": _safe_iso(now),
        "warning_count": len(resolved_warnings),
        "warnings": resolved_warnings,
    }
    save_warning_cache(payload)
    return payload


def record_warning_ack(
    warning_id: str,
    *,
    status: str,
    detail: Optional[Dict[str, Any]] = None,
    acknowledged_at: Optional[str] = None,
) -> Dict[str, Any]:
    payload = load_warning_cache()
    warnings = list(payload.get("warnings") or [])
    for warning in warnings:
        if str(warning.get("id")) != str(warning_id):
            continue
        warning["partner_ack_status"] = status
        warning["partner_ack_detail"] = dict(detail or {})
        warning["partner_acknowledged_at"] = acknowledged_at or _safe_iso(_utcnow())
        break
    payload["warnings"] = warnings
    save_warning_cache(payload)
    return payload

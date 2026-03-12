"""
Sentinel-KE Edge Sync Agent
============================

Runs on an agency station (bank, telco, government).

After each local GNN inference cycle the edge agent:
  1. Reads high-risk AIPrediction rows created since the last push.
  2. HMAC-SHA256 hashes every entity_key with the national correlation
     salt so the hub NEVER sees raw entity identifiers.
  3. Pushes a PatternBatch to the central hub's
     POST /v1/federation/patterns endpoint.
  4. Saves the high-water mark so the next run only sends new data.

The hub stores the hashed patterns and runs cross-partner correlation
queries.  If the same hashed entity appears at Safaricom AND Equity Bank
in the same window, the hub escalates to NCSC without either partner
ever having shared raw customer data.

Configuration (all from environment / .env):
    IS_EDGE_NODE=true               enable this worker
    EDGE_PARTNER_ID=safaricom-ke    partner ID issued at registration
    EDGE_HUB_URL=https://...        central hub base URL
    EDGE_HUB_API_KEY=...            API key issued at registration
    EDGE_NATIONAL_SALT=...          correlation salt from registration
    EDGE_SYNC_MIN_RISK=0.6          minimum risk_score to include
    EDGE_SYNC_BATCH_SIZE=200        max entities per push
    EDGE_SYNC_LOOKBACK_HOURS=4      safety lookback on cold start

Usage (docker-compose):
    command: >
      /bin/sh -c "while true;
        do python -m app.sync.edge_agent; sleep 120; done"
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

import httpx
from sqlalchemy.orm import Session

from app.analytics.ai_models import AIPrediction
from app.core.config import settings
from app.ledger.db import SessionLocal

log = logging.getLogger("sentinel.edge_agent")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [edge-agent] %(levelname)s %(message)s",
)

# ---------------------------------------------------------------------------
# Sync state — persisted as a single JSON file in the artifacts directory
# ---------------------------------------------------------------------------

_STATE_FILE = Path(os.environ.get("GNN_ARTIFACT_DIR", "/app/artifacts/gnn")).parent / "edge_sync_state.json"


def _load_state() -> dict:
    if _STATE_FILE.exists():
        try:
            return json.loads(_STATE_FILE.read_text())
        except Exception:
            pass
    return {"last_synced_at": None, "total_pushed": 0, "last_error": None}


def _save_state(state: dict) -> None:
    _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _STATE_FILE.write_text(json.dumps(state, default=str))


# ---------------------------------------------------------------------------
# Entity key hashing — privacy-preserving cross-partner correlation
# ---------------------------------------------------------------------------

def _hash_entity(entity_key: str, national_salt: str) -> str:
    """
    HMAC-SHA256(entity_key, national_salt).

    The national_salt is shared across all registered partners so that the
    same underlying entity produces the same hash on every partner's
    station, enabling cross-partner correlation on the hub without sharing
    raw entity identifiers.

    SECURITY NOTE — brute-force risk for finite key spaces:
    Kenyan phone numbers have ~10^8 values.  If the national_salt leaks,
    an attacker can recover phone numbers in seconds.  Mitigations:
      - Keep EDGE_NATIONAL_SALT in Docker secrets, not .env files in git.
      - Rotate the salt annually (breaks historical correlations but limits
        the exposure window of any compromised salt).
      - The entity_key format "type:value" (e.g. "phone:0712345678") adds
        the type as an implicit pepper, separating key spaces per type.
    """
    return hmac.new(
        national_salt.encode(),
        entity_key.encode(),
        hashlib.sha256,
    ).hexdigest()


# ---------------------------------------------------------------------------
# Fraud family inference from kill-chain stage
# ---------------------------------------------------------------------------

_STAGE_TO_FAMILY = {
    "initial_access":       "PHISHING",
    "credential_access":    "ATO",
    "lateral_movement":     "LATERAL_MOVE",
    "impact":               "FRAUD_EXECUTION",
    "exfiltration":         "DATA_EXFIL",
    "command_and_control":  "C2",
    "reconnaissance":       "RECON",
    "resource_development": "INFRA_BUILD",
}


def _infer_fraud_family(kill_chain_stage: Optional[str], reason_codes: list) -> Optional[str]:
    if kill_chain_stage and kill_chain_stage in _STAGE_TO_FAMILY:
        return _STAGE_TO_FAMILY[kill_chain_stage]
    # fall back to first reason code that looks like a family label
    for code in (reason_codes or []):
        if isinstance(code, str) and code.isupper() and len(code) <= 20:
            return code
    return None


# ---------------------------------------------------------------------------
# Core push logic
# ---------------------------------------------------------------------------

def _fetch_unsynced(db: Session, since: datetime, min_risk: float, limit: int) -> List[AIPrediction]:
    return (
        db.query(AIPrediction)
        .filter(AIPrediction.created_at >= since)
        .filter(AIPrediction.score >= min_risk)
        .filter(AIPrediction.abstained.is_(False))
        .order_by(AIPrediction.created_at.asc())
        .limit(limit)
        .all()
    )


def _build_payload(
    rows: List[AIPrediction],
    partner_id: str,
    national_salt: str,
    model_version: str,
) -> dict:
    now = datetime.now(timezone.utc)
    window_start = min(r.window_end for r in rows) if rows else now
    window_end   = max(r.window_end for r in rows) if rows else now

    entities = []
    for row in rows:
        reason_codes = list(row.reason_codes or [])
        entities.append({
            "entity_key_hash": _hash_entity(str(row.entity_key), national_salt),
            "entity_type":     row.entity_type or "unknown",
            "risk_score":      round(float(row.score) / 100.0, 4),   # normalise 0-100 → 0-1
            "uncertainty":     round(float(row.uncertainty), 4),
            "fraud_family":    _infer_fraud_family(row.kill_chain_stage, reason_codes),
            "chain_score":     0.0,
            "risk_flags":      [c for c in reason_codes if isinstance(c, str)][:10],
        })

    high_risk = [e for e in entities if e["risk_score"] >= 0.7]
    mean_risk  = round(sum(e["risk_score"] for e in entities) / len(entities), 4) if entities else 0.0

    return {
        "partner_id":        partner_id,
        "schema_version":    "1.0",
        "window_start":      window_start.isoformat(),
        "window_end":        window_end.isoformat(),
        "gnn_model_version": model_version,
        "high_risk_entities": entities,
        "summary": {
            "total_entities_scored": len(entities),
            "high_risk_count":       len(high_risk),
            "mean_risk_score":       mean_risk,
            "top_fraud_family":      None,
            "gnn_auc":               None,
        },
    }


def run_once(
    *,
    partner_id: str,
    hub_url: str,
    hub_api_key: str,
    national_salt: str,
    min_risk: float,
    batch_size: int,
    lookback_hours: int,
) -> dict:
    state = _load_state()

    # Determine since timestamp
    if state["last_synced_at"]:
        since = datetime.fromisoformat(state["last_synced_at"])
    else:
        since = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
        log.info("Cold start — looking back %d hours", lookback_hours)

    db = SessionLocal()
    try:
        rows = _fetch_unsynced(db, since, min_risk, batch_size)
    finally:
        db.close()

    if not rows:
        log.info("Nothing to sync since %s", since.isoformat())
        state["last_synced_at"] = datetime.now(timezone.utc).isoformat()
        _save_state(state)
        return {"synced": 0, "skipped": 0}

    model_version = rows[-1].model_version if rows else "unknown"
    payload = _build_payload(rows, partner_id, national_salt, model_version)

    hub_endpoint = hub_url.rstrip("/") + "/v1/federation/patterns"
    body_bytes = json.dumps(payload, default=str).encode()
    # HMAC-SHA256 of the request body so the hub can verify the payload
    # was not tampered with in transit and originated from this key holder.
    body_sig = hmac.new(hub_api_key.encode(), body_bytes, hashlib.sha256).hexdigest()
    try:
        resp = httpx.post(
            hub_endpoint,
            content=body_bytes,
            headers={
                "X-API-Key": hub_api_key,
                "X-Sentinel-Signature": f"sha256={body_sig}",
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )
        resp.raise_for_status()
        result = resp.json()
        accepted = result.get("accepted", len(rows))
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text[:200] if exc.response else ""
        log.error("Hub rejected batch: %s %s", exc.response.status_code, detail)
        state["last_error"] = f"HTTP {exc.response.status_code}: {detail}"
        _save_state(state)
        return {"synced": 0, "error": state["last_error"]}
    except Exception as exc:
        log.error("Push failed: %s", exc)
        state["last_error"] = str(exc)
        _save_state(state)
        return {"synced": 0, "error": str(exc)}

    # Advance high-water mark to just after the last row we sent
    new_hwm = max(r.created_at for r in rows)
    if new_hwm.tzinfo is None:
        new_hwm = new_hwm.replace(tzinfo=timezone.utc)
    # Add 1 microsecond so the next query doesn't re-fetch the last row
    state["last_synced_at"] = (new_hwm + timedelta(microseconds=1)).isoformat()
    state["total_pushed"]   = (state.get("total_pushed") or 0) + accepted
    state["last_error"]     = None
    _save_state(state)

    log.info(
        "Pushed %d entities to hub (%s). Total pushed all-time: %d",
        accepted,
        partner_id,
        state["total_pushed"],
    )
    return {"synced": accepted, "partner_id": partner_id, "hub_endpoint": hub_endpoint}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Sentinel-KE edge sync agent")
    parser.add_argument("--partner-id",     default=os.environ.get("EDGE_PARTNER_ID", ""))
    parser.add_argument("--hub-url",        default=os.environ.get("EDGE_HUB_URL", ""))
    parser.add_argument("--hub-api-key",    default=os.environ.get("EDGE_HUB_API_KEY", ""))
    parser.add_argument("--national-salt",  default=os.environ.get("EDGE_NATIONAL_SALT", ""))
    parser.add_argument("--min-risk",       type=float, default=float(os.environ.get("EDGE_SYNC_MIN_RISK", "60.0")))
    parser.add_argument("--batch-size",     type=int,   default=int(os.environ.get("EDGE_SYNC_BATCH_SIZE", "200")))
    parser.add_argument("--lookback-hours", type=int,   default=int(os.environ.get("EDGE_SYNC_LOOKBACK_HOURS", "4")))
    args = parser.parse_args()

    # Guard: skip silently if not configured as an edge node
    if not settings.is_edge_node:
        log.info("IS_EDGE_NODE is false — edge sync agent is idle")
        sys.exit(0)

    missing = [k for k, v in {
        "EDGE_PARTNER_ID":    args.partner_id,
        "EDGE_HUB_URL":       args.hub_url,
        "EDGE_HUB_API_KEY":   args.hub_api_key,
        "EDGE_NATIONAL_SALT": args.national_salt,
    }.items() if not v]
    if missing:
        log.error("Missing required edge config: %s", ", ".join(missing))
        sys.exit(1)

    result = run_once(
        partner_id=args.partner_id,
        hub_url=args.hub_url,
        hub_api_key=args.hub_api_key,
        national_salt=args.national_salt,
        min_risk=args.min_risk,
        batch_size=args.batch_size,
        lookback_hours=args.lookback_hours,
    )
    log.info("Run complete: %s", result)


if __name__ == "__main__":
    main()

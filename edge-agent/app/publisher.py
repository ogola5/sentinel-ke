"""
Sentinel-KE Edge Agent — Hub Publisher
========================================

Hashes entity keys with the shared national correlation salt, filters to
entities above the risk threshold, and POSTs a PatternBatch to the national
hub.

Privacy guarantee
-----------------
Raw entity keys (phone numbers, account IDs, IP addresses) NEVER leave
the partner's perimeter.  Only HMAC-SHA256(entity_key, national_salt) is
transmitted, so the hub can detect "same hashed entity flagged by two
different banks" without learning what the actual entity is.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

from app.config import settings
from app.gnn_runner import GNNResult

logger = logging.getLogger(__name__)


def _hash_entity_key(raw_key: str) -> str:
    """
    HMAC-SHA256(entity_key, national_salt) — uses the hub's shared national
    correlation salt so the same entity produces the same hash at every
    partner, enabling cross-partner threat correlation.

    The per-partner hmac_salt is NOT used here; it is reserved for any
    local processing that must remain opaque between partners.
    """
    return hmac.new(
        settings.national_salt.encode(),
        raw_key.encode(),
        hashlib.sha256,
    ).hexdigest()


def _build_payload(
    results:      List[GNNResult],
    window_start: datetime,
    window_end:   datetime,
) -> Dict[str, Any]:
    high_risk = [r for r in results if r.risk_score >= settings.risk_threshold]

    if high_risk:
        mean_risk = sum(r.risk_score for r in high_risk) / len(high_risk)
        top_family_counts: Dict[str, int] = {}
        for r in high_risk:
            if r.fraud_family:
                top_family_counts[r.fraud_family] = top_family_counts.get(r.fraud_family, 0) + 1
        top_family = max(top_family_counts, key=top_family_counts.get) if top_family_counts else None
    else:
        mean_risk  = 0.0
        top_family = None

    return {
        "partner_id":         settings.partner_id,
        "schema_version":     "1.0",
        "window_start":       window_start.isoformat(),
        "window_end":         window_end.isoformat(),
        "gnn_model_version":  settings.model_version,
        "high_risk_entities": [
            {
                "entity_key_hash": _hash_entity_key(r.entity_key),
                "entity_type":     r.entity_type,
                "risk_score":      r.risk_score,
                "uncertainty":     r.uncertainty,
                "fraud_family":    r.fraud_family,
                "chain_score":     r.chain_score,
                "risk_flags":      r.risk_flags,
            }
            for r in high_risk
        ],
        "summary": {
            "total_entities_scored": len(results),
            "high_risk_count":       len(high_risk),
            "mean_risk_score":       round(mean_risk, 4),
            "top_fraud_family":      top_family,
            "gnn_auc":               None,  # set externally if evaluation is run
        },
    }


def _signed_headers(body_bytes: bytes) -> Dict[str, str]:
    signature = hmac.new(settings.hub_api_key.encode(), body_bytes, hashlib.sha256).hexdigest()
    return {
        "X-API-Key": settings.hub_api_key,
        "X-Sentinel-Signature": f"sha256={signature}",
        "Content-Type": "application/json",
    }


def _signed_post(path: str, payload: Dict[str, Any], *, timeout_s: int) -> Dict[str, Any]:
    body_bytes = json.dumps(payload, default=str).encode()
    url = f"{settings.hub_url.rstrip('/')}{path}"
    response = httpx.post(url, content=body_bytes, headers=_signed_headers(body_bytes), timeout=timeout_s)
    response.raise_for_status()
    return response.json()


def _api_key_headers() -> Dict[str, str]:
    return {"X-API-Key": settings.hub_api_key}


def publish(
    results:      List[GNNResult],
    window_start: datetime,
    window_end:   datetime,
    timeout_s:    int = 30,
) -> Dict[str, Any]:
    """
    POST the pattern batch to the national hub.

    Returns the hub's JSON response on success.
    Raises httpx.HTTPStatusError on 4xx/5xx.
    """
    payload = _build_payload(results, window_start, window_end)
    high_count = len(payload["high_risk_entities"])

    if high_count == 0:
        logger.info("No high-risk entities above threshold %.2f — skipping publish", settings.risk_threshold)
        return {"accepted": 0, "skipped": True}

    logger.info(
        "Publishing %d high-risk entities to hub (%s)…",
        high_count,
        f"{settings.hub_url.rstrip('/')}/v1/federation/patterns",
    )
    resp_json = _signed_post("/v1/federation/patterns", payload, timeout_s=timeout_s)
    logger.info("Hub accepted %d patterns for partner '%s'", resp_json.get("accepted", 0), settings.partner_id)
    return resp_json


def send_heartbeat(
    payload: Dict[str, Any],
    *,
    timeout_s: int = 10,
) -> Dict[str, Any]:
    logger.info("Sending edge heartbeat to hub (%s)…", f"{settings.hub_url.rstrip('/')}/v1/federation/heartbeat")
    return _signed_post("/v1/federation/heartbeat", payload, timeout_s=timeout_s)


def check_hub_connectivity(*, timeout_s: int = 10) -> Dict[str, Any]:
    url = f"{settings.hub_url.rstrip('/')}/health"
    response = httpx.get(url, timeout=timeout_s)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        payload = {"status": "unknown"}
    payload["hub_url"] = settings.hub_url
    return payload


def fetch_warning_inbox(
    *,
    status: str = "open",
    limit: int = 100,
    timeout_s: int = 15,
) -> Dict[str, Any]:
    url = f"{settings.hub_url.rstrip('/')}/v1/federation/warnings/inbox"
    response = httpx.get(
        url,
        params={"status": status, "limit": limit},
        headers=_api_key_headers(),
        timeout=timeout_s,
    )
    response.raise_for_status()
    payload = response.json()
    return payload if isinstance(payload, dict) else {"warnings": []}


def acknowledge_warning(
    warning_id: str,
    *,
    status: str = "received",
    detail: Optional[Dict[str, Any]] = None,
    timeout_s: int = 15,
) -> Dict[str, Any]:
    return _signed_post(
        f"/v1/federation/warnings/{warning_id}/ack",
        {
            "status": status,
            "detail": dict(detail or {}),
        },
        timeout_s=timeout_s,
    )

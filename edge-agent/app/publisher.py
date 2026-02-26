"""
Sentinel-KE Edge Agent — Hub Publisher
========================================

Hashes entity keys with a partner-specific HMAC salt, filters to entities
above the risk threshold, and POSTs a PatternBatch to the national hub.

Privacy guarantee
-----------------
Raw entity keys (phone numbers, account IDs, IP addresses) NEVER leave
the partner's perimeter.  Only HMAC-SHA256(entity_key, hmac_salt) is
transmitted, so the hub can detect "same hashed entity flagged by two
different banks" without learning what the actual entity is.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

from app.config import settings
from app.gnn_runner import GNNResult

logger = logging.getLogger(__name__)


def _hash_entity_key(raw_key: str) -> str:
    """HMAC-SHA256(entity_key, partner_salt) — irreversible, hub-safe."""
    return hmac.new(
        settings.hmac_salt.encode(),
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

    url = f"{settings.hub_url.rstrip('/')}/v1/federation/patterns"
    headers = {
        "X-API-Key":    settings.hub_api_key,
        "Content-Type": "application/json",
    }

    logger.info("Publishing %d high-risk entities to hub (%s)…", high_count, url)

    response = httpx.post(url, json=payload, headers=headers, timeout=timeout_s)
    response.raise_for_status()

    resp_json = response.json()
    logger.info("Hub accepted %d patterns for partner '%s'", resp_json.get("accepted", 0), settings.partner_id)
    return resp_json

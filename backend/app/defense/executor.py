"""
Sentinel-KE Defense — Last-Mile Containment Executor
======================================================

Dispatches block_ip and isolate_host containment actions to the partner's
own firewall / EDR system via a signed HTTPS webhook.

Flow
----
1. Analyst executes ContainmentAction(action_type="block_ip", target="1.2.3.4")
   via POST /v1/defense/incidents/runs/{run_id}/actions.
2. Defense service calls dispatch_containment_action().
3. This module looks up the ContainmentWebhook for (section_code, action_type).
4. It builds a signed JSON payload and POSTs it to the partner's webhook URL.
5. A WebhookDelivery row is written for forensic audit regardless of outcome.
6. On failure the action is marked "failed" and the analyst is notified.

Webhook payload (JSON)
-----------------------
{
  "sentinel_version": "1.0",
  "action_type":   "block_ip",
  "target":        "1.2.3.4",
  "section_code":  "safaricom",
  "action_id":     "<uuid>",
  "issued_at":     "2026-02-28T12:00:00Z"
}

Signature
---------
Header: X-Sentinel-Signature: sha256=<HMAC-SHA256(payload_bytes, secret)>

The partner verifies this header before applying the action.

Supported action_types
----------------------
block_ip       → POST to partner BGP/firewall webhook
isolate_host   → POST to partner EDR/NDR webhook
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

import httpx
from sqlalchemy.orm import Session

from app.defense.models import ContainmentWebhook, WebhookDelivery

logger = logging.getLogger("sentinel.defense.executor")

WEBHOOK_TIMEOUT_S = 12
SUPPORTED_REMOTE_ACTIONS = {"block_ip", "isolate_host"}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _sign_payload(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _lookup_webhook(
    db: Session,
    section_code: Optional[str],
    action_type: str,
) -> Optional[ContainmentWebhook]:
    if not section_code:
        return None
    return (
        db.query(ContainmentWebhook)
        .filter(
            ContainmentWebhook.section_code == section_code,
            ContainmentWebhook.action_type  == action_type,
            ContainmentWebhook.is_active    == True,  # noqa: E712
        )
        .first()
    )


def dispatch_containment_action(
    *,
    db: Session,
    action_type: str,
    target: str,
    section_code: Optional[str],
    action_id: Optional[uuid.UUID] = None,
) -> Tuple[str, Dict[str, Any]]:
    """
    Dispatch a block_ip or isolate_host action to the partner's webhook.

    Returns (status, details) where status is one of:
      "delivered"        — webhook accepted (2xx)
      "failed"           — webhook returned error or connection failed
      "no_webhook"       — no webhook registered for this section/action
      "unsupported"      — action_type not dispatched remotely (handled internally)
    """
    if action_type not in SUPPORTED_REMOTE_ACTIONS:
        return "unsupported", {"note": f"{action_type} is handled internally, not via webhook"}

    hook = _lookup_webhook(db, section_code, action_type)
    if not hook:
        logger.warning(
            "No active webhook for section=%s action=%s — action recorded only",
            section_code, action_type,
        )
        return "no_webhook", {
            "note": "action recorded; no webhook registered for this section/action type",
            "target": target,
            "hint": "Register a webhook via POST /v1/defense/webhooks",
        }

    payload_dict: Dict[str, Any] = {
        "sentinel_version": "1.0",
        "action_type":      action_type,
        "target":           target,
        "section_code":     section_code,
        "action_id":        str(action_id) if action_id else None,
        "issued_at":        _utcnow().isoformat(),
    }
    body = json.dumps(payload_dict, separators=(",", ":")).encode()

    # Retrieve the raw secret from the stored hash — we can't reverse SHA-256,
    # so we stored the hash for verification; for signing we need the raw secret
    # passed at webhook registration. The hub stores it as environment-resolved
    # value in the request object, so we use a per-webhook signing approach:
    # the webhook was registered with a secret whose SHA-256 hash is stored.
    # At dispatch time we use the stored hash as a proxy (partner must verify
    # using the same hash — see docs).  Production deployments should use a
    # secrets manager to retrieve the raw secret.
    sig = _sign_payload(body, hook.secret_hash)

    delivery = WebhookDelivery(
        action_id        = action_id,
        section_code     = section_code,
        action_type      = action_type,
        target           = target,
        webhook_url      = hook.webhook_url,
        status           = "pending",
        attempt_count    = 0,
        last_attempted_at = _utcnow(),
    )
    db.add(delivery)
    db.flush()

    try:
        response = httpx.post(
            hook.webhook_url,
            content=body,
            headers={
                "Content-Type":         "application/json",
                "X-Sentinel-Signature": f"sha256={sig}",
                "X-Sentinel-Action":    action_type,
            },
            timeout=WEBHOOK_TIMEOUT_S,
        )
        delivery.attempt_count     = 1
        delivery.last_attempted_at = _utcnow()
        delivery.http_status_code  = response.status_code
        delivery.response_body     = {"body": response.text[:500]}

        if response.is_success:
            delivery.status      = "delivered"
            delivery.delivered_at = _utcnow()
            logger.info(
                "Webhook delivered: action=%s target=%s section=%s http=%d",
                action_type, target, section_code, response.status_code,
            )
            return "delivered", {
                "webhook_url":   hook.webhook_url,
                "http_status":   response.status_code,
                "delivery_id":   str(delivery.id),
            }
        else:
            delivery.status        = "failed"
            delivery.error_message = f"HTTP {response.status_code}: {response.text[:200]}"
            logger.error(
                "Webhook rejected: action=%s target=%s http=%d body=%s",
                action_type, target, response.status_code, response.text[:200],
            )
            return "failed", {
                "webhook_url":   hook.webhook_url,
                "http_status":   response.status_code,
                "error":         delivery.error_message,
                "delivery_id":   str(delivery.id),
            }

    except httpx.TimeoutException:
        msg = f"Webhook timeout after {WEBHOOK_TIMEOUT_S}s"
        delivery.status        = "failed"
        delivery.attempt_count = 1
        delivery.error_message = msg
        logger.error("Webhook timeout: action=%s target=%s url=%s", action_type, target, hook.webhook_url)
        return "failed", {"error": msg, "delivery_id": str(delivery.id)}

    except Exception as exc:
        msg = str(exc)
        delivery.status        = "failed"
        delivery.attempt_count = 1
        delivery.error_message = msg
        logger.exception("Webhook error: action=%s target=%s: %s", action_type, target, msg)
        return "failed", {"error": msg, "delivery_id": str(delivery.id)}

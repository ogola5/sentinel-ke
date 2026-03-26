"""
Sentinel-KE Defense — Last-Mile Containment Executor
======================================================

Dispatches containment actions to partner controls via a signed HTTPS webhook.

Flow
----
1. Analyst executes ContainmentAction(action_type="block_ip", target="1.2.3.4")
   via POST /v1/defense/incidents/runs/{run_id}/actions.
2. Defense service calls dispatch_containment_action().
3. This module looks up the ContainmentWebhook for (section_code, action_type).
4. It builds a signed JSON payload and POSTs it to the partner's webhook URL.
5. A WebhookDelivery row is written for forensic audit regardless of outcome.
6. If no webhook is registered, the dispatcher records a `no_integration`
   delivery receipt instead of pretending the action was delivered.
7. On failure the action is marked "failed" and the analyst is notified.

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
block_ip             → POST to partner BGP/firewall webhook
unblock_ip           → rollback for a prior block_ip action
isolate_host         → POST to partner EDR/NDR webhook
rate_limit_service   → ask the partner edge/WAF to throttle abusive traffic while keeping service up
enable_waf_challenge → ask the partner WAF/CDN to challenge suspicious traffic while keeping service up
reroute_to_scrubber  → ask the partner or provider to move traffic into DDoS scrubbing
quarantine_email     → ask the partner mail stack to quarantine a malicious sender or mailbox
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

import httpx
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.orm import Session

from app.defense.actions import webhook_action_keys
from app.defense.models import ContainmentWebhook, WebhookDelivery

logger = logging.getLogger("sentinel.defense.executor")

WEBHOOK_TIMEOUT_S = 12
SUPPORTED_REMOTE_ACTIONS = webhook_action_keys() | {"unblock_ip"}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _fernet() -> Fernet:
    """Return a Fernet instance keyed from WEBHOOK_SECRET_ENCRYPTION_KEY (or a dev fallback)."""
    from app.core.config import settings  # noqa: PLC0415
    raw = settings.webhook_secret_encryption_key
    if not raw:
        # Dev fallback: deterministic 32-byte key derived from a fixed string.
        # Set WEBHOOK_SECRET_ENCRYPTION_KEY in production.
        _raw = hashlib.sha256(b"sentinel-ke-dev-webhook-encryption").digest()
        raw = base64.urlsafe_b64encode(_raw).decode()
    return Fernet(raw.encode() if isinstance(raw, str) else raw)


def encrypt_webhook_secret(raw_secret: str) -> str:
    """Fernet-encrypt a raw webhook signing secret for storage."""
    return _fernet().encrypt(raw_secret.encode()).decode()


def _decrypt_secret(ciphertext: str) -> str:
    """Decrypt a stored Fernet ciphertext back to the raw signing secret."""
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except (InvalidToken, Exception) as exc:
        raise RuntimeError(f"failed to decrypt webhook secret: {exc}") from exc


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
    Dispatch a containment action to the partner's webhook.

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
        delivery = WebhookDelivery(
            action_id=action_id,
            section_code=section_code,
            action_type=action_type,
            target=target,
            webhook_url="",
            status="no_integration",
            attempt_count=0,
            last_attempted_at=_utcnow(),
            error_message="no webhook registered for this section/action type",
            response_body={
                "note": "action recorded; no webhook registered for this section/action type",
                "target": target,
                "hint": "Register a webhook via POST /v1/defense/webhooks",
            },
        )
        db.add(delivery)
        db.flush()
        return "no_webhook", {
            "note": "action recorded; no webhook registered for this section/action type",
            "target": target,
            "hint": "Register a webhook via POST /v1/defense/webhooks",
            "delivery_id": str(delivery.id),
            "delivery_status": "no_integration",
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

    if not hook.secret_enc:
        logger.error(
            "Webhook %s has no encrypted secret; re-register via POST /v1/defense/webhooks",
            hook.id,
        )
        return "failed", {
            "error": "webhook secret not configured; re-register the webhook",
            "hint":  "POST /v1/defense/webhooks with section_code, action_type, webhook_url, secret",
        }
    sig = _sign_payload(body, _decrypt_secret(hook.secret_enc))

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

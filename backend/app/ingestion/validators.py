from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

from pydantic import ValidationError

from app.ingestion.schemas import (
    CanonicalEvent,
    SimSwapPayload,
    LoginPayload,
    TransactionPayload,
    DomainRegPayload,
    PhishingMessagePayload,
    DdosSignalPayload,
    ServiceHealthPayload,
    DnsResolutionPayload,
)

REQUIRED_ANCHOR_GROUP = (
    "phone_h",
    "account_h",
    "person_h",
    "ip",
    "domain",
    "device_id",
    "service_id",
)


def _require_anchor(event: CanonicalEvent) -> None:
    if not event.anchors:
        raise ValueError("anchors required: event must include at least one anchor")
    if not any(k in event.anchors for k in REQUIRED_ANCHOR_GROUP):
        raise ValueError(
            "anchors required: must include at least one of "
            + ", ".join(REQUIRED_ANCHOR_GROUP)
        )


def _time_sanity(event: CanonicalEvent) -> None:
    if event.occurred_at.tzinfo is None:
        raise ValueError("occurred_at must be timezone-aware (include Z or offset)")
    now = datetime.now(timezone.utc)
    if event.occurred_at.astimezone(timezone.utc) > now:
        raise ValueError("occurred_at cannot be in the future")


def _validate_typed_payload(event: CanonicalEvent) -> None:
    # Strict minimal validation: ensure payload matches expected shape for event_type.
    # We do NOT enrich/have side effects here.
    try:
        if event.event_type == "SIM_SWAP_EVENT":
            SimSwapPayload.model_validate(event.payload)
        elif event.event_type == "LOGIN_EVENT":
            LoginPayload.model_validate(event.payload)
        elif event.event_type == "TRANSACTION_EVENT":
            TransactionPayload.model_validate(event.payload)
        elif event.event_type == "DOMAIN_REG_EVENT":
            DomainRegPayload.model_validate(event.payload)
        elif event.event_type == "PHISHING_MESSAGE_EVENT":
            PhishingMessagePayload.model_validate(event.payload)
        elif event.event_type == "DDOS_SIGNAL_EVENT":
            DdosSignalPayload.model_validate(event.payload)
        elif event.event_type == "SERVICE_HEALTH_EVENT":
            ServiceHealthPayload.model_validate(event.payload)
        elif event.event_type == "DNS_RESOLUTION_EVENT":
            DnsResolutionPayload.model_validate(event.payload)
        else:
            raise ValueError(f"unsupported event_type: {event.event_type}")
    except ValidationError as e:
        raise ValueError(f"payload validation failed for {event.event_type}: {e}") from e


def validate_event(event: CanonicalEvent) -> None:
    """
    Pure validation:
    - time sanity
    - anchor presence
    - payload conforms to event_type
    """
    _time_sanity(event)
    _require_anchor(event)
    _validate_typed_payload(event)

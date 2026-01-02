from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, model_validator


EventType = Literal[
    "SIM_SWAP_EVENT",
    "LOGIN_EVENT",
    "TRANSACTION_EVENT",
    "DOMAIN_REG_EVENT",
    "PHISHING_MESSAGE_EVENT",
    "DDOS_SIGNAL_EVENT",
    "SERVICE_HEALTH_EVENT",
    "DNS_RESOLUTION_EVENT",
]

Classification = Literal["PUBLIC", "RESTRICTED", "INTERNAL"]


# ---- Typed payloads (minimal, MVP-safe) ----

class SimSwapPayload(BaseModel):
    phone: str
    prev_sim_id: Optional[str] = None
    new_sim_id: Optional[str] = None
    reason: Optional[str] = None


class LoginPayload(BaseModel):
    username: Optional[str] = None
    outcome: Literal["success", "failure", "unknown"] = "unknown"
    user_agent: Optional[str] = None
    device_id: Optional[str] = None
    ip: Optional[str] = None
    # optional infra metadata for VPN correlation
    asn: Optional[int] = None
    provider: Optional[str] = None
    request_fingerprint: Optional[str] = None


class TransactionPayload(BaseModel):
    account_from: Optional[str] = None
    account_to: Optional[str] = None
    # hashed variants (optional, used after pseudonymization)
    account_h_from: Optional[str] = None
    account_h_to: Optional[str] = None
    amount: Optional[float] = None
    currency: Optional[str] = None
    channel: Optional[str] = None
    ip: Optional[str] = None
    device_id: Optional[str] = None
    agent_id: Optional[str] = None
    agent_location: Optional[str] = None
    withdrawal_type: Optional[str] = None


class DomainRegPayload(BaseModel):
    domain: str
    registrar: Optional[str] = None
    registrant_org: Optional[str] = None
    nameserver: Optional[str] = None


class PhishingMessagePayload(BaseModel):
    message_id: Optional[str] = None
    channel: Optional[str] = None  # sms/email/whatsapp/etc
    sender: Optional[str] = None
    url: Optional[str] = None
    domain: Optional[str] = None
    phone: Optional[str] = None


class DdosSignalPayload(BaseModel):
    service_id: str
    endpoint: Optional[str] = None
    method: Optional[str] = None
    req_rate: Optional[float] = None
    error_rate: Optional[float] = None
    unique_ips_count: Optional[int] = None
    avg_latency_ms: Optional[float] = None
    user_agent_entropy: Optional[float] = None
    asn_concentration: Optional[float] = None
    endpoint_convergence: Optional[float] = None


class ServiceHealthPayload(BaseModel):
    service_id: str
    status: Literal["up", "down", "degraded"]
    latency_ms: Optional[float] = None
    error_rate: Optional[float] = None


class DnsResolutionPayload(BaseModel):
    domain: str
    ip: str
    ttl: Optional[int] = None


# ---- Canonical envelope ----

ALLOWED_ANCHOR_KEYS = {
    "ip",
    "domain",
    "phone_h",
    "account_h",
    "person_h",
    "device_id",
    "service_id",
    "url",
    "endpoint",
    "agent_id",
}

class CanonicalEvent(BaseModel):
    # envelope
    event_type: EventType
    occurred_at: datetime
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)

    # payload: typed later via normalizer/validator
    payload: Dict[str, Any] = Field(default_factory=dict)

    # anchors: extracted entity anchors
    anchors: Dict[str, str] = Field(default_factory=dict)

    # classification: can be overridden per event later; default comes from source_registry
    classification: Optional[Classification] = None

    schema_version: str = "v1"

    @model_validator(mode="after")
    def _basic_checks(self) -> "CanonicalEvent":
        # anchor keys must be known (presence enforced in validators)
        bad = set(self.anchors.keys()) - ALLOWED_ANCHOR_KEYS
        if bad:
            raise ValueError(f"Invalid anchor keys: {sorted(bad)}")
        return self

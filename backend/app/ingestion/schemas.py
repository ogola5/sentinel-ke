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
    "DB_AUDIT_EVENT",
    "FILE_INTEGRITY_EVENT",
    "DFIR_FINDING_EVENT",
    "WEB_ATTACK_EVENT",
    "VULNERABILITY_EVENT",
    "BACKUP_ATTESTATION_EVENT",
    "INCIDENT_RESPONSE_EVENT",
    "AIRTIME_TRANSFER_EVENT",   # Telco airtime siphoning (Safaricom/Airtel/Telkom)
    "BILLING_FRAUD_EVENT",      # Roaming / cross-carrier billing manipulation
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


class DbAuditPayload(BaseModel):
    source: str = "pgaudit"
    db_instance: str
    db_name: Optional[str] = None
    db_user: Optional[str] = None
    statement_type: str
    object_name: Optional[str] = None
    operation: Optional[str] = None
    row_count: Optional[int] = None
    success: bool = True
    session_id: Optional[str] = None
    query_fingerprint: Optional[str] = None
    client_ip: Optional[str] = None
    reason_codes: List[str] = Field(default_factory=list)


class FileIntegrityPayload(BaseModel):
    source: str = "wazuh"
    host: str
    agent_id: Optional[str] = None
    file_path: str
    action: str
    hash_before: Optional[str] = None
    hash_after: Optional[str] = None
    user: Optional[str] = None
    process: Optional[str] = None
    severity: Optional[str] = None
    rule_id: Optional[str] = None
    client_ip: Optional[str] = None
    is_critical_path: bool = False
    reason_codes: List[str] = Field(default_factory=list)


class DfirFindingPayload(BaseModel):
    source: str = "velociraptor"
    host: str
    artifact_name: str
    finding_type: str
    severity: str = "medium"
    status: Optional[str] = None
    user: Optional[str] = None
    process_name: Optional[str] = None
    process_pid: Optional[int] = None
    file_path: Optional[str] = None
    sha256: Optional[str] = None
    command_line: Optional[str] = None
    client_ip: Optional[str] = None
    case_id: Optional[str] = None
    hunt_id: Optional[str] = None
    reason_codes: List[str] = Field(default_factory=list)


class WebAttackPayload(BaseModel):
    source: str = "waf"
    service_id: str
    endpoint: Optional[str] = None
    method: Optional[str] = None
    attack_type: str
    status: Literal["blocked", "detected", "allowed"] = "detected"
    req_count: Optional[int] = None
    src_ip: Optional[str] = None
    user_agent: Optional[str] = None
    reason_codes: List[str] = Field(default_factory=list)


class VulnerabilityPayload(BaseModel):
    source: str = "kev"
    asset_id: str
    cve_id: str
    severity: str = "medium"
    kev: bool = False
    epss: Optional[float] = None
    patch_due_date: Optional[str] = None
    status: Optional[str] = None
    reason_codes: List[str] = Field(default_factory=list)


class BackupAttestationPayload(BaseModel):
    source: str = "backup_system"
    asset_id: str
    backup_id: str
    immutable: bool = False
    object_lock_until: Optional[str] = None
    backup_hash: Optional[str] = None
    storage_tier: Optional[str] = None
    status: Optional[str] = None
    rpo_hours: Optional[float] = None


class AirtimeTransferPayload(BaseModel):
    source: str = "telco_billing"
    provider: str                          # safaricom | airtel | telkom
    phone_h: Optional[str] = None         # hashed MSISDN of victim
    amount_ksh: Optional[float] = None
    recipient_account_h: Optional[str] = None
    channel: Optional[str] = None         # ussd | api | stk
    transfer_ref: Optional[str] = None
    reason_codes: List[str] = Field(default_factory=list)


class BillingFraudPayload(BaseModel):
    source: str = "telco_billing"
    provider: str                          # safaricom | airtel | telkom
    fraud_type: str                        # roaming_inflate | cross_carrier | vas_abuse
    affected_account_h: Optional[str] = None
    amount_ksh: Optional[float] = None
    roaming_country: Optional[str] = None
    billing_cycle: Optional[str] = None
    reason_codes: List[str] = Field(default_factory=list)


class IncidentResponsePayload(BaseModel):
    source: str = "ir_orchestrator"
    incident_key: str
    action_type: str
    target: str
    status: str
    actor: Optional[str] = None
    reason: Optional[str] = None


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

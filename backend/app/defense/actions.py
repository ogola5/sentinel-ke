from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import List


@dataclass(frozen=True)
class DefenseActionDefinition:
    key: str
    label: str
    description: str
    delivery_mode: str  # webhook | internal | internal_dispatch
    continuity_preserving: bool
    target_hint: str
    category: str  # network | service | identity | email | host


_ACTION_CATALOG: tuple[DefenseActionDefinition, ...] = (
    DefenseActionDefinition(
        key="block_ip",
        label="Block source IP",
        description="Drop or deny traffic from a confirmed hostile public IP.",
        delivery_mode="webhook",
        continuity_preserving=False,
        target_hint="Public source IP",
        category="network",
    ),
    DefenseActionDefinition(
        key="rollback_block_ip",
        label="Rollback IP block",
        description="Reverse the latest active IP block within the rollback window.",
        delivery_mode="internal_dispatch",
        continuity_preserving=True,
        target_hint="Previously blocked IP",
        category="network",
    ),
    DefenseActionDefinition(
        key="isolate_host",
        label="Isolate host",
        description="Contain a compromised workstation or server through EDR/NDR isolation.",
        delivery_mode="webhook",
        continuity_preserving=False,
        target_hint="Host, endpoint, or device identifier",
        category="host",
    ),
    DefenseActionDefinition(
        key="rate_limit_service",
        label="Rate-limit service",
        description="Throttle abusive traffic while keeping the protected service reachable.",
        delivery_mode="webhook",
        continuity_preserving=True,
        target_hint="Service or endpoint identifier",
        category="service",
    ),
    DefenseActionDefinition(
        key="enable_waf_challenge",
        label="Enable WAF challenge",
        description="Require challenge or bot mitigation at the edge while keeping service available.",
        delivery_mode="webhook",
        continuity_preserving=True,
        target_hint="Service, URL, or domain",
        category="service",
    ),
    DefenseActionDefinition(
        key="reroute_to_scrubber",
        label="Reroute to scrubber",
        description="Move traffic into upstream DDoS scrubbing or protective transit.",
        delivery_mode="webhook",
        continuity_preserving=True,
        target_hint="Service or edge zone identifier",
        category="service",
    ),
    DefenseActionDefinition(
        key="quarantine_email",
        label="Quarantine email",
        description="Quarantine a malicious sender, message, or mailbox path.",
        delivery_mode="webhook",
        continuity_preserving=True,
        target_hint="Mailbox, sender, or message target",
        category="email",
    ),
    DefenseActionDefinition(
        key="disable_source_key",
        label="Disable source key",
        description="Disable a compromised source registry API key or ingest source.",
        delivery_mode="internal",
        continuity_preserving=True,
        target_hint="Source registry ID",
        category="identity",
    ),
    DefenseActionDefinition(
        key="revoke_user",
        label="Revoke user sessions",
        description="Invalidate all active sessions for a compromised user account.",
        delivery_mode="internal",
        continuity_preserving=True,
        target_hint="Username",
        category="identity",
    ),
    DefenseActionDefinition(
        key="force_password_reset",
        label="Force password reset",
        description="Reset a user password and revoke active sessions.",
        delivery_mode="internal",
        continuity_preserving=True,
        target_hint="Username",
        category="identity",
    ),
)


def action_catalog() -> List[dict]:
    return [asdict(item) for item in _ACTION_CATALOG]


def supported_action_keys() -> set[str]:
    return {item.key for item in _ACTION_CATALOG}


def webhook_action_keys() -> set[str]:
    return {item.key for item in _ACTION_CATALOG if item.delivery_mode == "webhook"} | {"unblock_ip"}


def action_definition(key: str) -> DefenseActionDefinition | None:
    normalized = key.strip().lower()
    for item in _ACTION_CATALOG:
        if item.key == normalized:
            return item
    return None

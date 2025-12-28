# app/campaign/rules.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

SUPPORTED_PRIMARY_KEYS = ("ip", "device_id", "endpoint", "service_id", "domain", "url", "provider_id")

ENTITY_MAP = {
    "ip": ("IP", "ip"),
    "device_id": ("Device", "device_id"),
    "endpoint": ("Endpoint", "endpoint"),
    "service_id": ("Service", "service_id"),
    "domain": ("Domain", "domain"),
    "url": ("URL", "url"),
    "provider_id": ("Provider", "provider_id"),
    "person_h": ("Person", "person_h"),
    "account_h": ("Account", "account_h"),
    "phone_h": ("Phone", "phone_h"),
}

@dataclass(frozen=True)
class CampaignRuleDecision:
    # Which campaign "channels" this event should contribute to
    # Each primary indicator becomes a separate campaign stream.
    primary_keys: List[str]  # e.g. ["ip:8.8.8.8", "endpoint:/api/login"]


def derive_primary_keys(anchors: Dict) -> CampaignRuleDecision:
    out: List[str] = []
    for k in SUPPORTED_PRIMARY_KEYS:
        v = anchors.get(k)
        if not v:
            continue
        s = str(v).strip()
        if not s:
            continue
        out.append(f"{k}:{s}")
    return CampaignRuleDecision(primary_keys=out)


def extract_entities_for_stats(anchors: Dict) -> List[Tuple[str, str]]:
    """
    returns list of (entity_type, entity_key)
    entity_key uses the same "k:value" format for uniqueness.
    """
    entities: List[Tuple[str, str]] = []
    for k, (etype, _) in ENTITY_MAP.items():
        v = anchors.get(k)
        if not v:
            continue
        s = str(v).strip()
        if not s:
            continue
        entities.append((etype, f"{k}:{s}"))
    return entities


def compute_score(*, event_count: int, distinct_persons: int, distinct_devices: int) -> float:
    """
    Deterministic scoring (Option A).
    You can tune this later. Keep in [0, 1].
    """
    # base signal: more events + more distinct persons is more suspicious
    p = min(1.0, distinct_persons / 5.0)
    d = min(1.0, distinct_devices / 5.0)
    e = min(1.0, event_count / 30.0)
    return max(p, (0.5 * p + 0.3 * d + 0.2 * e))

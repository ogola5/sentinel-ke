# app/campaign/detectors.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from datetime import datetime


@dataclass(frozen=True)
class Signal:
    """
    A single campaign candidate derived deterministically from one event.
    """
    type: str          # e.g. "VPN_IP_REUSE"
    primary_key: str   # e.g. "ip:8.8.8.8"
    entities: List[Tuple[str, str]]  # (entity_type, entity_key)
    stats_patch: Dict[str, int]      # counters to merge into Campaign.stats


def _anchor(event_doc: dict, k: str) -> Optional[str]:
    v = (event_doc.get("anchors") or {}).get(k)
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _payload(event_doc: dict, k: str) -> Optional[str]:
    v = (event_doc.get("payload") or {}).get(k)
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def build_signals_from_event(*, event_hash: str, event_doc: dict) -> List[Signal]:
    """
    Deterministic signals from the canonical event document.
    O(1) per event.

    event_doc is the inner 'event' object from sentinel.events.v1 message.
    """
    et = (event_doc.get("event_type") or "").upper()
    anchors = event_doc.get("anchors") or {}

    ip = _anchor(event_doc, "ip") or _payload(event_doc, "ip")
    person_h = _anchor(event_doc, "person_h")
    device_id = _anchor(event_doc, "device_id")
    endpoint = _anchor(event_doc, "endpoint") or _payload(event_doc, "endpoint")
    provider_id = _anchor(event_doc, "provider_id")  # optional for later

    out: List[Signal] = []

    # --- VPN-like: IP reused across identities/devices ---
    if ip:
        entities: List[Tuple[str, str]] = [("IP", f"ip:{ip}")]
        if person_h:
            entities.append(("Person", f"person_h:{person_h}"))
        if device_id:
            entities.append(("Device", f"device_id:{device_id}"))

        out.append(
            Signal(
                type="VPN_IP_REUSE",
                primary_key=f"ip:{ip}",
                entities=entities,
                stats_patch={"events": 1},
            )
        )

    # --- Device reuse across persons ---
    if device_id:
        entities: List[Tuple[str, str]] = [("Device", f"device_id:{device_id}")]
        if person_h:
            entities.append(("Person", f"person_h:{person_h}"))
        if ip:
            entities.append(("IP", f"ip:{ip}"))

        out.append(
            Signal(
                type="DEVICE_REUSE",
                primary_key=f"device_id:{device_id}",
                entities=entities,
                stats_patch={"events": 1},
            )
        )

    # --- DDoS: many IPs to same endpoint ---
    if endpoint:
        entities: List[Tuple[str, str]] = [("Endpoint", f"endpoint:{endpoint}")]
        if ip:
            entities.append(("IP", f"ip:{ip}"))
        out.append(
            Signal(
                type="DDOS_ENDPOINT_FANIN",
                primary_key=f"endpoint:{endpoint}",
                entities=entities,
                stats_patch={"events": 1},
            )
        )

    # --- Infra reuse (optional now) ---
    if provider_id:
        entities: List[Tuple[str, str]] = [("Provider", f"provider_id:{provider_id}")]
        if ip:
            entities.append(("IP", f"ip:{ip}"))
        out.append(
            Signal(
                type="INFRA_PROVIDER_REUSE",
                primary_key=f"provider_id:{provider_id}",
                entities=entities,
                stats_patch={"events": 1},
            )
        )

    return out


#     return out


# app/campaign/detectors.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple


# -----------------------------
# Signal contract (ENGINE SAFE)
# -----------------------------
@dataclass(frozen=True)
class Signal:
    """
    A single campaign candidate derived deterministically from one event.
    """
    type: str
    primary_key: str
    entities: List[Tuple[str, str, str]]  # (entity_type, entity_key, role)
    stats_patch: Dict[str, int]


# -----------------------------
# Helpers
# -----------------------------
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


# -----------------------------
# Main detector
# -----------------------------
def build_signals_from_event(*, event_hash: str, event_doc: dict) -> List[Signal]:
    """
    Deterministic, O(1) signal extraction per event.
    MUST return entities as (type, key, role).
    """
    et = (event_doc.get("event_type") or "").upper()

    ip = _anchor(event_doc, "ip") or _payload(event_doc, "ip")
    domain = _anchor(event_doc, "domain") or _payload(event_doc, "domain")
    url = _anchor(event_doc, "url") or _payload(event_doc, "url")
    endpoint = _anchor(event_doc, "endpoint") or _payload(event_doc, "endpoint")
    service_id = _anchor(event_doc, "service_id") or _payload(event_doc, "service_id")
    person_h = _anchor(event_doc, "person_h")
    device_id = _anchor(event_doc, "device_id")
    finding_type = (_payload(event_doc, "finding_type") or "").strip().lower()

    out: List[Signal] = []

    # -----------------------------
    # DDoS: many IPs → same endpoint
    # -----------------------------
    if et == "DDOS_SIGNAL_EVENT" and endpoint:
        entities: List[Tuple[str, str, str]] = []

        if ip:
            entities.append(("IP", f"ip:{ip}", "attacker"))

        entities.append(("Endpoint", f"endpoint:{endpoint}", "target"))

        if service_id:
            entities.append(("Service", f"service_id:{service_id}", "target"))

        out.append(
            Signal(
                type="DDOS_ENDPOINT_FANIN",
                primary_key=f"endpoint:{endpoint}",
                entities=entities,
                stats_patch={"events": 1},
            )
        )

    # -----------------------------
    # VPN-like IP reuse
    # -----------------------------
    if ip:
        entities: List[Tuple[str, str, str]] = [("IP", f"ip:{ip}", "unknown")]

        if person_h:
            entities.append(("Person", f"person_h:{person_h}", "user"))
        if device_id:
            entities.append(("Device", f"device_id:{device_id}", "device"))

        out.append(
            Signal(
                type="VPN_IP_REUSE",
                primary_key=f"ip:{ip}",
                entities=entities,
                stats_patch={"events": 1},
            )
        )

    # -----------------------------
    # IOC / malware indicator clustering
    # -----------------------------
    if et == "DFIR_FINDING_EVENT" and (
        "indicator" in finding_type
        or finding_type in {"malware_url", "botnet_c2_indicator"}
    ):
        entities: List[Tuple[str, str, str]] = []
        primary_key: Optional[str] = None

        if ip:
            entities.append(("IP", f"ip:{ip}", "indicator"))
            primary_key = primary_key or f"ip:{ip}"
        if domain:
            entities.append(("Domain", f"domain:{domain}", "indicator"))
            primary_key = primary_key or f"domain:{domain}"
        if url:
            entities.append(("URL", f"url:{url}", "indicator"))
            primary_key = primary_key or f"url:{url}"
        if service_id:
            entities.append(("Service", f"service_id:{service_id}", "target"))
        if endpoint:
            entities.append(("Endpoint", f"endpoint:{endpoint}", "target"))

        if primary_key and entities:
            out.append(
                Signal(
                    type="IOC_INDICATOR_CLUSTER",
                    primary_key=primary_key,
                    entities=entities,
                    stats_patch={"events": 1},
                )
            )

    return out

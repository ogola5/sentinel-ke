# backend/app/stix/mapper.py
from __future__ import annotations

from typing import Dict, Optional, Tuple

from app.stix.ids import stix_id


def parse_entity_key(entity_key: str) -> Tuple[str, str]:
    """
    entity_key is stored like "ip:8.8.8.8" or "endpoint:/api/login"
    """
    if ":" not in entity_key:
        return entity_key, ""
    k, v = entity_key.split(":", 1)
    return k.strip(), v.strip()


def to_stix_object(entity_key: str) -> Optional[Dict]:
    """
    Returns a STIX object (SCO or custom object), or None if unsupported.
    """
    k, v = parse_entity_key(entity_key)
    if not v:
        return None

    if k == "ip":
        return {
            "type": "ipv4-addr",
            "spec_version": "2.1",
            "id": stix_id("ipv4-addr", f"ip:{v}"),
            "value": v,
        }

    if k == "domain":
        return {
            "type": "domain-name",
            "spec_version": "2.1",
            "id": stix_id("domain-name", f"domain:{v}"),
            "value": v,
        }

    if k == "url":
        return {
            "type": "url",
            "spec_version": "2.1",
            "id": stix_id("url", f"url:{v}"),
            "value": v,
        }

    # Custom objects for app-specific anchors
    if k == "endpoint":
        return {
            "type": "x-sentinel-endpoint",
            "spec_version": "2.1",
            "id": stix_id("x-sentinel-endpoint", f"endpoint:{v}"),
            "name": v,
        }

    if k == "service_id":
        return {
            "type": "x-sentinel-service",
            "spec_version": "2.1",
            "id": stix_id("x-sentinel-service", f"service_id:{v}"),
            "name": v,
        }

    # You can extend with device_id/person_h etc using custom objects
    return None

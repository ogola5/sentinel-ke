from __future__ import annotations

from typing import Any, Dict, Tuple, Optional

from app.core.security import pseudonymize
from app.ingestion.anchors import extract_raw_anchor_candidates


def pseudonymize_payload_and_anchors(
    payload: Dict[str, Any],
    salt: Optional[str] = None,
) -> Tuple[Dict[str, Any], Dict[str, str]]:
    """
    Returns (payload_out, anchors_out).
    - payload_out: payload with sensitive fields replaced/removed (MVP strategy)
    - anchors_out: canonical anchors; sensitive identifiers converted to *_h
    """
    raw = extract_raw_anchor_candidates(payload)

    anchors: Dict[str, str] = {}

    # non-sensitive anchors pass through
    for k in ("ip", "domain", "service_id", "device_id", "endpoint", "url"):
        if k in raw:
            anchors[k] = raw[k]

    # sensitive anchors become hashed keys
    if "phone" in raw:
        anchors["phone_h"] = pseudonymize(raw["phone"], salt=salt)
        # optionally remove raw from payload
        payload.pop("phone", None)
        payload.pop("msisdn", None)

    if "account" in raw:
        anchors["account_h"] = pseudonymize(raw["account"], salt=salt)
        payload.pop("account", None)

    if "person" in raw:
        anchors["person_h"] = pseudonymize(raw["person"], salt=salt)
        payload.pop("person_id", None)
        payload.pop("national_id", None)

    return payload, anchors

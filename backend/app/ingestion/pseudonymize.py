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
    for k in ("ip", "domain", "service_id", "device_id", "endpoint", "url", "agent_id"):
        if k in raw:
            anchors[k] = raw[k]

    # sensitive anchors become hashed keys
    if "phone" in raw:
        anchors["phone_h"] = pseudonymize(raw["phone"], salt=salt)
        # optionally remove raw from payload
        payload.pop("phone", None)
        payload.pop("msisdn", None)

    account_from = payload.get("account_from")
    account_to = payload.get("account_to")
    if "account" in raw or account_from:
        account_h_from = payload.get("account_h_from") or pseudonymize(
            raw.get("account") or str(account_from), salt=salt
        )
        anchors["account_h"] = account_h_from
        payload["account_h_from"] = account_h_from
        payload.pop("account", None)
        payload.pop("account_from", None)
    if account_to:
        account_h_to = payload.get("account_h_to") or pseudonymize(str(account_to), salt=salt)
        payload["account_h_to"] = account_h_to
        payload.pop("account_to", None)

    if "person" in raw:
        anchors["person_h"] = pseudonymize(raw["person"], salt=salt)
        payload.pop("person_id", None)
        payload.pop("national_id", None)

    return payload, anchors

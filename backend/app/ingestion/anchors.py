from __future__ import annotations

from typing import Any, Dict

# canonical anchor keys we use across the system
ANCHOR_FIELDS = {
    "ip": ["ip", "src_ip", "dst_ip"],
    "domain": ["domain"],
    "service_id": ["service_id"],
    "device_id": ["device_id"],
    "endpoint": ["endpoint"],
    "url": ["url"],
    # phone/account/person are sensitive; we extract raw here, hash later
    "phone": ["phone", "msisdn"],
    "account": ["account", "account_from", "account_to"],
    "person": ["person_id", "national_id"],
}


def extract_raw_anchor_candidates(payload: Dict[str, Any]) -> Dict[str, str]:
    """
    Returns raw candidates, not yet pseudonymized.
    Keys returned may include: ip, domain, service_id, device_id, endpoint, url,
    plus sensitive keys: phone, account, person.
    """
    out: Dict[str, str] = {}

    for canon_key, aliases in ANCHOR_FIELDS.items():
        for a in aliases:
            v = payload.get(a)
            if v is None:
                continue
            if isinstance(v, (str, int, float)):
                s = str(v).strip()
                if s:
                    out[canon_key] = s
                    break  # prefer first match

    return out

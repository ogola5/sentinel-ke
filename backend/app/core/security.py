from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any, Dict, Optional


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def hash_api_key(raw_key: str) -> str:
    # stored in source_registry
    return sha256_hex(raw_key.encode("utf-8"))


def verify_api_key(raw_key: str, stored_hash: str) -> bool:
    computed = hash_api_key(raw_key)
    return hmac.compare_digest(computed, stored_hash)


def stable_json_dumps(obj: Any) -> str:
    """
    Deterministic JSON canonicalization:
    - sort keys
    - no whitespace
    - ensure_ascii=False
    This is the basis for deterministic event_hash.
    """
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_event_hash(canonical_obj: Dict[str, Any]) -> str:
    """
    SHA256 over canonical JSON representation.
    """
    payload = stable_json_dumps(canonical_obj).encode("utf-8")
    return sha256_hex(payload)


def hmac_verify(secret: str, message: bytes, signature_hex: str) -> bool:
    """
    Placeholder for Phase 1.4/1.5:
    HMAC-SHA256 verification. We will wire it to headers later.
    """
    mac = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()
    return hmac.compare_digest(mac, signature_hex)


# ---- Pseudonymization ----
# We never store phone/account/person raw if we can avoid it.
# For MVP: deterministic salted hashing.
# Salt should come from env later; default is dangerous but acceptable for local demo.

DEFAULT_PSEUDO_SALT = "sentinel-ke-demo-salt"


def pseudonymize(value: str, salt: Optional[str] = None) -> str:
    salt = salt or DEFAULT_PSEUDO_SALT
    material = f"{salt}:{value}".encode("utf-8")
    return sha256_hex(material)

# backend/app/stix/ids.py
from __future__ import annotations

import uuid

# Fixed namespace for stable IDs across exports
_STIX_NS = uuid.UUID("2d5f1c6e-0b2c-4c2a-aaf1-6b5a0e1b6d2a")


def stix_id(stix_type: str, stable_key: str) -> str:
    """
    Deterministic STIX ID using UUIDv5.

    Example:
      stix_id("report", "campaign:<uuid>") -> "report--<uuidv5>"
    """
    u = uuid.uuid5(_STIX_NS, f"{stix_type}:{stable_key}")
    return f"{stix_type}--{u}"


def now_iso() -> str:
    # STIX wants RFC3339-ish timestamps; ISO with Z is fine.
    # We'll keep timezone-aware elsewhere; this helper is optional.
    import datetime as _dt
    return _dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

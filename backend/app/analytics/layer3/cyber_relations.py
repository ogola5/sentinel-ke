from __future__ import annotations

from typing import Dict, List, Sequence, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session


def _entity_prefix(entity_key: str) -> str:
    if ":" not in str(entity_key):
        return str(entity_key or "").strip().lower()
    return str(entity_key).split(":", 1)[0].strip().lower()


_RELATION_WEIGHTS: Dict[str, Dict[frozenset[str], float]] = {
    "LOGIN_EVENT": {
        frozenset({"account_h", "device_id"}): 3.0,
        frozenset({"account_h", "ip"}): 2.6,
        frozenset({"device_id", "ip"}): 2.2,
        frozenset({"account_h", "endpoint"}): 1.9,
        frozenset({"account_h", "provider_id"}): 1.8,
    },
    "SIM_SWAP_EVENT": {
        frozenset({"phone_h", "device_id"}): 3.4,
        frozenset({"phone_h", "account_h"}): 3.1,
        frozenset({"phone_h", "provider_id"}): 2.8,
        frozenset({"device_id", "account_h"}): 2.4,
    },
    "TRANSACTION_EVENT": {
        frozenset({"account_h", "phone_h"}): 3.0,
        frozenset({"account_h", "device_id"}): 2.7,
        frozenset({"account_h", "ip"}): 2.5,
        frozenset({"account_h", "endpoint"}): 2.2,
        frozenset({"phone_h", "device_id"}): 2.0,
    },
    "DDOS_SIGNAL_EVENT": {
        frozenset({"service_id", "endpoint"}): 3.6,
        frozenset({"service_id", "ip"}): 3.2,
        frozenset({"endpoint", "ip"}): 3.0,
        frozenset({"provider_id", "service_id"}): 2.0,
    },
    "WEB_ATTACK_EVENT": {
        frozenset({"service_id", "endpoint"}): 3.1,
        frozenset({"endpoint", "ip"}): 3.0,
        frozenset({"url", "ip"}): 2.7,
        frozenset({"url", "service_id"}): 2.2,
    },
    "PHISHING_MESSAGE_EVENT": {
        frozenset({"person_h", "account_h"}): 3.2,
        frozenset({"account_h", "domain"}): 2.9,
        frozenset({"account_h", "url"}): 2.9,
        frozenset({"person_h", "domain"}): 2.4,
        frozenset({"person_h", "url"}): 2.4,
    },
    "DNS_RESOLUTION_EVENT": {
        frozenset({"domain", "ip"}): 3.5,
        frozenset({"domain", "service_id"}): 2.2,
        frozenset({"domain", "url"}): 1.8,
    },
    "DOMAIN_REG_EVENT": {
        frozenset({"domain", "provider_id"}): 2.8,
        frozenset({"domain", "person_h"}): 2.5,
        frozenset({"domain", "service_id"}): 2.0,
    },
    "DFIR_FINDING_EVENT": {
        frozenset({"device_id", "ip"}): 2.8,
        frozenset({"device_id", "account_h"}): 2.5,
        frozenset({"device_id", "service_id"}): 2.0,
    },
    "DB_AUDIT_EVENT": {
        frozenset({"account_h", "service_id"}): 2.8,
        frozenset({"account_h", "endpoint"}): 2.4,
        frozenset({"service_id", "endpoint"}): 2.3,
    },
    "FILE_INTEGRITY_EVENT": {
        frozenset({"device_id", "service_id"}): 2.4,
        frozenset({"device_id", "endpoint"}): 2.0,
    },
    "SERVICE_HEALTH_EVENT": {
        frozenset({"service_id", "endpoint"}): 2.2,
        frozenset({"service_id", "provider_id"}): 1.8,
    },
}

_RELATION_EVENT_TYPES = tuple(sorted(_RELATION_WEIGHTS.keys()))


def derive_typed_edges_for_event(
    *,
    event_type: str,
    entity_keys: Sequence[str],
) -> List[Tuple[str, str, float]]:
    relation_weights = _RELATION_WEIGHTS.get(str(event_type or ""))
    if not relation_weights:
        return []

    unique_keys = [str(k) for k in dict.fromkeys(entity_keys or []) if k]
    out: List[Tuple[str, str, float]] = []
    for i, src in enumerate(unique_keys):
        src_prefix = _entity_prefix(src)
        for dst in unique_keys[i + 1 :]:
            dst_prefix = _entity_prefix(dst)
            weight = relation_weights.get(frozenset({src_prefix, dst_prefix}))
            if weight is None:
                continue
            a, b = (src, dst) if src < dst else (dst, src)
            out.append((a, b, float(weight)))
    return out


def typed_edges_from_postgres(
    db: Session,
    *,
    entity_keys: Sequence[str],
    window_start,
    window_end,
    max_events: int = 5000,
) -> List[Tuple[str, str, float]]:
    keys = [str(k) for k in dict.fromkeys(entity_keys or []) if k]
    if not keys:
        return []

    rows = db.execute(
        text(
            """
            SELECT
                el.event_type AS event_type,
                array_agg(ee.entity_key ORDER BY ee.entity_key) AS entity_keys
            FROM event_log el
            JOIN event_entity_index ee
              ON ee.event_hash = el.event_hash
            WHERE el.occurred_at >= :window_start
              AND el.occurred_at <= :window_end
              AND el.event_type = ANY(:event_types)
              AND ee.entity_key = ANY(:entity_keys)
            GROUP BY el.event_hash, el.event_type
            HAVING COUNT(*) >= 2
            ORDER BY MAX(el.occurred_at) DESC
            LIMIT :max_events
            """
        ),
        {
            "window_start": window_start,
            "window_end": window_end,
            "event_types": list(_RELATION_EVENT_TYPES),
            "entity_keys": keys,
            "max_events": max(100, int(max_events)),
        },
    ).fetchall()

    out: List[Tuple[str, str, float]] = []
    for row in rows:
        out.extend(
            derive_typed_edges_for_event(
                event_type=str(row[0] or ""),
                entity_keys=list(row[1] or []),
            )
        )
    return out

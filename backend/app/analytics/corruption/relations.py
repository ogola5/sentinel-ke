from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session


def _entity_prefix(entity_key: str) -> str:
    if ":" not in str(entity_key):
        return str(entity_key or "").strip().lower()
    return str(entity_key).split(":", 1)[0].strip().lower()


_RELATION_WEIGHTS: Dict[str, Dict[frozenset[str], float]] = {
    "TENDER_AWARD": {
        frozenset({"department", "tender"}): 2.0,
        frozenset({"tender", "supplier"}): 2.8,
        frozenset({"tender", "contract"}): 2.3,
        frozenset({"supplier", "contract"}): 2.6,
        frozenset({"contract", "project"}): 2.2,
    },
    "TENDER_AMENDMENT": {
        frozenset({"contract", "project"}): 2.4,
        frozenset({"supplier", "contract"}): 2.3,
        frozenset({"department", "contract"}): 2.0,
    },
    "SINGLE_SOURCE_AWARD": {
        frozenset({"department", "tender"}): 2.4,
        frozenset({"tender", "supplier"}): 3.0,
        frozenset({"supplier", "supplier_family"}): 2.5,
    },
    "COMPANY_REGISTRATION": {
        frozenset({"supplier", "supplier_family"}): 4.8,
        frozenset({"supplier", "director"}): 4.2,
        frozenset({"supplier", "account"}): 3.6,
        frozenset({"supplier_family", "director"}): 3.9,
        frozenset({"supplier_family", "account"}): 3.4,
    },
    "SUPPLIER_NETWORK_LINK": {
        frozenset({"supplier", "supplier_family"}): 5.0,
        frozenset({"supplier", "director"}): 4.4,
        frozenset({"supplier", "account"}): 4.0,
        frozenset({"supplier_family", "director"}): 4.1,
        frozenset({"supplier_family", "account"}): 3.9,
        frozenset({"director", "account"}): 3.2,
    },
    "PAYMENT_DISBURSEMENT": {
        frozenset({"supplier", "payment"}): 3.0,
        frozenset({"payment", "account"}): 3.0,
        frozenset({"payment", "project"}): 2.4,
        frozenset({"payment", "contract"}): 2.7,
        frozenset({"department", "payment"}): 2.2,
    },
    "APPROVER_LINK": {
        frozenset({"official", "department"}): 3.0,
        frozenset({"official", "contract"}): 3.2,
        frozenset({"official", "project"}): 2.8,
        frozenset({"official", "payment"}): 2.5,
    },
    "PROJECT_MILESTONE_CERTIFIED": {
        frozenset({"official", "project"}): 3.5,
        frozenset({"official", "contract"}): 3.0,
        frozenset({"payment", "project"}): 2.4,
        frozenset({"contract", "project"}): 3.2,
    },
    "SITE_INSPECTION": {
        frozenset({"official", "project"}): 3.2,
        frozenset({"official", "contract"}): 2.7,
        frozenset({"supplier", "project"}): 2.1,
    },
    "COMPLAINT_FILED": {
        frozenset({"supplier", "contract"}): 2.1,
        frozenset({"supplier", "project"}): 2.2,
        frozenset({"department", "project"}): 2.0,
        frozenset({"contract", "project"}): 2.5,
    },
    "DEFECT_NOTICE": {
        frozenset({"supplier", "project"}): 2.4,
        frozenset({"contract", "project"}): 2.8,
        frozenset({"department", "project"}): 2.1,
    },
    "PROJECT_DELAY": {
        frozenset({"supplier", "project"}): 2.2,
        frozenset({"contract", "project"}): 2.6,
        frozenset({"department", "project"}): 2.1,
    },
    "PROJECT_DELIVERY_ALERT": {
        frozenset({"supplier", "project"}): 2.8,
        frozenset({"supplier", "contract"}): 2.6,
        frozenset({"contract", "project"}): 3.0,
        frozenset({"department", "project"}): 2.4,
    },
    "DEBARMENT_LISTING": {
        frozenset({"supplier", "supplier_family"}): 3.8,
        frozenset({"supplier", "director"}): 3.4,
        frozenset({"supplier_family", "director"}): 3.5,
    },
    "WATCHLIST_HIT": {
        frozenset({"supplier", "supplier_family"}): 3.4,
        frozenset({"supplier", "director"}): 3.0,
        frozenset({"supplier_family", "director"}): 3.1,
    },
    "AUDIT_FINDING_EVENT": {
        frozenset({"department", "contract"}): 3.0,
        frozenset({"department", "project"}): 2.6,
        frozenset({"supplier", "contract"}): 3.0,
        frozenset({"supplier", "project"}): 2.6,
        frozenset({"contract", "project"}): 3.4,
        frozenset({"official", "contract"}): 2.6,
    },
    "CASE_OUTCOME_RECORDED": {
        frozenset({"department", "contract"}): 3.1,
        frozenset({"department", "project"}): 2.8,
        frozenset({"supplier", "contract"}): 3.1,
        frozenset({"supplier", "project"}): 2.8,
        frozenset({"contract", "project"}): 3.5,
        frozenset({"official", "supplier"}): 2.4,
        frozenset({"official", "contract"}): 2.7,
    },
    "SANCTION_APPLIED": {
        frozenset({"supplier", "contract"}): 3.2,
        frozenset({"supplier", "project"}): 2.8,
        frozenset({"official", "department"}): 2.5,
        frozenset({"official", "supplier"}): 2.8,
        frozenset({"contract", "project"}): 3.2,
    },
    "RECOVERY_ORDER": {
        frozenset({"supplier", "contract"}): 3.0,
        frozenset({"supplier", "project"}): 2.7,
        frozenset({"department", "project"}): 2.5,
        frozenset({"contract", "project"}): 3.1,
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

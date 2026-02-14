from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.analytics.ai_models import GraphFeatureSnapshot
from app.graph.neo4j_driver import get_driver


POSITIVE_RISK_FLAGS = {
    "DDOS_ALERT_SERVICE",
    "DDOS_ALERT_ENDPOINT",
    "CAMPAIGN_ENTITY",
    "VPN_CLUSTER_MEMBER",
    "DDOS_CLUSTER_MEMBER",
}

TRACKED_EVENT_TYPES = [
    "DDOS_SIGNAL_EVENT",
    "SIM_SWAP_EVENT",
    "TRANSACTION_EVENT",
    "PHISHING_MESSAGE_EVENT",
    "LOGIN_EVENT",
]


@dataclass(frozen=True)
class GNNNode:
    entity_key: str
    entity_type: str
    event_count: int
    source_count: int
    risk_flags: List[str]
    features: Dict[str, Any]


@dataclass(frozen=True)
class GNNDataset:
    window_key: str
    window_start: datetime
    window_end: datetime
    entity_keys: List[str]
    entity_types: List[str]
    feature_matrix: List[List[float]]
    labels: List[int]
    edges: List[Tuple[int, int, float]]
    node_meta: List[Dict[str, Any]]
    source_backend_used: str


def weak_label(*, risk_flags: Sequence[str], event_count: int, source_count: int) -> int:
    flag_hit = any(flag in POSITIVE_RISK_FLAGS for flag in (risk_flags or []))
    if flag_hit:
        return 1
    if event_count >= 25 and source_count >= 3:
        return 1
    return 0


def build_feature_vector(*, event_count: int, source_count: int, risk_flags: Sequence[str], features: Dict[str, Any]) -> List[float]:
    flags = set(risk_flags or [])
    f = features or {}

    last_seen_age = f.get("last_seen_age_sec")
    if isinstance(last_seen_age, (int, float)) and last_seen_age >= 0:
        recency = 1.0 / (1.0 + (float(last_seen_age) / 300.0))
    else:
        recency = 0.0

    event_types = f.get("event_types") or {}
    if not isinstance(event_types, dict):
        event_types = {}

    vec: List[float] = [
        math.log1p(max(0, int(event_count))),
        math.log1p(max(0, int(source_count))),
        recency,
        1.0 if "DDOS_ALERT_SERVICE" in flags or "DDOS_ALERT_ENDPOINT" in flags else 0.0,
        1.0 if "CAMPAIGN_ENTITY" in flags else 0.0,
        1.0 if "VPN_CLUSTER_MEMBER" in flags else 0.0,
        1.0 if "DDOS_CLUSTER_MEMBER" in flags else 0.0,
    ]

    for et in TRACKED_EVENT_TYPES:
        vec.append(math.log1p(max(0, int(event_types.get(et, 0)))))

    return vec


def collapse_edges(edges: Sequence[Tuple[str, str, float]]) -> List[Tuple[str, str, float]]:
    rolled: Dict[Tuple[str, str], float] = {}
    for src, dst, w in edges:
        if not src or not dst or src == dst:
            continue
        a, b = (src, dst) if src < dst else (dst, src)
        rolled[(a, b)] = rolled.get((a, b), 0.0) + float(w)

    out = [(a, b, round(w, 6)) for (a, b), w in rolled.items()]
    out.sort(key=lambda x: x[2], reverse=True)
    return out


def _latest_window_end(db: Session, window_key: str) -> Optional[datetime]:
    return (
        db.query(func.max(GraphFeatureSnapshot.window_end))
        .filter(GraphFeatureSnapshot.window_key == window_key)
        .scalar()
    )


def _edges_from_postgres(
    db: Session,
    *,
    entity_keys: List[str],
    window_start: datetime,
    window_end: datetime,
    min_edge_weight: int,
    max_edges: int,
) -> List[Tuple[str, str, float]]:
    if not entity_keys:
        return []

    rows = db.execute(
        text(
            """
            SELECT
                a.entity_key AS src,
                b.entity_key AS dst,
                COUNT(*)::float AS weight
            FROM event_entity_index a
            JOIN event_entity_index b
              ON a.event_hash = b.event_hash
             AND a.entity_key < b.entity_key
            JOIN event_log el
              ON el.event_hash = a.event_hash
            WHERE el.occurred_at >= :window_start
              AND el.occurred_at <= :window_end
              AND a.entity_key = ANY(:entity_keys)
              AND b.entity_key = ANY(:entity_keys)
            GROUP BY a.entity_key, b.entity_key
            HAVING COUNT(*) >= :min_edge_weight
            ORDER BY weight DESC
            LIMIT :max_edges
            """
        ),
        {
            "window_start": window_start,
            "window_end": window_end,
            "entity_keys": entity_keys,
            "min_edge_weight": max(1, int(min_edge_weight)),
            "max_edges": max(1, int(max_edges)),
        },
    ).fetchall()

    return [(str(r[0]), str(r[1]), float(r[2] or 0.0)) for r in rows]


def _edges_from_neo4j(
    *,
    entity_keys: List[str],
    max_edges: int,
) -> List[Tuple[str, str, float]]:
    if not entity_keys:
        return []

    query = """
    MATCH (a)-[r]->(b)
    WHERE exists(a.entity_key)
      AND exists(b.entity_key)
      AND a.entity_key IN $entity_keys
      AND b.entity_key IN $entity_keys
      AND a.entity_key < b.entity_key
    RETURN a.entity_key AS src, b.entity_key AS dst, count(r) AS weight
    ORDER BY weight DESC
    LIMIT $max_edges
    """

    driver = get_driver()
    try:
        with driver.session() as sess:
            rows = sess.run(query, entity_keys=entity_keys, max_edges=max(1, int(max_edges)))
            out = []
            for r in rows:
                src = r.get("src")
                dst = r.get("dst")
                w = r.get("weight")
                if not src or not dst:
                    continue
                out.append((str(src), str(dst), float(w or 0.0)))
            return out
    finally:
        try:
            driver.close()
        except Exception:
            pass


def load_dataset(
    db: Session,
    *,
    window_key: str = "Wmid",
    window_end: Optional[datetime] = None,
    max_entities: int = 3000,
    edge_backend: str = "hybrid",
    min_edge_weight: int = 1,
    max_edges: int = 30000,
) -> Optional[GNNDataset]:
    if window_end is None:
        window_end = _latest_window_end(db, window_key)
    if window_end is None:
        return None

    snapshots = (
        db.query(GraphFeatureSnapshot)
        .filter(GraphFeatureSnapshot.window_key == window_key)
        .filter(GraphFeatureSnapshot.window_end == window_end)
        .order_by(GraphFeatureSnapshot.event_count.desc())
        .limit(max(10, int(max_entities)))
        .all()
    )
    if not snapshots:
        return None

    entity_keys: List[str] = []
    entity_types: List[str] = []
    feature_matrix: List[List[float]] = []
    labels: List[int] = []
    node_meta: List[Dict[str, Any]] = []

    for s in snapshots:
        risk_flags = list(s.risk_flags or [])
        features = dict(s.features or {})

        source_count = int(features.get("source_count") or 0)
        event_count = int(s.event_count or 0)

        entity_keys.append(str(s.entity_key))
        entity_types.append(str(s.entity_type))
        feature_matrix.append(
            build_feature_vector(
                event_count=event_count,
                source_count=source_count,
                risk_flags=risk_flags,
                features=features,
            )
        )
        labels.append(
            weak_label(
                risk_flags=risk_flags,
                event_count=event_count,
                source_count=source_count,
            )
        )
        event_types = features.get("event_types") if isinstance(features.get("event_types"), dict) else {}
        node_meta.append(
            {
                "entity_key": str(s.entity_key),
                "entity_type": str(s.entity_type),
                "event_count": event_count,
                "source_count": source_count,
                "risk_flags": risk_flags,
                "event_types": dict(event_types),
            }
        )

    key_to_idx = {k: i for i, k in enumerate(entity_keys)}

    raw_edges: List[Tuple[str, str, float]] = []
    backend = (edge_backend or "hybrid").lower().strip()
    backend_used: List[str] = []

    if backend in {"neo4j", "hybrid"}:
        try:
            neo_edges = _edges_from_neo4j(entity_keys=entity_keys, max_edges=max_edges)
            raw_edges.extend(neo_edges)
            if neo_edges:
                backend_used.append("neo4j")
        except Exception:
            if backend == "neo4j":
                raise

    if backend in {"postgres", "hybrid"}:
        pg_edges = _edges_from_postgres(
            db,
            entity_keys=entity_keys,
            window_start=snapshots[0].window_start,
            window_end=window_end,
            min_edge_weight=min_edge_weight,
            max_edges=max_edges,
        )
        raw_edges.extend(pg_edges)
        if pg_edges:
            backend_used.append("postgres")

    collapsed = collapse_edges(raw_edges)
    edges: List[Tuple[int, int, float]] = []
    for src, dst, w in collapsed[:max_edges]:
        i = key_to_idx.get(src)
        j = key_to_idx.get(dst)
        if i is None or j is None or i == j:
            continue
        edges.append((i, j, float(w)))

    # Keep graph connected enough for message passing if sparse.
    if not edges and len(entity_keys) > 1:
        for i in range(len(entity_keys) - 1):
            edges.append((i, i + 1, 1.0))

    used = "+".join(sorted(set(backend_used))) if backend_used else "none"

    return GNNDataset(
        window_key=window_key,
        window_start=snapshots[0].window_start,
        window_end=window_end,
        entity_keys=entity_keys,
        entity_types=entity_types,
        feature_matrix=feature_matrix,
        labels=labels,
        edges=edges,
        node_meta=node_meta,
        source_backend_used=used,
    )

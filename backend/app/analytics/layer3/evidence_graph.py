from __future__ import annotations

from datetime import datetime
from typing import Dict, List

from sqlalchemy import text
from sqlalchemy.orm import Session


def recent_entity_event_hashes(
    db: Session,
    *,
    entity_key: str,
    window_start: datetime,
    window_end: datetime,
    limit: int = 20,
) -> List[str]:
    rows = db.execute(
        text(
            """
            SELECT ee.event_hash
            FROM event_entity_index ee
            JOIN event_log el ON el.event_hash = ee.event_hash
            WHERE ee.entity_key = :entity_key
              AND el.occurred_at >= :start
              AND el.occurred_at <= :end
            ORDER BY el.occurred_at DESC
            LIMIT :limit
            """
        ),
        {
            "entity_key": entity_key,
            "start": window_start,
            "end": window_end,
            "limit": limit,
        },
    ).fetchall()
    return [str(r[0]) for r in rows]


def build_entity_graph_paths(
    db: Session,
    *,
    entity_key: str,
    window_start: datetime,
    window_end: datetime,
    max_hops: int = 2,
    limit: int = 10,
) -> List[Dict[str, object]]:
    rows_1hop = db.execute(
        text(
            """
            SELECT b.entity_key AS neighbour,
                   b.entity_type AS neighbour_type,
                   COUNT(*) AS shared_events,
                   MIN(el.occurred_at) AS first_seen,
                   MAX(el.occurred_at) AS last_seen
            FROM event_entity_index a
            JOIN event_entity_index b
              ON a.event_hash = b.event_hash
             AND b.entity_key <> a.entity_key
            JOIN event_log el ON el.event_hash = a.event_hash
            WHERE a.entity_key = :entity_key
              AND el.occurred_at >= :start
              AND el.occurred_at <= :end
            GROUP BY b.entity_key, b.entity_type
            ORDER BY shared_events DESC
            LIMIT :limit
            """
        ),
        {
            "entity_key": entity_key,
            "start": window_start,
            "end": window_end,
            "limit": limit,
        },
    ).fetchall()

    paths: List[Dict[str, object]] = []
    for row in rows_1hop:
        neighbour = str(row[0])
        paths.append(
            {
                "path": [entity_key, neighbour],
                "node_types": ["entity", str(row[1] or "unknown")],
                "shared_events": int(row[2] or 0),
                "first_seen": row[3].isoformat() if row[3] else None,
                "last_seen": row[4].isoformat() if row[4] else None,
                "hop_count": 1,
            }
        )

    if max_hops >= 2 and rows_1hop:
        top_neighbours = [str(r[0]) for r in rows_1hop[:3]]
        rows_2hop = db.execute(
            text(
                """
                SELECT a.entity_key AS mid,
                       c.entity_key AS dest,
                       c.entity_type AS dest_type,
                       COUNT(*) AS shared_events
                FROM event_entity_index a
                JOIN event_entity_index c
                  ON a.event_hash = c.event_hash
                 AND c.entity_key <> :entity_key
                 AND c.entity_key <> ANY(:top_neighbours)
                JOIN event_log el ON el.event_hash = a.event_hash
                WHERE a.entity_key = ANY(:top_neighbours)
                  AND el.occurred_at >= :start
                  AND el.occurred_at <= :end
                GROUP BY a.entity_key, c.entity_key, c.entity_type
                ORDER BY shared_events DESC
                LIMIT :limit
                """
            ),
            {
                "entity_key": entity_key,
                "top_neighbours": top_neighbours,
                "start": window_start,
                "end": window_end,
                "limit": limit,
            },
        ).fetchall()
        for row in rows_2hop:
            paths.append(
                {
                    "path": [entity_key, str(row[0]), str(row[1])],
                    "node_types": ["entity", "intermediate", str(row[2] or "unknown")],
                    "shared_events": int(row[3] or 0),
                    "hop_count": 2,
                }
            )

    return paths

from __future__ import annotations

import argparse
import json
from typing import Iterable, Optional

from sqlalchemy import select

from app.graph.models import GraphDeltaLog
from app.graph.projector import project_event_to_delta
from app.graph.repository import GraphDeltaRepository
from app.graph.neo4j_worker import run_once as run_neo4j_once
from app.ingestion.schemas import CanonicalEvent
from app.ledger.db import SessionLocal
from app.ledger.models import EventEntityIndex, EventLog


def _candidate_events(
    *,
    db,
    entity_key: Optional[str],
    event_type: Optional[str],
    limit: int,
) -> Iterable[EventLog]:
    stmt = (
        select(EventLog)
        .outerjoin(GraphDeltaLog, GraphDeltaLog.event_hash == EventLog.event_hash)
        .where(GraphDeltaLog.event_hash.is_(None))
        .order_by(EventLog.occurred_at.asc())
        .limit(limit)
    )
    if entity_key:
        stmt = stmt.join(EventEntityIndex, EventEntityIndex.event_hash == EventLog.event_hash)
        stmt = stmt.where(EventEntityIndex.entity_key == entity_key)
    if event_type:
        stmt = stmt.where(EventLog.event_type == event_type)
    return db.execute(stmt).scalars().all()


def _canonical_from_row(row: EventLog) -> CanonicalEvent:
    return CanonicalEvent(
        event_type=str(row.event_type),
        occurred_at=row.occurred_at,
        confidence=0.5,
        payload=dict(row.payload_json or {}),
        anchors=dict(row.anchors_json or {}),
        classification=str(row.classification) if row.classification else None,
        schema_version=str(row.schema_version or "v1"),
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill missing graph_delta_log rows from canonical ledger events.",
    )
    parser.add_argument("--entity-key", default=None, help="Backfill only events touching this entity key.")
    parser.add_argument("--event-type", default=None, help="Backfill only one event type.")
    parser.add_argument("--limit", type=int, default=1000, help="Maximum missing events to backfill.")
    parser.add_argument(
        "--project-neo4j",
        action="store_true",
        help="After creating missing delta rows, run the Neo4j worker until the delta queue is drained.",
    )
    parser.add_argument("--batch-size", type=int, default=500, help="Neo4j worker batch size when --project-neo4j is set.")
    args = parser.parse_args()

    db = SessionLocal()
    repo = GraphDeltaRepository(db)
    try:
        rows = list(
            _candidate_events(
                db=db,
                entity_key=args.entity_key,
                event_type=args.event_type,
                limit=max(1, int(args.limit)),
            )
        )
        created = 0
        failed: list[dict[str, str]] = []
        for row in rows:
            try:
                delta = project_event_to_delta(
                    event=_canonical_from_row(row),
                    event_hash=str(row.event_hash),
                )
                repo.insert_delta(
                    event_hash=str(row.event_hash),
                    nodes=[node.__dict__ for node in delta.nodes],
                    edges=[edge.__dict__ for edge in delta.edges],
                )
                created += 1
            except Exception as exc:  # pragma: no cover - operational script
                failed.append({"event_hash": str(row.event_hash), "error": str(exc)})
                db.rollback()

        projected = 0
        if args.project_neo4j:
            while True:
                batch_processed = run_neo4j_once(batch_size=max(1, int(args.batch_size)))
                projected += batch_processed
                if batch_processed <= 0:
                    break

        print(
            json.dumps(
                {
                    "status": "ok",
                    "candidate_count": len(rows),
                    "graph_deltas_created": created,
                    "neo4j_projected": projected,
                    "failed_count": len(failed),
                    "failed": failed[:20],
                }
            )
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import select, asc
from sqlalchemy.orm import Session

from app.graph.models import GraphDeltaLog, ProjectionCursor


class DeltaStore:
    def __init__(self, db: Session):
        self.db = db

    def get_cursor(self, name: str = "neo4j") -> Optional[datetime]:
        cur = self.db.get(ProjectionCursor, name)
        return cur.last_created_at if cur else None

    def set_cursor(self, last_created_at: datetime, name: str = "neo4j") -> None:
        cur = self.db.get(ProjectionCursor, name)
        if not cur:
            cur = ProjectionCursor(name=name, last_created_at=last_created_at)
            self.db.add(cur)
        else:
            cur.last_created_at = last_created_at
        self.db.commit()

    def fetch_batch(self, *, after: Optional[datetime], limit: int = 500) -> list[GraphDeltaLog]:
        q = select(GraphDeltaLog).order_by(asc(GraphDeltaLog.created_at)).limit(limit)
        if after:
            q = q.where(GraphDeltaLog.created_at > after)
        return list(self.db.execute(q).scalars().all())

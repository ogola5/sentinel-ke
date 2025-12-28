from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.graph.models import GraphDeltaLog


class GraphDeltaRepository:
    def __init__(self, db: Session):
        self.db = db

    def insert_delta(
        self,
        *,
        event_hash: str,
        nodes: list[dict],
        edges: list[dict],
    ) -> None:
        row = GraphDeltaLog(
            event_hash=event_hash,
            nodes_json=nodes,
            edges_json=edges,
        )
        try:
            self.db.add(row)
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            # idempotent: delta already exists

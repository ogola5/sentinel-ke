from datetime import datetime
from sqlalchemy import Column, String, DateTime, JSON, Index, ForeignKey

from app.ledger.models import Base


class GraphDeltaLog(Base):
    __tablename__ = "graph_delta_log"

    event_hash = Column(
        String,
        ForeignKey("event_log.event_hash", ondelete="CASCADE"),
        primary_key=True,
    )

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    nodes_json = Column(JSON, nullable=False)
    edges_json = Column(JSON, nullable=False)

    __table_args__ = (
        Index("ix_graph_delta_created_at", "created_at"),
    )

class ProjectionCursor(Base):
    __tablename__ = "projection_cursor"

    name = Column(String, primary_key=True)  # e.g. "neo4j"
    last_created_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)
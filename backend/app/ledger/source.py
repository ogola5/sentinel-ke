from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, String, Index
from sqlalchemy.dialects.postgresql import UUID

from app.ledger.models import Base


class Source(Base):
    __tablename__ = "source"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # what ingestion checks
    api_key = Column(String, nullable=False, unique=True)

    # metadata
    source_id = Column(String, nullable=False, unique=True)  # external identifier for audit/logs
    source_type = Column(String, nullable=False)             # e.g. DEV_TEST, KPA, KRA, TELCO
    classification_level = Column(String, nullable=False, default="RESTRICTED")
    enabled = Column(Boolean, nullable=False, default=True)

    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        Index("ix_source_api_key", "api_key"),
        Index("ix_source_enabled", "enabled"),
    )

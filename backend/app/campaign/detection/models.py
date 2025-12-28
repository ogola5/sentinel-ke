from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, DateTime, String, Float, Boolean, Index
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class IpEnrichmentCache(Base):
    __tablename__ = "ip_enrichment_cache"

    ip = Column(String, primary_key=True)  # "8.8.8.8"
    asn = Column(String, nullable=True)    # "AS15169"
    org = Column(String, nullable=True)    # "Google LLC"
    provider_id = Column(String, nullable=True)  # your internal provider key
    vpn_flag = Column(Boolean, nullable=False, default=False)
    vpn_score = Column(Float, nullable=False, default=0.0)

    updated_at = Column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_ip_enrichment_cache_updated_at", "updated_at"),
    )

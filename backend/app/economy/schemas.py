from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, model_validator


class ProcurementRecord(BaseModel):
    """
    Input payload for procurement anomaly analysis.
    """

    tender_id: Optional[str] = None
    vendor_id: Optional[str] = None
    project_id: Optional[str] = None
    agency: Optional[str] = None
    sector: str = Field(..., min_length=1)

    amount: float = Field(..., ge=0.0)
    baseline_amount: Optional[float] = Field(default=None, ge=0.0)
    currency: str = Field(default="KES", min_length=1)

    competitive_bids: Optional[int] = Field(default=None, ge=0)
    vendor_award_count_90d: Optional[int] = Field(default=None, ge=0)
    single_source: bool = False
    change_order_count: Optional[int] = Field(default=None, ge=0)

    occurred_at: Optional[datetime] = None
    evidence: Dict[str, Any] = Field(default_factory=dict)


class EconomicSignalIn(BaseModel):
    """
    Generic economic integrity signal entry.
    """

    signal_type: str = Field(..., min_length=1)
    sector: str = Field(..., min_length=1)
    agency: Optional[str] = None
    entity_type: Optional[str] = None
    entity_id: Optional[str] = None

    window_start: datetime
    window_end: datetime

    score: float = Field(..., ge=0.0, le=1.0)
    severity: Optional[str] = None
    source: Optional[str] = None

    reason_codes: List[str] = Field(default_factory=list)
    indicators: Dict[str, Any] = Field(default_factory=dict)
    evidence: Dict[str, Any] = Field(default_factory=dict)


class IntegritySnapshotIn(BaseModel):
    """
    Snapshot from an external system to detect tamper/deletion patterns.
    """

    source_system: str = Field(..., min_length=1)
    record_type: str = Field(..., min_length=1)
    record_id: str = Field(..., min_length=1)

    observed_at: Optional[datetime] = None
    is_deleted: bool = False

    payload: Dict[str, Any] = Field(default_factory=dict)
    payload_hash: Optional[str] = None

    change_ticket: Optional[str] = None
    actor_id: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    evidence: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_payload_material(self) -> "IntegritySnapshotIn":
        # For non-delete snapshots, require either payload or payload_hash.
        if not self.is_deleted and not self.payload and not self.payload_hash:
            raise ValueError("payload or payload_hash is required when is_deleted=false")
        return self

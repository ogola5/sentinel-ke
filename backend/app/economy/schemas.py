from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


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

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from app.ingestion.schemas import Classification


class ConnectorEventRequest(BaseModel):
    source_api_key: str
    payload: Dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)
    classification: Optional[Classification] = None


class ConnectorBatchRequest(BaseModel):
    source_api_key: str
    items: List[Dict[str, Any]] = Field(default_factory=list, min_length=1, max_length=1000)
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)
    classification: Optional[Classification] = None


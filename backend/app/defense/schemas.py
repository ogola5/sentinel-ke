from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator

from app.defense.actions import supported_action_keys


class VulnerabilityUpsertRequest(BaseModel):
    asset_id: str = Field(..., min_length=1, max_length=256)
    cve_id: str = Field(..., min_length=3, max_length=64)
    source: str = Field(default="kev", min_length=1, max_length=64)
    severity: str = Field(default="medium", min_length=1, max_length=32)
    epss: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    kev: bool = False
    status: str = Field(default="open", min_length=1, max_length=32)
    discovered_at: Optional[datetime] = None
    due_at: Optional[datetime] = None
    patched_at: Optional[datetime] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    section_code: Optional[str] = None


class BackupAttestationRequest(BaseModel):
    asset_id: str = Field(..., min_length=1, max_length=256)
    backup_id: str = Field(..., min_length=1, max_length=256)
    immutable: bool = False
    object_lock_until: Optional[datetime] = None
    backup_hash: Optional[str] = Field(default=None, max_length=256)
    storage_tier: Optional[str] = Field(default=None, max_length=64)
    status: str = Field(default="unknown", min_length=1, max_length=32)
    rpo_hours: Optional[float] = Field(default=None, ge=0.0, le=365 * 24)
    attested_at: Optional[datetime] = None
    evidence: Dict[str, Any] = Field(default_factory=dict)
    section_code: Optional[str] = None


class RestoreDrillRequest(BaseModel):
    asset_id: str = Field(..., min_length=1, max_length=256)
    backup_id: str = Field(..., min_length=1, max_length=256)
    success: bool
    rto_target_minutes: int = Field(default=240, ge=1, le=60 * 24 * 14)
    rto_actual_minutes: Optional[float] = Field(default=None, ge=0.0, le=60 * 24 * 30)
    notes: Optional[str] = Field(default=None, max_length=2000)
    evidence: Dict[str, Any] = Field(default_factory=dict)
    section_code: Optional[str] = None


class IncidentRunCreateRequest(BaseModel):
    incident_key: str = Field(..., min_length=1, max_length=256)
    severity: str = Field(default="medium", min_length=1, max_length=32)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    section_code: Optional[str] = None


class ContainmentActionRequest(BaseModel):
    action_type: str = Field(..., min_length=1, max_length=64)
    target: str = Field(..., min_length=1, max_length=512)
    details: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("action_type")
    @classmethod
    def _validate_action_type(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in supported_action_keys():
            allowed = ", ".join(sorted(supported_action_keys()))
            raise ValueError(f"unsupported_action_type:{normalized}. allowed={allowed}")
        return normalized


class IncidentRunActionBatchRequest(BaseModel):
    actions: List[ContainmentActionRequest] = Field(default_factory=list, min_length=1)


class CryptoSnapshotRequest(BaseModel):
    details: Dict[str, Any] = Field(default_factory=dict)
    section_code: Optional[str] = None


class ThreatAlertRefreshRequest(BaseModel):
    minutes: int = Field(default=60, ge=1, le=24 * 60)

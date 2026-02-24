from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, model_validator


LegalOrderStatus = Literal["active", "revoked", "expired"]
GrantStatus = Literal["allow", "deny", "expired", "revoked", "used"]


class LegalOrderCreate(BaseModel):
    order_number: str = Field(..., min_length=1)
    court_name: str = Field(..., min_length=1)
    case_reference: Optional[str] = None
    purpose: str = Field(..., min_length=1)
    authorized_by: str = Field(..., min_length=1)
    issued_at: Optional[datetime] = None
    valid_from: datetime
    valid_until: datetime
    allowed_actions: List[str] = Field(default_factory=list, min_length=1)
    allowed_targets: List[str] = Field(default_factory=list, min_length=1)
    constraints: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_by: str = Field(..., min_length=1)

    @model_validator(mode="after")
    def _validate_time_window(self) -> "LegalOrderCreate":
        if self.valid_until <= self.valid_from:
            raise ValueError("valid_until must be after valid_from")
        return self


class LegalOrderRevoke(BaseModel):
    revoked_by: str = Field(..., min_length=1)
    reason: str = Field(..., min_length=1)


class LegalAuthorizationRequest(BaseModel):
    order_id: str = Field(..., min_length=1)
    action_type: str = Field(..., min_length=1)
    target: str = Field(..., min_length=1)
    requested_by: str = Field(..., min_length=1)
    approved_by: List[str] = Field(default_factory=list)
    approval_signatures: List["ApprovalSignature"] = Field(default_factory=list)
    justification: Optional[str] = None
    requested_minutes: int = Field(default=30, ge=1, le=24 * 60)
    policy_version: str = Field(default="v1", min_length=1)
    model_action_scope: Dict[str, Any] = Field(default_factory=dict)
    evidence: Dict[str, Any] = Field(default_factory=dict)


class ApprovalSignature(BaseModel):
    approver_id: str = Field(..., min_length=1)
    signature_hex: str = Field(..., min_length=1)


class ApprovalPayloadRequest(BaseModel):
    order_id: str = Field(..., min_length=1)
    action_type: str = Field(..., min_length=1)
    target: str = Field(..., min_length=1)
    requested_by: str = Field(..., min_length=1)
    requested_minutes: int = Field(default=30, ge=1, le=24 * 60)


class ScanCandidate(BaseModel):
    target: str = Field(..., min_length=1)
    estimated_cost: float = Field(..., gt=0.0)
    risk_score: float = Field(..., ge=0.0, le=1.0)
    criticality: float = Field(default=1.0, ge=0.1, le=10.0)
    intel_confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class LegalScanPlanRequest(BaseModel):
    order_id: str = Field(..., min_length=1)
    action_type: str = Field(..., min_length=1)
    max_budget: float = Field(..., gt=0.0)
    candidates: List[ScanCandidate] = Field(default_factory=list, min_length=1)
    requested_by: str = Field(..., min_length=1)


class LegalScanPlanResponse(BaseModel):
    order_id: str
    action_type: str
    max_budget: float
    used_budget: float
    total_expected_risk_reduction: float
    selected_targets: List[Dict[str, Any]]
    skipped_targets: List[Dict[str, Any]]


class LegalEvidenceExportRequest(BaseModel):
    campaign_id: str = Field(..., min_length=1)
    order_id: str = Field(..., min_length=1)
    grant_ids: List[str] = Field(default_factory=list)
    include_stix: bool = True
    exported_by: str = Field(..., min_length=1)
    notes: Optional[str] = None


class LegalEvidenceBundleOut(BaseModel):
    bundle_id: str
    export_type: str
    campaign_id: str
    order_id: str
    root_hash: str
    prev_chain_hash: Optional[str] = None
    chain_hash: str
    created_by: str
    created_at: str

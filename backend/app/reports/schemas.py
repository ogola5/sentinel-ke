from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator


ReportType = Literal[
    "incident_brief",
    "entity_investigation",
    "campaign_case",
    "legal_evidence_bundle",
    "ai_decision_explanation",
    "model_governance",
]

ReportPeriod = Literal[
    "hourly",
    "daily",
    "weekly",
    "monthly",
    "quarterly",
    "semi_annual",
    "annual",
]

ReportFormat = Literal["json", "html", "pdf"]


class ReportRequest(BaseModel):
    report_type: ReportType
    period: ReportPeriod = "daily"
    format: ReportFormat = "html"
    prediction_type: str = Field(default="risk_gnn", min_length=1)
    entity_key: Optional[str] = None
    campaign_id: Optional[str] = None
    bundle_id: Optional[str] = None
    prediction_id: Optional[str] = None
    model_version: Optional[str] = None
    classification: str = Field(default="RESTRICTED", min_length=1)

    @model_validator(mode="after")
    def validate_subject_requirements(self) -> "ReportRequest":
        if self.report_type == "entity_investigation" and not self.entity_key:
            raise ValueError("entity_key_required")
        if self.report_type == "campaign_case" and not self.campaign_id:
            raise ValueError("campaign_id_required")
        if self.report_type == "legal_evidence_bundle" and not (self.bundle_id or self.campaign_id):
            raise ValueError("bundle_id_or_campaign_id_required")
        if self.report_type == "ai_decision_explanation" and not (self.prediction_id or self.entity_key):
            raise ValueError("prediction_id_or_entity_key_required")
        return self

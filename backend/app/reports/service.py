from __future__ import annotations

import html
import json
import re
import uuid
from io import BytesIO
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, Preformatted, SimpleDocTemplate, Spacer
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.analytics.ai_models import (
    AIExplanation,
    AIAttackPathScore,
    AIAttackTechniqueHit,
    AICampaignRiskIndicator,
    AIDecisionFusion,
    AIDriftReport,
    AIModelLineage,
    AIModelRollout,
    AIPrediction,
    GNNTrainingRun,
)
from app.analytics.layer3.ai_intel import techniques_to_tools
from app.analytics.layer3.forecasting import build_risk_forecast
from app.analytics.layer3.trust_service import build_campaign_trust_summary, build_entity_trust_summary
from app.campaign.models import Campaign, CampaignEntity, CampaignEvent
from app.cases.builders import build_case_packet
from app.defense.models import ContainmentAction
from app.ledger.models import AuditLog, EventEntityIndex, EventLog
from app.legal.models import (
    LegalAuthorizationGrant,
    LegalEvidenceAnchor,
    LegalEvidenceBundle,
    LegalEvidenceCertificate,
    LegalOrder,
)
from app.reports.schemas import ReportPeriod, ReportRequest


SUSPICIOUS_EVENT_TYPES = (
    "DDOS_SIGNAL_EVENT",
    "SIM_SWAP_EVENT",
    "PHISHING_MESSAGE_EVENT",
    "DFIR_FINDING_EVENT",
    "FILE_INTEGRITY_EVENT",
    "DB_AUDIT_EVENT",
    "VULNERABILITY_EVENT",
    "WEB_ATTACK_EVENT",
)

PERIOD_LOOKBACKS: dict[str, tuple[str, timedelta]] = {
    "hourly": ("Hourly", timedelta(hours=1)),
    "daily": ("Daily", timedelta(days=1)),
    "weekly": ("Weekly", timedelta(days=7)),
    "monthly": ("Monthly", timedelta(days=30)),
    "quarterly": ("Quarterly", timedelta(days=91)),
    "semi_annual": ("Semi-Annual", timedelta(days=182)),
    "annual": ("Annual", timedelta(days=365)),
}

REPORT_CATALOG: list[dict[str, Any]] = [
    {
        "report_type": "incident_brief",
        "title": "Incident Brief",
        "audience": ["soc", "section_commander", "agency_lead"],
        "description": "National or section-level situational brief in plain English with actions and evidence summary.",
        "required_fields": [],
        "supported_formats": ["json", "html", "pdf"],
    },
    {
        "report_type": "entity_investigation",
        "title": "Entity Investigation Report",
        "audience": ["analyst", "dfir", "investigator"],
        "description": "Explains one entity's score, graph links, evidence paths, techniques, tools, and actions.",
        "required_fields": ["entity_key"],
        "supported_formats": ["json", "html", "pdf"],
    },
    {
        "report_type": "campaign_case",
        "title": "Campaign Case Report",
        "audience": ["investigator", "supervisor", "inter-agency"],
        "description": "Converts a campaign into a human-readable case report with timeline, entities, evidence, and legal readiness.",
        "required_fields": ["campaign_id"],
        "supported_formats": ["json", "html", "pdf"],
    },
    {
        "report_type": "legal_evidence_bundle",
        "title": "Legal Evidence Bundle Report",
        "audience": ["legal", "audit", "court_support"],
        "description": "Summarizes legal order, grants, chain hashes, anchors, and certificates for one evidence bundle.",
        "required_fields": ["bundle_id or campaign_id"],
        "supported_formats": ["json", "html", "pdf"],
    },
    {
        "report_type": "ai_decision_explanation",
        "title": "AI Decision Explanation Report",
        "audience": ["oversight", "analyst", "non_technical_reviewer"],
        "description": "Explains why an AI score was produced, what evidence supported it, and what would change the decision.",
        "required_fields": ["prediction_id or entity_key"],
        "supported_formats": ["json", "html", "pdf"],
    },
    {
        "report_type": "model_governance",
        "title": "Model Governance Report",
        "audience": ["cto", "oversight", "judges", "procurement_review"],
        "description": "Documents training provenance, fairness, drift, rollout, caveats, and model governance status.",
        "required_fields": [],
        "supported_formats": ["json", "html", "pdf"],
    },
]


def report_catalog() -> dict[str, Any]:
    periods = [
        {"id": key, "label": label, "lookback_days": round(delta.total_seconds() / 86400.0, 2)}
        for key, (label, delta) in PERIOD_LOOKBACKS.items()
    ]
    return {
        "report_types": REPORT_CATALOG,
        "periods": periods,
        "formats": ["json", "html", "pdf"],
    }


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _humanize_code(value: str | None) -> str:
    raw = str(value or "").strip()
    if not raw:
        return "Unknown"
    pretty = raw.replace("_", " ").replace("-", " ").strip().lower()
    return pretty[:1].upper() + pretty[1:]


def _risk_label(score: float) -> str:
    val = float(score or 0.0)
    if val >= 90:
        return "critical"
    if val >= 75:
        return "high"
    if val >= 55:
        return "medium"
    return "low"


def _confidence_statement(confidence: float | None, uncertainty: float | None) -> str:
    conf = float(confidence or 0.0)
    unc = float(uncertainty or 0.0)
    if conf >= 85 and unc <= 0.2:
        return "The system has high confidence and low uncertainty in this assessment."
    if conf >= 70 and unc <= 0.4:
        return "The system has moderate-to-high confidence, but the result should still be reviewed by an analyst."
    if conf >= 50:
        return "The system sees meaningful risk signals, but uncertainty remains material."
    return "Confidence is limited. Treat this as a lead for review, not a strong conclusion."


def _plain_limitations() -> list[str]:
    return [
        "AI output is an investigative indicator, not final proof.",
        "Model metrics may reflect weak-label consistency rather than confirmed real-world case outcomes.",
        "External threat-intel indicators can increase early warning value but may contain noise or stale artifacts.",
    ]


def _short_json(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True, default=str)


def _sanitize_slug(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "-", value).strip("-").lower() or "report"


def _period_context(period: ReportPeriod) -> dict[str, Any]:
    label, delta = PERIOD_LOOKBACKS[period]
    end = _now()
    start = end - delta
    return {
        "id": period,
        "label": label,
        "start": start,
        "end": end,
        "lookback_hours": round(delta.total_seconds() / 3600.0, 2),
        "lookback_days": round(delta.total_seconds() / 86400.0, 2),
    }


def _serialize_path(path: AIAttackPathScore | None) -> dict[str, Any] | None:
    if not path:
        return None
    return {
        "path_score": float(path.path_score or 0.0),
        "hop_count": int(path.hop_count or 0),
        "evidence_entity_keys": list(path.evidence_entity_keys or []),
        "details": dict(path.details_json or {}),
        "created_at": path.created_at.isoformat(),
    }


def _serialize_fusion(row: AIDecisionFusion | None) -> dict[str, Any] | None:
    if not row:
        return None
    return {
        "fused_score": float(row.fused_score or 0.0),
        "severity": row.severity,
        "decision": row.decision,
        "selected_model_version": row.selected_model_version,
        "signals": dict(row.signals_json or {}),
        "created_at": row.created_at.isoformat(),
    }


def _serialize_prediction(row: AIPrediction | None) -> dict[str, Any] | None:
    if not row:
        return None
    return {
        "prediction_id": str(row.id),
        "entity_key": row.entity_key,
        "entity_type": row.entity_type,
        "prediction_type": row.prediction_type,
        "model_version": row.model_version,
        "window_key": row.window_key,
        "window_end": row.window_end.isoformat(),
        "score": float(row.score or 0.0),
        "confidence": float(row.confidence or 0.0),
        "uncertainty": float(row.uncertainty or 0.0),
        "abstained": bool(row.abstained),
        "kill_chain_stage": row.kill_chain_stage,
        "decision_source": row.decision_source,
        "reason_codes": list(row.reason_codes or []),
        "details": dict(row.details_json or {}),
        "created_at": row.created_at.isoformat(),
    }


def _serialize_explanation(row: AIExplanation | None) -> dict[str, Any] | None:
    if not row:
        return None
    return {
        "reason_codes": list(row.reason_codes or []),
        "evidence_hashes": list(row.evidence_hashes or []),
        "evidence_paths": list(row.evidence_paths or []),
        "recommended_controls": list(row.recommended_controls_json or []),
        "counterfactual": dict(row.counterfactual_json or {}),
        "details": dict(row.details_json or {}),
        "created_at": row.created_at.isoformat(),
    }


def _serialize_bundle(
    bundle: LegalEvidenceBundle,
    *,
    order: LegalOrder | None,
    grants: Sequence[LegalAuthorizationGrant],
    anchor: LegalEvidenceAnchor | None,
    certificate: LegalEvidenceCertificate | None,
) -> dict[str, Any]:
    return {
        "bundle_id": bundle.bundle_id,
        "export_type": bundle.export_type,
        "campaign_id": bundle.campaign_id,
        "order_id": bundle.order_id,
        "root_hash": bundle.root_hash,
        "prev_chain_hash": bundle.prev_chain_hash,
        "chain_hash": bundle.chain_hash,
        "created_by": bundle.created_by,
        "created_at": bundle.created_at.isoformat(),
        "order": None if order is None else {
            "order_id": order.order_id,
            "order_number": order.order_number,
            "court_name": order.court_name,
            "case_reference": order.case_reference,
            "purpose": order.purpose,
            "authorized_by": order.authorized_by,
            "issued_at": order.issued_at.isoformat(),
            "valid_from": order.valid_from.isoformat(),
            "valid_until": order.valid_until.isoformat(),
            "status": order.status,
            "allowed_actions": list(order.allowed_actions_json or []),
            "allowed_targets": list(order.allowed_targets_json or []),
            "constraints": dict(order.constraints_json or {}),
            "metadata": dict(order.metadata_json or {}),
        },
        "grants": [
            {
                "grant_id": grant.grant_id,
                "action_type": grant.action_type,
                "target": grant.target,
                "requested_by": grant.requested_by,
                "approved_by": list(grant.approved_by_json or []),
                "status": grant.status,
                "reason_codes": list(grant.reason_codes_json or []),
                "valid_from": grant.valid_from.isoformat(),
                "valid_until": grant.valid_until.isoformat(),
                "evidence": dict(grant.evidence_json or {}),
                "created_at": grant.created_at.isoformat(),
            }
            for grant in grants
        ],
        "anchor": None if anchor is None else {
            "anchor_id": anchor.anchor_id,
            "anchor_status": anchor.anchor_status,
            "minio_backend": anchor.minio_backend,
            "minio_bucket": anchor.minio_bucket,
            "minio_object_key": anchor.minio_object_key,
            "immudb_backend": anchor.immudb_backend,
            "immudb_key": anchor.immudb_key,
            "immudb_tx_id": anchor.immudb_tx_id,
            "immudb_verified": bool(anchor.immudb_verified),
            "anchor_receipt_hash": anchor.anchor_receipt_hash,
            "error": dict(anchor.error_json or {}),
            "metadata": dict(anchor.metadata_json or {}),
            "created_at": anchor.created_at.isoformat(),
        },
        "certificate": None if certificate is None else {
            "certificate_id": certificate.certificate_id,
            "framework": certificate.framework,
            "jurisdiction": certificate.jurisdiction,
            "statement_hash": certificate.statement_hash,
            "signed_by": certificate.signed_by,
            "signature_method": certificate.signature_method,
            "metadata": dict(certificate.metadata_json or {}),
            "created_at": certificate.created_at.isoformat(),
        },
        "payload": dict(bundle.payload_json or {}),
    }


def _latest_prediction_for_entity(
    db: Session,
    *,
    entity_key: str,
    prediction_type: str,
    end: datetime,
) -> AIPrediction | None:
    return (
        db.query(AIPrediction)
        .filter(AIPrediction.entity_key == entity_key)
        .filter(AIPrediction.prediction_type == prediction_type)
        .filter(AIPrediction.window_end <= end)
        .order_by(AIPrediction.window_end.desc(), AIPrediction.created_at.desc())
        .first()
    )


def _latest_prediction_by_id(db: Session, prediction_id: str) -> AIPrediction | None:
    return db.query(AIPrediction).filter(AIPrediction.id == prediction_id).first()


def _latest_explanation(db: Session, prediction_id: Any) -> AIExplanation | None:
    return db.query(AIExplanation).filter(AIExplanation.prediction_id == prediction_id).first()


def _latest_path_score(db: Session, *, entity_key: str, prediction_type: str, end: datetime) -> AIAttackPathScore | None:
    return (
        db.query(AIAttackPathScore)
        .filter(AIAttackPathScore.entity_key == entity_key)
        .filter(AIAttackPathScore.prediction_type == prediction_type)
        .filter(AIAttackPathScore.window_end <= end)
        .order_by(AIAttackPathScore.window_end.desc())
        .first()
    )


def _latest_fusion(db: Session, *, entity_key: str, prediction_type: str, end: datetime) -> AIDecisionFusion | None:
    return (
        db.query(AIDecisionFusion)
        .filter(AIDecisionFusion.entity_key == entity_key)
        .filter(AIDecisionFusion.prediction_type == prediction_type)
        .filter(AIDecisionFusion.window_end <= end)
        .order_by(AIDecisionFusion.window_end.desc())
        .first()
    )


def _latest_containment(db: Session, entity_key: str) -> ContainmentAction | None:
    target = entity_key.split(":", 1)[1] if ":" in entity_key else entity_key
    return (
        db.query(ContainmentAction)
        .filter(ContainmentAction.target.in_([entity_key, target]))
        .order_by(ContainmentAction.executed_at.desc(), ContainmentAction.created_at.desc())
        .first()
    )


def _latest_gnn_run(
    db: Session,
    *,
    prediction_type: str,
    model_version: str | None = None,
) -> GNNTrainingRun | None:
    q = db.query(GNNTrainingRun).filter(GNNTrainingRun.prediction_type == prediction_type)
    if model_version:
        q = q.filter(GNNTrainingRun.model_version == model_version)
    return q.order_by(GNNTrainingRun.created_at.desc()).first()


def _recent_events_for_entity(
    db: Session,
    *,
    entity_key: str,
    start: datetime,
    end: datetime,
    limit: int = 20,
) -> list[dict[str, Any]]:
    rows = (
        db.query(EventLog)
        .join(EventEntityIndex, EventEntityIndex.event_hash == EventLog.event_hash)
        .filter(EventEntityIndex.entity_key == entity_key)
        .filter(EventLog.occurred_at >= start)
        .filter(EventLog.occurred_at <= end)
        .order_by(EventLog.occurred_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "event_hash": row.event_hash,
            "event_type": row.event_type,
            "source_id": row.source_id,
            "section_code": row.section_code,
            "occurred_at": row.occurred_at.isoformat(),
            "anchors": dict(row.anchors_json or {}),
            "payload": dict(row.payload_json or {}),
        }
        for row in rows
    ]


def _latest_techniques(
    db: Session,
    *,
    entity_key: str,
    prediction_type: str,
    end: datetime,
    limit: int = 10,
) -> list[dict[str, Any]]:
    rows = (
        db.query(AIAttackTechniqueHit)
        .filter(AIAttackTechniqueHit.entity_key == entity_key)
        .filter(AIAttackTechniqueHit.prediction_type == prediction_type)
        .filter(AIAttackTechniqueHit.window_end <= end)
        .order_by(AIAttackTechniqueHit.window_end.desc(), AIAttackTechniqueHit.confidence.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "technique_id": row.technique_id,
            "tactic": row.tactic,
            "confidence": float(row.confidence or 0.0),
            "source": dict(row.source_json or {}),
            "created_at": row.created_at.isoformat(),
        }
        for row in rows
    ]


def _campaigns_for_entity(
    db: Session,
    *,
    entity_key: str,
    start: datetime,
    end: datetime,
    limit: int = 10,
) -> list[dict[str, Any]]:
    rows = (
        db.query(Campaign, CampaignEntity)
        .join(CampaignEntity, CampaignEntity.campaign_id == Campaign.id)
        .filter(CampaignEntity.entity_key == entity_key)
        .filter(Campaign.last_seen >= start)
        .filter(Campaign.last_seen <= end)
        .order_by(Campaign.last_seen.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "campaign_id": str(campaign.id),
            "type": campaign.type,
            "status": campaign.status,
            "score": float(campaign.score or 0.0),
            "first_seen": campaign.first_seen.isoformat(),
            "last_seen": campaign.last_seen.isoformat(),
            "role": entity.role,
        }
        for campaign, entity in rows
    ]


def _timing_summary(db: Session, *, start: datetime, end: datetime) -> dict[str, Any]:
    rows = db.execute(
        text(
            """
            SELECT
                EXTRACT(DOW FROM occurred_at AT TIME ZONE 'UTC')::int AS dow,
                EXTRACT(HOUR FROM occurred_at AT TIME ZONE 'UTC')::int AS hour,
                COUNT(*)::int AS n
            FROM event_log
            WHERE occurred_at >= :start
              AND occurred_at <= :end
              AND event_type = ANY(:event_types)
            GROUP BY 1, 2
            ORDER BY n DESC
            LIMIT 10
            """
        ),
        {"start": start, "end": end, "event_types": list(SUSPICIOUS_EVENT_TYPES)},
    ).fetchall()
    if not rows:
        return {"peak_day": None, "peak_hour": None, "samples": 0}
    dow_names = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
    top = rows[0]
    return {
        "peak_day": dow_names[int(top[0]) % 7],
        "peak_hour": int(top[1]),
        "samples": int(sum(int(r[2]) for r in rows)),
    }


def _top_event_types(db: Session, *, start: datetime, end: datetime, limit: int = 8) -> list[dict[str, Any]]:
    rows = db.execute(
        text(
            """
            SELECT event_type, COUNT(*)::int AS n
            FROM event_log
            WHERE occurred_at >= :start AND occurred_at <= :end
            GROUP BY event_type
            ORDER BY n DESC
            LIMIT :limit
            """
        ),
        {"start": start, "end": end, "limit": limit},
    ).fetchall()
    return [{"event_type": str(r[0]), "count": int(r[1] or 0)} for r in rows]


def _top_predictions(db: Session, *, prediction_type: str, start: datetime, end: datetime, limit: int = 5) -> list[dict[str, Any]]:
    rows = (
        db.query(AIPrediction)
        .filter(AIPrediction.prediction_type == prediction_type)
        .filter(AIPrediction.window_end >= start)
        .filter(AIPrediction.window_end <= end)
        .order_by(AIPrediction.score.desc(), AIPrediction.window_end.desc())
        .limit(limit)
        .all()
    )
    return [_serialize_prediction(row) for row in rows if row is not None]


def _latest_campaigns(db: Session, *, start: datetime, end: datetime, limit: int = 5) -> list[dict[str, Any]]:
    rows = (
        db.query(Campaign)
        .filter(Campaign.last_seen >= start)
        .filter(Campaign.last_seen <= end)
        .order_by(Campaign.score.desc(), Campaign.last_seen.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "campaign_id": str(row.id),
            "type": row.type,
            "status": row.status,
            "score": float(row.score or 0.0),
            "event_count": int(row.event_count or 0),
            "last_seen": row.last_seen.isoformat(),
        }
        for row in rows
    ]


def _forecast_for_period(db: Session, *, period_days: int, horizon: int = 7) -> dict[str, Any]:
    rows = db.execute(
        text(
            """
            SELECT
                date_trunc('day', window_end AT TIME ZONE 'UTC')::date AS day,
                AVG(score) AS avg_score,
                MAX(score) AS max_score,
                COUNT(*) AS n
            FROM ai_prediction
            WHERE prediction_type = 'risk_gnn'
              AND window_end >= NOW() - INTERVAL '1 day' * :days
            GROUP BY 1
            ORDER BY 1
            """
        ),
        {"days": period_days},
    ).fetchall()
    history = [
        {
            "date": str(r[0]),
            "avg_score": round(float(r[1] or 0.0), 2),
            "max_score": round(float(r[2] or 0.0), 2),
            "n": int(r[3] or 0),
        }
        for r in rows
    ]
    return build_risk_forecast(history=history, horizon=horizon, alpha=0.3, beta=0.1)


def _governance_from_run(run: GNNTrainingRun | None) -> dict[str, Any]:
    if run is None:
        return {
            "model_version": None,
            "status": "unavailable",
            "note": "No training run is available for this report.",
        }
    metrics = dict(run.metrics_json or {})
    return {
        "model_version": run.model_version,
        "prediction_type": run.prediction_type,
        "window_key": run.window_key,
        "window_end": run.window_end.isoformat(),
        "node_count": run.node_count,
        "edge_count": run.edge_count,
        "positive_count": run.positive_count,
        "auc": float(run.auc or 0.0) if run.auc is not None else None,
        "precision": float(run.precision or 0.0) if run.precision is not None else None,
        "recall": float(run.recall or 0.0) if run.recall is not None else None,
        "f1": float(run.f1 or 0.0) if run.f1 is not None else None,
        "fairness": dict(metrics.get("fairness") or {}),
        "provenance": dict(metrics.get("provenance") or {}),
        "feedback": dict(metrics.get("feedback") or {}),
        "real_data_gate": dict(metrics.get("real_data_gate") or {}),
        "label_strategy": dict(metrics.get("label_strategy") or {}),
        "evaluation_protocol": dict(metrics.get("evaluation_protocol") or {}),
        "explainability": dict(metrics.get("explainability") or {}),
    }


def _base_report(
    *,
    report_type: str,
    title: str,
    audience: Sequence[str],
    classification: str,
    period: Mapping[str, Any],
    subject: Mapping[str, Any],
) -> dict[str, Any]:
    report_id = str(uuid.uuid4())
    return {
        "report_id": report_id,
        "report_type": report_type,
        "title": title,
        "generated_at": _now().isoformat(),
        "classification": classification,
        "audience": list(audience),
        "period": {
            "id": period["id"],
            "label": period["label"],
            "start": period["start"].isoformat(),
            "end": period["end"].isoformat(),
            "lookback_hours": period["lookback_hours"],
            "lookback_days": period["lookback_days"],
        },
        "subject": dict(subject),
        "summary": {},
        "findings": [],
        "explainability": {},
        "recommended_actions": [],
        "governance": {},
        "evidence_appendix": {},
        "limitations": _plain_limitations(),
    }


def _build_incident_brief(db: Session, payload: ReportRequest, period: Mapping[str, Any]) -> dict[str, Any]:
    top_events = _top_event_types(db, start=period["start"], end=period["end"])
    top_predictions = _top_predictions(
        db,
        prediction_type=payload.prediction_type,
        start=period["start"],
        end=period["end"],
    )
    top_campaigns = _latest_campaigns(db, start=period["start"], end=period["end"])
    timing = _timing_summary(db, start=period["start"], end=period["end"])
    forecast = _forecast_for_period(db, period_days=max(14, int(period["lookback_days"]) or 1))
    latest_run = _latest_gnn_run(db, prediction_type=payload.prediction_type)

    event_headline = "No material activity recorded"
    if top_events:
        event_headline = f"{_humanize_code(top_events[0]['event_type'])} was the most common signal in this window"
    top_score = float((top_predictions[0] or {}).get("score") or 0.0) if top_predictions else 0.0
    top_entity = str((top_predictions[0] or {}).get("entity_key") or "none") if top_predictions else "none"

    report = _base_report(
        report_type="incident_brief",
        title=f"{period['label']} Incident Brief",
        audience=["soc", "section_commander", "agency_lead"],
        classification=payload.classification,
        period=period,
        subject={"scope": "national", "prediction_type": payload.prediction_type},
    )
    report["summary"] = {
        "headline": event_headline,
        "overview": (
            f"This {period['label'].lower()} brief summarizes the most significant cyber signals, "
            f"active campaign activity, and AI risk posture observed between "
            f"{period['start'].isoformat()} and {period['end'].isoformat()}."
        ),
        "why_it_matters": (
            f"The highest scored entity in this window was {top_entity} at {top_score:.2f}. "
            f"{len(top_campaigns)} campaigns remained visible during the same period."
        ),
        "next_step": (
            "Review the top flagged entities, confirm whether the leading signal reflects an active incident, "
            "and escalate containment only after analyst verification."
        ),
        "confidence_statement": (
            "This is a blended operational brief derived from event volumes, campaign linkage, and AI risk scores."
        ),
    }
    report["findings"] = [
        {
            "title": "Top event pattern",
            "severity": "info",
            "plain_text": (
                f"The most common signal type was {_humanize_code(top_events[0]['event_type'])} "
                f"with {top_events[0]['count']} records."
                if top_events else
                "No event activity was recorded for this period."
            ),
        },
        {
            "title": "Highest scored entity",
            "severity": _risk_label(top_score),
            "plain_text": (
                f"The highest current AI risk score was {top_score:.2f} for {top_entity}."
                if top_predictions else
                "No AI predictions were recorded in this period."
            ),
        },
        {
            "title": "Peak timing",
            "severity": "info",
            "plain_text": (
                f"Suspicious activity peaked on {timing['peak_day']} around {timing['peak_hour']:02d}:00 UTC."
                if timing["samples"] else
                "There was not enough suspicious-event timing data to identify a peak pattern."
            ),
        },
        {
            "title": "Forward posture",
            "severity": _risk_label(float((forecast.get("alert_recommendation") or {}).get("peak_forecast_score") or 0.0)),
            "plain_text": (
                f"Forecast trend is {forecast.get('trend_direction', 'unknown')} with a recommended posture of "
                f"{((forecast.get('alert_recommendation') or {}).get('level') or 'unknown')}."
                if forecast.get("status") != "insufficient_data" else
                "There is not enough daily risk history to produce a forecast for this brief."
            ),
        },
    ]
    report["explainability"] = {
        "plain_language": (
            "This brief aggregates many individual AI entity scores. It is intended to guide attention, "
            "not to serve as proof of one specific actor or event."
        ),
        "method_summary": (
            "Risk posture is derived from graph-based AI predictions, recent event evidence, and campaign linkage."
        ),
    }
    report["recommended_actions"] = [
        "Review the top 5 scored entities and validate whether they map to active operational risk.",
        "Cross-check the leading signal type against recent campaigns before escalating to national response.",
        "Preserve event and prediction evidence for any entity escalated beyond analyst review.",
    ]
    report["governance"] = _governance_from_run(latest_run)
    report["evidence_appendix"] = {
        "top_event_types": top_events,
        "top_predictions": top_predictions,
        "top_campaigns": top_campaigns,
        "timing": timing,
        "forecast": forecast,
    }
    return report


def _build_entity_investigation(db: Session, payload: ReportRequest, period: Mapping[str, Any]) -> dict[str, Any]:
    prediction = _latest_prediction_for_entity(
        db,
        entity_key=str(payload.entity_key),
        prediction_type=payload.prediction_type,
        end=period["end"],
    )
    explanation = _latest_explanation(db, prediction.id) if prediction else None
    path_score = _latest_path_score(
        db,
        entity_key=str(payload.entity_key),
        prediction_type=payload.prediction_type,
        end=period["end"],
    )
    fusion = _latest_fusion(
        db,
        entity_key=str(payload.entity_key),
        prediction_type=payload.prediction_type,
        end=period["end"],
    )
    recent_events = _recent_events_for_entity(
        db,
        entity_key=str(payload.entity_key),
        start=period["start"],
        end=period["end"],
    )
    techniques = _latest_techniques(
        db,
        entity_key=str(payload.entity_key),
        prediction_type=payload.prediction_type,
        end=period["end"],
    )
    tools = techniques_to_tools([str(item["technique_id"]) for item in techniques])
    containment = _latest_containment(db, str(payload.entity_key))
    campaigns = _campaigns_for_entity(
        db,
        entity_key=str(payload.entity_key),
        start=period["start"],
        end=period["end"],
    )
    latest_run = _latest_gnn_run(
        db,
        prediction_type=payload.prediction_type,
        model_version=prediction.model_version if prediction else payload.model_version,
    )
    trust_summary = (
        build_entity_trust_summary(
            db,
            entity_key=str(payload.entity_key),
            prediction_type=payload.prediction_type,
        )
        if prediction else None
    )
    trust_brief = dict((trust_summary or {}).get("operator_brief") or {})

    report = _base_report(
        report_type="entity_investigation",
        title=f"Entity Investigation Report — {payload.entity_key}",
        audience=["analyst", "dfir", "investigator"],
        classification=payload.classification,
        period=period,
        subject={"entity_key": payload.entity_key, "prediction_type": payload.prediction_type},
    )

    if not prediction:
        report["summary"] = {
            "headline": f"No AI prediction is currently available for {payload.entity_key}",
            "overview": "This entity can still be reviewed using raw events, but there is no model output to explain.",
            "why_it_matters": "Lack of a prediction may mean the entity is new, outside the active window, or absent from feature snapshots.",
            "next_step": "Verify the entity key, inspect its events directly, and refresh feature generation if needed.",
            "confidence_statement": "No model decision exists for this entity in the selected period.",
        }
        report["findings"] = [
            {
                "title": "Event coverage",
                "severity": "info",
                "plain_text": f"{len(recent_events)} recent events were found for this entity in the selected window.",
            }
        ]
        report["evidence_appendix"] = {"recent_events": recent_events}
        report["governance"] = _governance_from_run(latest_run)
        return report

    reason_codes = list((prediction.reason_codes or [])[:5])
    controls = list((explanation.recommended_controls_json if explanation else []) or [])
    report["summary"] = {
        "headline": trust_brief.get("headline") or (
            f"{payload.entity_key} is currently assessed as {_risk_label(float(prediction.score or 0.0))} risk."
        ),
        "overview": (
            f"The latest model score for this entity is {float(prediction.score or 0.0):.2f}. "
            f"The entity is in kill-chain stage '{prediction.kill_chain_stage or 'unknown'}'."
        ),
        "why_it_matters": " ".join(str(item) for item in (trust_brief.get("why_it_matters") or [])) or (
            f"This entity is linked to {len(campaigns)} campaign records, {len(recent_events)} recent events, "
            f"and {len((explanation.evidence_hashes if explanation else []) or [])} evidence hashes."
        ),
        "next_step": (
            str((trust_brief.get("next_actions") or [])[0])
            if (trust_brief.get("next_actions") or [])
            else "Review the evidence paths and event history, then decide whether analyst confirmation justifies containment."
        ),
        "confidence_statement": _confidence_statement(prediction.confidence, prediction.uncertainty),
    }
    report["findings"] = [
        {
            "title": "Primary reasons",
            "severity": _risk_label(float(prediction.score or 0.0)),
            "plain_text": (
                f"Top reasons recorded for this entity were: {', '.join(_humanize_code(x) for x in reason_codes)}."
                if reason_codes else
                "No explicit reason codes were recorded."
            ),
        },
        {
            "title": "Graph proximity",
            "severity": "info",
            "plain_text": (
                f"Path score is {float(path_score.path_score or 0.0):.2f} across {int(path_score.hop_count or 0)} hops."
                if path_score else
                "No attack-path score is recorded yet for this entity."
            ),
        },
        {
            "title": "Decision fusion",
            "severity": "info",
            "plain_text": (
                f"Fused decision score is {float(fusion.fused_score or 0.0):.2f} with decision '{fusion.decision}'."
                if fusion else
                "No decision-fusion record is available yet."
            ),
        },
        {
            "title": "Containment status",
            "severity": "info",
            "plain_text": (
                f"Latest containment action is {containment.action_type} with status {containment.status}."
                if containment else
                "No executed containment action is recorded for this entity."
            ),
        },
    ]
    report["explainability"] = {
        "plain_language": (
            "The AI score increased because this entity is connected to suspicious activity, not because of one isolated event."
        ),
        "trust_brief": trust_brief,
        "reason_codes": reason_codes,
        "evidence_hash_count": len(list((explanation.evidence_hashes if explanation else []) or [])),
        "evidence_path_count": len(list((explanation.evidence_paths if explanation else []) or [])),
        "counterfactual": dict((explanation.counterfactual_json if explanation else {}) or {}),
        "recommended_controls": controls,
        "tools": tools,
        "techniques": techniques,
    }
    report["recommended_actions"] = controls or [
        "Validate the linked events before escalating the entity.",
        "Preserve the evidence hashes and graph paths for review.",
        "Escalate to containment only if the entity is operationally confirmed as hostile.",
    ]
    report["governance"] = {
        **_governance_from_run(latest_run),
        "trust_checks": list((trust_summary or {}).get("trust_checks") or []),
        "evidence_summary": dict((trust_summary or {}).get("evidence_summary") or {}),
    }
    report["evidence_appendix"] = {
        "prediction": _serialize_prediction(prediction),
        "explanation": _serialize_explanation(explanation),
        "recent_events": recent_events,
        "path_score": _serialize_path(path_score),
        "fusion": _serialize_fusion(fusion),
        "campaign_links": campaigns,
        "tools": tools,
    }
    return report


def _build_campaign_case(db: Session, payload: ReportRequest, period: Mapping[str, Any]) -> dict[str, Any]:
    campaign = db.query(Campaign).filter(Campaign.id == payload.campaign_id).first()
    if not campaign:
        raise ValueError("campaign_not_found")

    packet: dict[str, Any] | None = None
    packet_error: str | None = None
    try:
        packet = build_case_packet(campaign_id=campaign.id, db=db)
    except Exception as exc:  # noqa: BLE001
        packet_error = str(exc)

    entities = (
        db.query(CampaignEntity)
        .filter(CampaignEntity.campaign_id == campaign.id)
        .order_by(CampaignEntity.last_seen.desc())
        .all()
    )
    events = (
        db.query(CampaignEvent)
        .filter(CampaignEvent.campaign_id == campaign.id)
        .order_by(CampaignEvent.occurred_at.desc())
        .limit(50)
        .all()
    )
    indicator = (
        db.query(AICampaignRiskIndicator)
        .filter(AICampaignRiskIndicator.campaign_id == campaign.id)
        .order_by(AICampaignRiskIndicator.window_end.desc())
        .first()
    )
    latest_bundle = (
        db.query(LegalEvidenceBundle)
        .filter(LegalEvidenceBundle.campaign_id == str(campaign.id))
        .order_by(LegalEvidenceBundle.created_at.desc())
        .first()
    )
    trust_summary = build_campaign_trust_summary(db, campaign_id=str(campaign.id))
    trust_brief = dict(trust_summary.get("operator_brief") or {})

    report = _base_report(
        report_type="campaign_case",
        title=f"Campaign Case Report — {campaign.type}",
        audience=["investigator", "supervisor", "inter-agency"],
        classification=payload.classification,
        period=period,
        subject={"campaign_id": str(campaign.id), "campaign_type": campaign.type},
    )
    report["summary"] = {
        "headline": trust_brief.get("headline") or f"Campaign {campaign.type} remains {campaign.status} with score {float(campaign.score or 0.0):.2f}.",
        "overview": (
            f"The campaign has {int(campaign.event_count or 0)} linked events and {len(entities)} linked entities."
        ),
        "why_it_matters": " ".join(str(item) for item in (trust_brief.get("why_it_matters") or [])) or (
            "Campaign-level reporting is useful when many entities appear related and the response must be coordinated."
        ),
        "next_step": (
            str((trust_brief.get("next_actions") or [])[0])
            if (trust_brief.get("next_actions") or [])
            else "Use this report to coordinate investigation, preserve evidence, and determine whether a legal bundle should be finalized."
        ),
        "confidence_statement": (
            f"Latest campaign AI risk indicator is {float(indicator.score or 0.0):.2f}."
            if indicator else
            "No campaign-level AI indicator is currently recorded."
        ),
    }
    report["findings"] = [
        {
            "title": "Entity spread",
            "severity": _risk_label(float(campaign.score or 0.0)),
            "plain_text": f"The campaign currently links {len(entities)} entities across {int(campaign.event_count or 0)} events.",
        },
        {
            "title": "Latest AI campaign indicator",
            "severity": _risk_label(float(indicator.score or 0.0)) if indicator else "info",
            "plain_text": (
                f"Latest campaign indicator score is {float(indicator.score or 0.0):.2f} "
                f"with {int(indicator.flagged_entity_count or 0)} flagged entities."
                if indicator else
                "No AI campaign indicator is available yet."
            ),
        },
        {
            "title": "Legal packaging readiness",
            "severity": "info",
            "plain_text": (
                f"A legal evidence bundle already exists for this campaign: {latest_bundle.bundle_id}."
                if latest_bundle else
                "No legal evidence bundle is currently stored for this campaign."
            ),
        },
    ]
    report["explainability"] = {
        "plain_language": (
            "This campaign report explains how multiple entities and events form one connected pattern, not isolated alerts."
        ),
        "trust_brief": trust_brief,
        "network_summary": {
            "entity_count": len(entities),
            "event_count": len(events),
            "primary_key": campaign.primary_key,
        },
    }
    report["recommended_actions"] = [
        "Validate the highest-risk entities inside the campaign before operational escalation.",
        "Preserve linked events and graph relationships as campaign evidence.",
        "Generate or refresh the legal bundle if this campaign is moving toward enforcement or prosecution.",
    ]
    report["governance"] = {
        "rule_version": campaign.rule_version,
        "latest_bundle_id": latest_bundle.bundle_id if latest_bundle else None,
        "case_packet_integrity_available": bool(packet and packet.get("integrity")),
        "case_packet_generation_error": packet_error,
        "trust_checks": list(trust_summary.get("trust_checks") or []),
        "evidence_summary": dict(trust_summary.get("evidence_summary") or {}),
    }
    report["evidence_appendix"] = {
        "campaign": {
            "campaign_id": str(campaign.id),
            "type": campaign.type,
            "status": campaign.status,
            "score": float(campaign.score or 0.0),
            "first_seen": campaign.first_seen.isoformat(),
            "last_seen": campaign.last_seen.isoformat(),
            "stats": dict(campaign.stats or {}),
        },
        "entities": [
            {
                "entity_key": row.entity_key,
                "entity_type": row.entity_type,
                "role": row.role,
                "last_seen": row.last_seen.isoformat(),
            }
            for row in entities
        ],
        "events": [{"event_hash": row.event_hash, "occurred_at": row.occurred_at.isoformat()} for row in events],
        "risk_indicator": None if indicator is None else {
            "score": float(indicator.score or 0.0),
            "severity": indicator.severity,
            "flagged_entity_count": int(indicator.flagged_entity_count or 0),
            "total_entity_count": int(indicator.total_entity_count or 0),
            "reason_codes": list(indicator.reason_codes or []),
            "evidence_entity_keys": list(indicator.evidence_entity_keys or []),
            "details": dict(indicator.details_json or {}),
        },
        "case_packet": packet,
    }
    return report


def _build_legal_bundle(db: Session, payload: ReportRequest, period: Mapping[str, Any]) -> dict[str, Any]:
    q = db.query(LegalEvidenceBundle)
    if payload.bundle_id:
        q = q.filter(LegalEvidenceBundle.bundle_id == payload.bundle_id)
    elif payload.campaign_id:
        q = q.filter(LegalEvidenceBundle.campaign_id == payload.campaign_id)
    bundle = q.order_by(LegalEvidenceBundle.created_at.desc()).first()
    if not bundle:
        raise ValueError("legal_evidence_bundle_not_found")

    order = db.query(LegalOrder).filter(LegalOrder.order_id == bundle.order_id).first()
    grants = (
        db.query(LegalAuthorizationGrant)
        .filter(LegalAuthorizationGrant.order_id == bundle.order_id)
        .order_by(LegalAuthorizationGrant.created_at.asc())
        .all()
    )
    anchor = db.query(LegalEvidenceAnchor).filter(LegalEvidenceAnchor.bundle_id == bundle.bundle_id).first()
    certificate = (
        db.query(LegalEvidenceCertificate)
        .filter(LegalEvidenceCertificate.bundle_id == bundle.bundle_id)
        .first()
    )
    audit_rows = (
        db.query(AuditLog)
        .filter(AuditLog.target.in_([bundle.bundle_id, bundle.order_id]))
        .order_by(AuditLog.at.asc())
        .limit(200)
        .all()
    )
    bundle_data = _serialize_bundle(bundle, order=order, grants=grants, anchor=anchor, certificate=certificate)

    report = _base_report(
        report_type="legal_evidence_bundle",
        title=f"Legal Evidence Bundle Report — {bundle.bundle_id}",
        audience=["legal", "audit", "court_support"],
        classification=payload.classification,
        period=period,
        subject={"bundle_id": bundle.bundle_id, "campaign_id": bundle.campaign_id},
    )
    anchor_status = (bundle_data.get("anchor") or {}).get("anchor_status")
    report["summary"] = {
        "headline": f"Evidence bundle {bundle.bundle_id} preserves the case chain for campaign {bundle.campaign_id}.",
        "overview": (
            f"The bundle is linked to order {bundle.order_id} and contains a cryptographic root hash and chain hash."
        ),
        "why_it_matters": (
            "This report documents chain of custody, legal scope, and anchoring status so evidence handling can be audited."
        ),
        "next_step": (
            "Verify the anchor status, certificate metadata, and grant scope before external sharing or court submission."
        ),
        "confidence_statement": (
            f"Current anchor status is {anchor_status or 'not available'}."
        ),
    }
    report["findings"] = [
        {
            "title": "Legal scope",
            "severity": "info",
            "plain_text": (
                f"The bundle is associated with court order {order.order_number} from {order.court_name}."
                if order else
                "No linked legal order record was found."
            ),
        },
        {
            "title": "Grant chain",
            "severity": "info",
            "plain_text": f"{len(grants)} authorization grants are linked to this order.",
        },
        {
            "title": "Anchor status",
            "severity": "high" if anchor_status in {"failed", "stub"} else "info",
            "plain_text": (
                f"Anchor backend status is {anchor_status}."
                if anchor_status else
                "No anchor record exists for this bundle."
            ),
        },
    ]
    report["explainability"] = {
        "plain_language": (
            "This is not a model explanation report. It explains evidence custody, legal scope, and integrity protections."
        ),
        "integrity_chain": {
            "root_hash": bundle.root_hash,
            "prev_chain_hash": bundle.prev_chain_hash,
            "chain_hash": bundle.chain_hash,
        },
    }
    report["recommended_actions"] = [
        "Confirm that the order scope covers the target entities and actions.",
        "Refresh or verify the anchor if the current status is stub or failed.",
        "Retain the certificate and audit chain alongside any exported copy.",
    ]
    report["governance"] = {
        "framework": (bundle_data.get("certificate") or {}).get("framework"),
        "jurisdiction": (bundle_data.get("certificate") or {}).get("jurisdiction"),
        "anchor_status": anchor_status,
        "created_by": bundle.created_by,
    }
    report["evidence_appendix"] = {
        "bundle": bundle_data,
        "audit_chain": [
            {
                "actor_type": row.actor_type,
                "actor_id": row.actor_id,
                "action": row.action,
                "target": row.target,
                "at": row.at.isoformat(),
            }
            for row in audit_rows
        ],
    }
    return report


def _build_ai_decision_explanation(db: Session, payload: ReportRequest, period: Mapping[str, Any]) -> dict[str, Any]:
    prediction = (
        _latest_prediction_by_id(db, payload.prediction_id)
        if payload.prediction_id
        else _latest_prediction_for_entity(
            db,
            entity_key=str(payload.entity_key),
            prediction_type=payload.prediction_type,
            end=period["end"],
        )
    )
    if not prediction:
        raise ValueError("prediction_not_found")
    explanation = _latest_explanation(db, prediction.id)
    latest_run = _latest_gnn_run(
        db,
        prediction_type=prediction.prediction_type,
        model_version=prediction.model_version,
    )
    techniques = _latest_techniques(
        db,
        entity_key=prediction.entity_key,
        prediction_type=prediction.prediction_type,
        end=prediction.window_end,
    )
    tools = techniques_to_tools([str(item["technique_id"]) for item in techniques])
    path_score = _latest_path_score(
        db,
        entity_key=prediction.entity_key,
        prediction_type=prediction.prediction_type,
        end=prediction.window_end,
    )
    fusion = _latest_fusion(
        db,
        entity_key=prediction.entity_key,
        prediction_type=prediction.prediction_type,
        end=prediction.window_end,
    )

    report = _base_report(
        report_type="ai_decision_explanation",
        title=f"AI Decision Explanation — {prediction.entity_key}",
        audience=["oversight", "analyst", "non_technical_reviewer"],
        classification=payload.classification,
        period=period,
        subject={
            "prediction_id": str(prediction.id),
            "entity_key": prediction.entity_key,
            "model_version": prediction.model_version,
        },
    )
    report["summary"] = {
        "headline": (
            f"The AI assigned {prediction.entity_key} a score of {float(prediction.score or 0.0):.2f} "
            f"({prediction.kill_chain_stage or 'unknown stage'})."
        ),
        "overview": (
            "This report explains the decision in plain language and lists the evidence that contributed to it."
        ),
        "why_it_matters": (
            "The purpose is to help a human reviewer understand whether the AI decision is reasonable and auditable."
        ),
        "next_step": (
            "Review the recorded reasons, graph paths, and suggested controls before treating this output as operationally significant."
        ),
        "confidence_statement": _confidence_statement(prediction.confidence, prediction.uncertainty),
    }
    reason_codes = list((explanation.reason_codes if explanation else []) or prediction.reason_codes or [])
    report["findings"] = [
        {
            "title": "Reason codes",
            "severity": _risk_label(float(prediction.score or 0.0)),
            "plain_text": (
                f"The main reasons recorded were: {', '.join(_humanize_code(x) for x in reason_codes[:5])}."
                if reason_codes else
                "No explicit reason codes were captured."
            ),
        },
        {
            "title": "Evidence support",
            "severity": "info",
            "plain_text": (
                f"The explanation contains {len(list((explanation.evidence_hashes if explanation else []) or []))} "
                f"evidence hashes and {len(list((explanation.evidence_paths if explanation else []) or []))} graph paths."
            ),
        },
        {
            "title": "Counterfactual",
            "severity": "info",
            "plain_text": (
                "A counterfactual explanation is available describing what probability shift would change the decision."
                if explanation and explanation.counterfactual_json else
                "No counterfactual explanation was recorded for this decision."
            ),
        },
    ]
    report["explainability"] = {
        "plain_language": (
            "The model did not flag this entity because of one single field. It combined event history, graph relationships, "
            "and learned patterns from similar cases."
        ),
        "reason_codes": reason_codes,
        "recommended_controls": list((explanation.recommended_controls_json if explanation else []) or []),
        "counterfactual": dict((explanation.counterfactual_json if explanation else {}) or {}),
        "tools": tools,
        "techniques": techniques,
        "path_score": _serialize_path(path_score),
        "fusion": _serialize_fusion(fusion),
    }
    report["recommended_actions"] = list((explanation.recommended_controls_json if explanation else []) or []) or [
        "Validate the supporting evidence before acting on the score.",
        "Check whether the entity appears in other campaign or path analyses.",
        "Use human review to confirm whether escalation is justified.",
    ]
    report["governance"] = _governance_from_run(latest_run)
    report["evidence_appendix"] = {
        "prediction": _serialize_prediction(prediction),
        "explanation": _serialize_explanation(explanation),
        "tools": tools,
        "techniques": techniques,
    }
    return report


def _build_model_governance(db: Session, payload: ReportRequest, period: Mapping[str, Any]) -> dict[str, Any]:
    q = db.query(GNNTrainingRun).filter(GNNTrainingRun.prediction_type == payload.prediction_type)
    if payload.model_version:
        q = q.filter(GNNTrainingRun.model_version == payload.model_version)
    q = q.filter(GNNTrainingRun.created_at >= period["start"]).filter(GNNTrainingRun.created_at <= period["end"])
    runs = q.order_by(GNNTrainingRun.created_at.desc()).limit(10).all()
    if not runs:
        fallback = _latest_gnn_run(db, prediction_type=payload.prediction_type, model_version=payload.model_version)
        runs = [fallback] if fallback else []

    latest_run = runs[0] if runs else None
    drift_rows = []
    rollout = None
    lineage = None
    if latest_run:
        drift_rows = (
            db.query(AIDriftReport)
            .filter(AIDriftReport.prediction_type == latest_run.prediction_type)
            .filter(AIDriftReport.model_version == latest_run.model_version)
            .order_by(AIDriftReport.created_at.desc())
            .limit(10)
            .all()
        )
        rollout = (
            db.query(AIModelRollout)
            .filter(AIModelRollout.prediction_type == latest_run.prediction_type)
            .order_by(AIModelRollout.updated_at.desc())
            .first()
        )
        lineage = (
            db.query(AIModelLineage)
            .filter(AIModelLineage.prediction_type == latest_run.prediction_type)
            .filter(AIModelLineage.model_version == latest_run.model_version)
            .first()
        )

    report = _base_report(
        report_type="model_governance",
        title=f"Model Governance Report — {payload.prediction_type}",
        audience=["cto", "oversight", "judges", "procurement_review"],
        classification=payload.classification,
        period=period,
        subject={"prediction_type": payload.prediction_type, "model_version": latest_run.model_version if latest_run else payload.model_version},
    )
    if not latest_run:
        report["summary"] = {
            "headline": "No training run is available for the requested model scope.",
            "overview": "Governance reporting requires at least one recorded training run.",
            "why_it_matters": "Without a training run, there is no model lineage, fairness, or provenance record to review.",
            "next_step": "Run training first, then re-generate this governance report.",
            "confidence_statement": "Governance status unavailable.",
        }
        return report

    governance = _governance_from_run(latest_run)
    fairness = dict(governance.get("fairness") or {})
    provenance = dict(governance.get("provenance") or {})
    real_gate = dict(governance.get("real_data_gate") or {})
    latest_drift = drift_rows[0] if drift_rows else None

    report["summary"] = {
        "headline": f"Current active model version is {latest_run.model_version}.",
        "overview": (
            f"The latest recorded run for {latest_run.prediction_type} trained on {latest_run.node_count} nodes "
            f"and {latest_run.edge_count} edges."
        ),
        "why_it_matters": (
            "This report shows whether the model is trained on enough real data, whether fairness checks passed, "
            "and whether drift monitoring has detected instability."
        ),
        "next_step": (
            "Use this report before public performance claims, procurement review, or rollout changes."
        ),
        "confidence_statement": (
            f"Real-data gate passed: {bool(real_gate.get('passed', False))}. "
            f"Latest drift status: {latest_drift.status if latest_drift else 'unavailable'}."
        ),
    }
    report["findings"] = [
        {
            "title": "Training provenance",
            "severity": "info",
            "plain_text": (
                f"Latest run used source backend {latest_run.source_backend} with real-signal ratio "
                f"{float(provenance.get('real_ratio') or 0.0):.3f} and "
                f"{int(((governance.get('feedback') or {}).get('override_count') or 0))} analyst feedback overrides."
            ),
        },
        {
            "title": "Fairness status",
            "severity": "high" if fairness.get("fairness_flag") == "FAIL" else "info",
            "plain_text": (
                f"Maximum positive-rate disparity is {float(fairness.get('max_positive_rate_disparity') or 0.0):.3f}."
            ),
        },
        {
            "title": "Metric caveat",
            "severity": "info",
            "plain_text": (
                str((governance.get("label_strategy") or {}).get("eval_caveat") or
                    "No metric caveat was recorded.")
            ),
        },
        {
            "title": "Drift status",
            "severity": "high" if latest_drift and latest_drift.status not in {"ok", "stable"} else "info",
            "plain_text": (
                f"Latest drift report status is {latest_drift.status} with score {float(latest_drift.drift_score or 0.0):.3f}."
                if latest_drift else
                "No drift report is recorded for this model."
            ),
        },
    ]
    report["explainability"] = {
        "plain_language": (
            "This report does not explain one incident. It explains how the model was trained, monitored, and governed."
        ),
        "method_summary": dict(governance.get("explainability") or {}),
        "label_strategy": dict(governance.get("label_strategy") or {}),
    }
    report["recommended_actions"] = [
        "Do not make external accuracy claims without acknowledging the recorded metric caveats.",
        "Increase real-data coverage if the real-data gate is close to threshold.",
        "Review fairness and drift reports before activating a new rollout mode.",
    ]
    report["governance"] = governance
    report["evidence_appendix"] = {
        "recent_runs": [
            {
                "model_version": row.model_version,
                "created_at": row.created_at.isoformat(),
                "node_count": row.node_count,
                "edge_count": row.edge_count,
                "auc": float(row.auc or 0.0) if row.auc is not None else None,
                "metrics": dict(row.metrics_json or {}),
            }
            for row in runs
        ],
        "drift_reports": [
            {
                "model_version": row.model_version,
                "window_end": row.window_end.isoformat(),
                "drift_score": float(row.drift_score or 0.0),
                "status": row.status,
                "metrics": dict(row.metrics_json or {}),
                "created_at": row.created_at.isoformat(),
            }
            for row in drift_rows
        ],
        "rollout": None if rollout is None else {
            "rollout_id": rollout.rollout_id,
            "active_model_version": rollout.active_model_version,
            "shadow_model_version": rollout.shadow_model_version,
            "rollout_mode": rollout.rollout_mode,
            "canary_ratio": float(rollout.canary_ratio or 0.0),
            "auto_rollback": bool(rollout.auto_rollback),
            "status": rollout.status,
            "metadata": dict(rollout.metadata_json or {}),
            "updated_at": rollout.updated_at.isoformat(),
        },
        "lineage": None if lineage is None else {
            "lineage_id": lineage.lineage_id,
            "dataset_hash": lineage.dataset_hash,
            "params_hash": lineage.params_hash,
            "code_hash": lineage.code_hash,
            "lineage_signature": lineage.lineage_signature,
            "metadata": dict(lineage.metadata_json or {}),
            "created_at": lineage.created_at.isoformat(),
        },
    }
    return report


def build_report(*, db: Session, payload: ReportRequest) -> dict[str, Any]:
    period = _period_context(payload.period)
    if payload.report_type == "incident_brief":
        report = _build_incident_brief(db, payload, period)
    elif payload.report_type == "entity_investigation":
        report = _build_entity_investigation(db, payload, period)
    elif payload.report_type == "campaign_case":
        report = _build_campaign_case(db, payload, period)
    elif payload.report_type == "legal_evidence_bundle":
        report = _build_legal_bundle(db, payload, period)
    elif payload.report_type == "ai_decision_explanation":
        report = _build_ai_decision_explanation(db, payload, period)
    elif payload.report_type == "model_governance":
        report = _build_model_governance(db, payload, period)
    else:
        raise ValueError("unsupported_report_type")

    report["download"] = {
        "base_name": build_report_filename(report),
        "available_formats": ["json", "html", "pdf"],
    }
    return report


def build_report_filename(report: Mapping[str, Any]) -> str:
    report_type = _sanitize_slug(str(report.get("report_type") or "report"))
    subject = dict(report.get("subject") or {})
    base_subject = (
        subject.get("entity_key")
        or subject.get("campaign_id")
        or subject.get("bundle_id")
        or subject.get("model_version")
        or subject.get("scope")
        or "report"
    )
    return f"sentinel-{report_type}-{_sanitize_slug(str(base_subject))}-{_sanitize_slug(str(report.get('report_id') or 'generated'))}"


def render_report_html(report: Mapping[str, Any]) -> str:
    def esc(value: Any) -> str:
        return html.escape("" if value is None else str(value))

    def list_items(values: Iterable[str]) -> str:
        items = "".join(f"<li>{esc(item)}</li>" for item in values)
        return f"<ul>{items}</ul>" if items else "<p class='muted'>None recorded.</p>"

    summary = dict(report.get("summary") or {})
    findings = list(report.get("findings") or [])
    explainability = dict(report.get("explainability") or {})
    actions = list(report.get("recommended_actions") or [])
    governance = dict(report.get("governance") or {})
    appendix = dict(report.get("evidence_appendix") or {})
    limitations = list(report.get("limitations") or [])
    period = dict(report.get("period") or {})
    subject = dict(report.get("subject") or {})

    findings_html = "".join(
        (
            "<div class='finding'>"
            f"<div class='finding-head'><span class='finding-title'>{esc(item.get('title'))}</span>"
            f"<span class='badge badge-{esc(item.get('severity') or 'info').lower()}'>{esc(item.get('severity') or 'info')}</span></div>"
            f"<p>{esc(item.get('plain_text'))}</p>"
            "</div>"
        )
        for item in findings
    ) or "<p class='muted'>No findings recorded.</p>"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{esc(report.get('title'))}</title>
  <style>
    :root {{
      --bg: #f3f4f6;
      --card: #ffffff;
      --line: #d1d5db;
      --ink: #111827;
      --muted: #4b5563;
      --accent: #0f766e;
      --critical: #b91c1c;
      --high: #c2410c;
      --medium: #b45309;
      --info: #1d4ed8;
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; background: var(--bg); color: var(--ink); font: 15px/1.55 Georgia, 'Times New Roman', serif; }}
    .page {{ max-width: 1040px; margin: 0 auto; padding: 28px; }}
    .hero {{ background: linear-gradient(135deg, #0f172a, #134e4a); color: white; border-radius: 18px; padding: 24px 28px; }}
    .hero h1 {{ margin: 0 0 8px; font-size: 28px; }}
    .meta {{ display: flex; flex-wrap: wrap; gap: 10px; margin-top: 12px; font-size: 13px; }}
    .pill {{ background: rgba(255,255,255,0.12); padding: 6px 10px; border-radius: 999px; }}
    .grid {{ display: grid; grid-template-columns: 1.2fr 0.8fr; gap: 18px; margin-top: 18px; }}
    .card {{ background: var(--card); border: 1px solid var(--line); border-radius: 14px; padding: 18px; box-shadow: 0 10px 30px rgba(15, 23, 42, 0.05); }}
    .section {{ margin-top: 18px; }}
    h2 {{ margin: 0 0 12px; font-size: 20px; }}
    h3 {{ margin: 0 0 10px; font-size: 16px; }}
    p {{ margin: 0 0 10px; }}
    .muted {{ color: var(--muted); }}
    .finding {{ border-top: 1px solid var(--line); padding-top: 12px; margin-top: 12px; }}
    .finding:first-child {{ border-top: 0; margin-top: 0; padding-top: 0; }}
    .finding-head {{ display: flex; justify-content: space-between; gap: 12px; align-items: center; }}
    .finding-title {{ font-weight: 700; }}
    .badge {{ display: inline-block; padding: 3px 8px; border-radius: 999px; font: 11px/1.2 sans-serif; text-transform: uppercase; color: white; }}
    .badge-critical {{ background: var(--critical); }}
    .badge-high {{ background: var(--high); }}
    .badge-medium {{ background: var(--medium); }}
    .badge-info, .badge-low {{ background: var(--info); }}
    ul {{ margin: 8px 0 0 18px; }}
    li {{ margin-bottom: 6px; }}
    pre {{ white-space: pre-wrap; word-break: break-word; background: #0f172a; color: #e5e7eb; padding: 14px; border-radius: 12px; overflow: auto; font: 12px/1.45 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }}
    .summary-strong {{ font-size: 20px; font-weight: 700; }}
    .footnote {{ font-size: 12px; color: var(--muted); margin-top: 18px; }}
    @media (max-width: 860px) {{
      .grid {{ grid-template-columns: 1fr; }}
      .page {{ padding: 16px; }}
    }}
  </style>
</head>
<body>
  <div class="page">
    <section class="hero">
      <h1>{esc(report.get("title"))}</h1>
      <p>{esc(summary.get("headline"))}</p>
      <div class="meta">
        <span class="pill">Classification: {esc(report.get("classification"))}</span>
        <span class="pill">Generated: {esc(report.get("generated_at"))}</span>
        <span class="pill">Period: {esc(period.get("label"))}</span>
        <span class="pill">Audience: {esc(", ".join(report.get("audience") or []))}</span>
      </div>
    </section>

    <div class="grid">
      <section class="card">
        <h2>Plain-English Summary</h2>
        <p class="summary-strong">{esc(summary.get("headline"))}</p>
        <p><strong>What is happening:</strong> {esc(summary.get("overview"))}</p>
        <p><strong>Why it matters:</strong> {esc(summary.get("why_it_matters"))}</p>
        <p><strong>What to do next:</strong> {esc(summary.get("next_step"))}</p>
        <p><strong>Confidence:</strong> {esc(summary.get("confidence_statement"))}</p>
      </section>
      <section class="card">
        <h2>Subject</h2>
        <pre>{esc(_short_json(subject))}</pre>
      </section>
    </div>

    <section class="card section">
      <h2>Key Findings</h2>
      {findings_html}
    </section>

    <section class="card section">
      <h2>Explainability</h2>
      <p>{esc(explainability.get("plain_language"))}</p>
      <pre>{esc(_short_json(explainability))}</pre>
    </section>

    <section class="card section">
      <h2>Recommended Actions</h2>
      {list_items(actions)}
    </section>

    <section class="card section">
      <h2>Governance and Caveats</h2>
      <pre>{esc(_short_json(governance))}</pre>
      <h3>Limitations</h3>
      {list_items(limitations)}
    </section>

    <section class="card section">
      <h2>Evidence Appendix</h2>
      <pre>{esc(_short_json(appendix))}</pre>
    </section>

    <p class="footnote">
      Sentinel-KE generated report. AI outputs support prioritization and review; they do not replace human judgment or legal process.
    </p>
  </div>
</body>
</html>"""


def render_report_pdf(report: Mapping[str, Any]) -> bytes:
    summary = dict(report.get("summary") or {})
    findings = list(report.get("findings") or [])
    explainability = dict(report.get("explainability") or {})
    actions = list(report.get("recommended_actions") or [])
    governance = dict(report.get("governance") or {})
    appendix = dict(report.get("evidence_appendix") or {})
    limitations = list(report.get("limitations") or [])
    period = dict(report.get("period") or {})
    subject = dict(report.get("subject") or {})

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=str(report.get("title") or "Sentinel Report"),
        author="Sentinel-KE",
    )
    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="SentinelTitle",
            parent=styles["Title"],
            fontName="Helvetica-Bold",
            fontSize=20,
            leading=24,
            textColor=colors.HexColor("#0f172a"),
            spaceAfter=10,
        )
    )
    styles.add(
        ParagraphStyle(
            name="SentinelSection",
            parent=styles["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=13,
            leading=16,
            textColor=colors.HexColor("#134e4a"),
            spaceBefore=8,
            spaceAfter=6,
        )
    )
    styles.add(
        ParagraphStyle(
            name="SentinelBody",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=10,
            leading=14,
            textColor=colors.HexColor("#111827"),
            spaceAfter=6,
        )
    )
    styles.add(
        ParagraphStyle(
            name="SentinelMeta",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=9,
            leading=12,
            textColor=colors.HexColor("#4b5563"),
            spaceAfter=3,
        )
    )
    code_style = ParagraphStyle(
        "SentinelCode",
        parent=styles["Code"],
        fontName="Courier",
        fontSize=7.5,
        leading=9,
        textColor=colors.HexColor("#111827"),
        backColor=colors.HexColor("#f3f4f6"),
        borderWidth=0.5,
        borderColor=colors.HexColor("#d1d5db"),
        borderPadding=6,
        spaceBefore=3,
        spaceAfter=8,
    )

    def para(text_value: Any, style_name: str = "SentinelBody") -> Paragraph:
        text = html.escape("" if text_value is None else str(text_value)).replace("\n", "<br/>")
        return Paragraph(text or "&nbsp;", styles[style_name])

    story = [
        Paragraph(html.escape(str(report.get("title") or "Sentinel Report")), styles["SentinelTitle"]),
        para(summary.get("headline")),
        para(f"Classification: {report.get('classification')}"),
        para(f"Generated: {report.get('generated_at')}", "SentinelMeta"),
        para(f"Period: {period.get('label')} ({period.get('start')} to {period.get('end')})", "SentinelMeta"),
        para(f"Audience: {', '.join(report.get('audience') or [])}", "SentinelMeta"),
        Spacer(1, 4 * mm),
        Paragraph("Plain-English Summary", styles["SentinelSection"]),
        para(f"What is happening: {summary.get('overview')}"),
        para(f"Why it matters: {summary.get('why_it_matters')}"),
        para(f"What to do next: {summary.get('next_step')}"),
        para(f"Confidence: {summary.get('confidence_statement')}"),
        Paragraph("Subject", styles["SentinelSection"]),
        Preformatted(_short_json(subject), code_style),
        Paragraph("Key Findings", styles["SentinelSection"]),
    ]

    if findings:
        for item in findings:
            title = f"{item.get('title') or 'Finding'} [{item.get('severity') or 'info'}]"
            story.append(para(title))
            story.append(para(item.get("plain_text")))
    else:
        story.append(para("No findings recorded.", "SentinelMeta"))

    story.extend(
        [
            Paragraph("Explainability", styles["SentinelSection"]),
            para(explainability.get("plain_language") or "No explainability summary recorded."),
            Preformatted(_short_json(explainability), code_style),
            Paragraph("Recommended Actions", styles["SentinelSection"]),
        ]
    )
    if actions:
        for action in actions:
            story.append(para(f"- {action}"))
    else:
        story.append(para("No recommended actions recorded.", "SentinelMeta"))

    story.extend(
        [
            Paragraph("Governance and Caveats", styles["SentinelSection"]),
            Preformatted(_short_json(governance), code_style),
            Paragraph("Limitations", styles["SentinelSection"]),
        ]
    )
    if limitations:
        for limitation in limitations:
            story.append(para(f"- {limitation}"))
    else:
        story.append(para("No explicit limitations recorded.", "SentinelMeta"))

    story.extend(
        [
            Paragraph("Evidence Appendix", styles["SentinelSection"]),
            Preformatted(_short_json(appendix), code_style),
            Spacer(1, 4 * mm),
            para(
                "Sentinel-KE generated report. AI outputs support prioritization and review; they do not replace human judgment or legal process.",
                "SentinelMeta",
            ),
        ]
    )

    doc.build(story)
    return buffer.getvalue()

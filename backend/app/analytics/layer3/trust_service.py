from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.analytics.ai_models import (
    AIAttackPathScore,
    AIAttackTechniqueHit,
    AICampaignRiskIndicator,
    AIDecisionFusion,
    AIDriftReport,
    AIExplanation,
    AIFeedbackLabel,
    AIModelRollout,
    AIPrediction,
    GNNTrainingRun,
    GraphFeatureSnapshot,
    ThreatIntelIndicator,
)
from app.analytics.layer3.ai_intel import techniques_to_tools
from app.analytics.layer3.worker_heartbeat import summarize_worker_freshness
from app.campaign.models import Campaign, CampaignEntity, CampaignEvent
from app.defense.models import BackupAttestation, ContainmentAction, ContainmentWebhook, IncidentPlaybookRun, RestoreDrill
from app.legal.models import LegalEvidenceBundle


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _status_rank(status: str) -> int:
    return {"pass": 0, "warn": 1, "fail": 2}.get(status, 1)


def _severity(score: float | None) -> str:
    value = float(score or 0.0)
    if value >= 90:
        return "critical"
    if value >= 75:
        return "high"
    if value >= 55:
        return "medium"
    return "low"


def _operator_decision(score: float | None, uncertainty: float | None) -> tuple[str, str]:
    value = float(score or 0.0)
    uncertainty_value = float(uncertainty or 0.0)
    if value >= 85 and uncertainty_value < 0.45:
        return "Act now after quick human confirmation.", "The signal is severe and relatively confident."
    if value >= 70:
        return "Review now and prepare containment.", "The signal is elevated enough to justify immediate analyst attention."
    if value >= 55:
        return "Investigate soon; do not auto-contain yet.", "The signal is meaningful but still needs corroboration."
    return "Monitor only; no immediate action is required from your side.", "The current score is low enough for observation rather than intervention."


def _data_realism_note(
    *,
    real_ratio: float | None,
    avg_real_signal_ratio: float | None,
    feedback_override_count: int,
    feedback_consumed_count: int,
) -> str:
    if real_ratio is None:
        base = "No current data-mix record is attached to this model run."
    elif real_ratio >= 0.7:
        base = "This run is mostly driven by real or mixed-source signals."
    elif real_ratio >= 0.35:
        base = "This run uses a mixed real-plus-synthetic dataset."
    else:
        base = "This run is still mostly synthetic or demo-oriented and should be used for triage, not proof."

    detail: list[str] = []
    if real_ratio is not None:
        detail.append(f"Real-signal ratio is {round(real_ratio * 100)}%.")
    if avg_real_signal_ratio is not None:
        detail.append(f"Average per-node real coverage is {round(avg_real_signal_ratio * 100)}%.")
    if feedback_override_count > 0:
        feedback_sentence = f"{feedback_override_count} analyst feedback label(s) influenced training"
        if feedback_consumed_count > 0:
            feedback_sentence += f", including {feedback_consumed_count} newly consumed"
        detail.append(f"{feedback_sentence}.")
    return " ".join([base, *detail]).strip()


def _graph_meaning(path_score: AIAttackPathScore | None, evidence_paths: list[Any]) -> str:
    if not path_score:
        return "Graph reasoning is not yet attached, so this score is coming mostly from model output and supporting evidence rather than a verified graph route."
    hops = int(path_score.hop_count or 0)
    value = float(path_score.path_score or 0.0)
    if evidence_paths:
        return (
            f"Graph path score is {value:.1f}/100 across {hops} hop(s): it measures how strongly this entity is structurally linked to risky neighbours, "
            "shared events, or campaign routes."
        )
    return (
        f"Graph path score is {value:.1f}/100 across {hops} hop(s), but no evidence path is attached yet. "
        "Treat the structural signal as suggestive rather than fully explained."
    )


def _raw_entity_target(entity_key: str) -> str:
    return entity_key.split(":", 1)[1] if ":" in entity_key else entity_key


def _suggested_containment_action(entity_key: str) -> str:
    family = entity_key.split(":", 1)[0] if ":" in entity_key else entity_key
    if family == "ip":
        return "block_ip"
    if family in {"service_id", "url", "domain"}:
        return "enable_waf_challenge"
    if family in {"host", "endpoint", "device_id"}:
        return "isolate_host"
    if family in {"account_h", "user"}:
        return "revoke_user"
    if family == "email":
        return "quarantine_email"
    return "block_ip"


def _suggested_containment_section(entity_key: str) -> str | None:
    family = entity_key.split(":", 1)[0] if ":" in entity_key else entity_key
    if family in {"service_id", "provider_id"}:
        target = _raw_entity_target(entity_key).strip()
        return target or None
    return None


def _containment_readiness(active_webhooks: int, recommended_controls: list[str], latest_containment: ContainmentAction | None) -> str:
    if latest_containment:
        return (
            f"Latest containment record is {latest_containment.action_type} on {latest_containment.target} with status {latest_containment.status}. "
            f"There are {active_webhooks} matching active webhook(s) available for partner-side delivery."
        )
    if active_webhooks <= 0:
        return "Containment is not operationally ready yet because no matching active partner webhook is registered for the current action path."
    if not recommended_controls:
        return f"There are {active_webhooks} matching active webhook(s), but the explanation did not return a recommended control for this entity."
    return f"Containment is available: {active_webhooks} matching active webhook(s) are registered and the explanation returned response guidance."


def _status_from_age(dt: datetime | None, *, warn_hours: int, fail_hours: int) -> tuple[str, str, float | None]:
    if not dt:
        return "fail", "No records found.", None
    age_hours = max(0.0, (_utcnow() - dt).total_seconds() / 3600.0)
    if age_hours >= fail_hours:
        return "fail", f"Stale by {age_hours:.1f}h.", age_hours
    if age_hours >= warn_hours:
        return "warn", f"Aging ({age_hours:.1f}h old).", age_hours
    return "pass", f"Fresh ({age_hours:.1f}h old).", age_hours


def _latest_prediction(
    db: Session,
    *,
    entity_key: str,
    prediction_type: str | None = None,
) -> AIPrediction | None:
    q = db.query(AIPrediction).filter(AIPrediction.entity_key == entity_key)
    if prediction_type:
        q = q.filter(AIPrediction.prediction_type == prediction_type)
    row = (
        q.order_by(AIPrediction.window_end.desc(), AIPrediction.created_at.desc(), AIPrediction.score.desc())
        .first()
    )
    if row or prediction_type is not None:
        return row
    # Prefer cyber if caller did not specify a prediction type.
    return _latest_prediction(db, entity_key=entity_key, prediction_type="risk_gnn")


def _latest_training_run(
    db: Session,
    *,
    prediction_type: str,
    model_version: str | None = None,
) -> GNNTrainingRun | None:
    q = db.query(GNNTrainingRun).filter(GNNTrainingRun.prediction_type == prediction_type)
    if model_version:
        q = q.filter(GNNTrainingRun.model_version == model_version)
    return q.order_by(GNNTrainingRun.created_at.desc()).first()


def _latest_drift_report(
    db: Session,
    *,
    prediction_type: str,
    model_version: str | None = None,
) -> AIDriftReport | None:
    q = db.query(AIDriftReport).filter(AIDriftReport.prediction_type == prediction_type)
    if model_version:
        q = q.filter(AIDriftReport.model_version == model_version)
    return q.order_by(AIDriftReport.created_at.desc()).first()


def _latest_rollout(db: Session, *, prediction_type: str) -> AIModelRollout | None:
    return (
        db.query(AIModelRollout)
        .filter(AIModelRollout.prediction_type == prediction_type)
        .order_by(AIModelRollout.updated_at.desc())
        .first()
    )


def _campaign_links(db: Session, *, entity_key: str, limit: int = 200) -> list[dict[str, Any]]:
    rows = (
        db.query(AICampaignRiskIndicator)
        .order_by(AICampaignRiskIndicator.window_end.desc(), AICampaignRiskIndicator.score.desc())
        .limit(limit)
        .all()
    )
    linked: list[dict[str, Any]] = []
    for row in rows:
        evidence = list(row.evidence_entity_keys or [])
        if entity_key not in evidence:
            continue
        linked.append(
            {
                "campaign_id": str(row.campaign_id),
                "score": float(row.score or 0.0),
                "severity": row.severity,
                "flagged_entity_count": int(row.flagged_entity_count or 0),
                "window_end": row.window_end.isoformat(),
            }
        )
    return linked


def _trust_check(label: str, status: str, detail: str, *, action: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "label": label,
        "status": status,
        "detail": detail,
    }
    if action:
        payload["action"] = action
    return payload


def build_entity_trust_summary(
    db: Session,
    *,
    entity_key: str,
    prediction_type: str | None = None,
) -> dict[str, Any]:
    prediction = _latest_prediction(db, entity_key=entity_key, prediction_type=prediction_type)
    if not prediction:
        raise ValueError("prediction_not_found")

    explanation = (
        db.query(AIExplanation)
        .filter(AIExplanation.prediction_id == prediction.id)
        .order_by(AIExplanation.created_at.desc())
        .first()
    )
    path_score = (
        db.query(AIAttackPathScore)
        .filter(AIAttackPathScore.entity_key == entity_key)
        .filter(AIAttackPathScore.prediction_type == prediction.prediction_type)
        .order_by(AIAttackPathScore.window_end.desc(), AIAttackPathScore.created_at.desc())
        .first()
    )
    fusion = (
        db.query(AIDecisionFusion)
        .filter(AIDecisionFusion.entity_key == entity_key)
        .filter(AIDecisionFusion.prediction_type == prediction.prediction_type)
        .order_by(AIDecisionFusion.window_end.desc(), AIDecisionFusion.created_at.desc())
        .first()
    )
    run = _latest_training_run(
        db,
        prediction_type=prediction.prediction_type,
        model_version=prediction.model_version,
    )
    drift = _latest_drift_report(
        db,
        prediction_type=prediction.prediction_type,
        model_version=prediction.model_version,
    )
    rollout = _latest_rollout(db, prediction_type=prediction.prediction_type)
    feedback_rows = (
        db.query(AIFeedbackLabel)
        .filter(AIFeedbackLabel.entity_key == entity_key)
        .order_by(AIFeedbackLabel.created_at.desc())
        .limit(10)
        .all()
    )
    technique_rows = (
        db.query(AIAttackTechniqueHit)
        .filter(AIAttackTechniqueHit.entity_key == entity_key)
        .filter(AIAttackTechniqueHit.prediction_type == prediction.prediction_type)
        .order_by(AIAttackTechniqueHit.window_end.desc(), AIAttackTechniqueHit.confidence.desc())
        .limit(20)
        .all()
    )
    technique_ids = [row.technique_id for row in technique_rows]
    inferred_tools = techniques_to_tools(technique_ids) if technique_ids else []
    linked_campaigns = _campaign_links(db, entity_key=entity_key)
    containment_action = _suggested_containment_action(entity_key)
    containment_section = _suggested_containment_section(entity_key)
    active_webhooks_q = (
        db.query(ContainmentWebhook)
        .filter(ContainmentWebhook.is_active.is_(True))
        .filter(ContainmentWebhook.action_type == containment_action)
    )
    if containment_section:
        active_webhooks_q = active_webhooks_q.filter(ContainmentWebhook.section_code == containment_section)
    active_webhooks = active_webhooks_q.count()
    latest_containment = (
        db.query(ContainmentAction)
        .filter(ContainmentAction.target.in_([entity_key, entity_key.split(":", 1)[1] if ":" in entity_key else entity_key]))
        .order_by(ContainmentAction.executed_at.desc(), ContainmentAction.created_at.desc())
        .first()
    )

    evidence_hashes = list(explanation.evidence_hashes or []) if explanation else []
    evidence_paths = list(explanation.evidence_paths or []) if explanation else []
    recommended_controls = list(explanation.recommended_controls_json or []) if explanation else []
    counterfactual = dict(explanation.counterfactual_json or {}) if explanation else {}

    fairness = dict((run.metrics_json or {}).get("fairness") or {}) if run else {}
    fairness_disparity = float(fairness.get("max_positive_rate_disparity", 0.0) or 0.0)
    fairness_status = "fail" if fairness_disparity >= 0.75 else ("warn" if fairness_disparity >= 0.35 else "pass")

    real_gate = dict((run.metrics_json or {}).get("real_data_gate") or {}) if run else {}
    provenance = dict((run.metrics_json or {}).get("provenance") or {}) if run else {}
    feedback_metrics = dict((run.metrics_json or {}).get("feedback") or {}) if run else {}
    real_data_passed = bool(real_gate.get("passed", False))
    drift_status = str(drift.status or "unknown") if drift else "unknown"
    real_ratio = float(provenance.get("real_ratio")) if provenance.get("real_ratio") is not None else None
    avg_real_signal_ratio = (
        float(provenance.get("avg_real_signal_ratio"))
        if provenance.get("avg_real_signal_ratio") is not None
        else None
    )
    feedback_override_count = int(feedback_metrics.get("override_count") or 0)
    feedback_consumed_count = int(
        feedback_metrics.get("consumed_count")
        or feedback_metrics.get("new_feedback_count")
        or 0
    )
    operator_decision, operator_reason = _operator_decision(prediction.score, prediction.uncertainty)

    trust_checks = [
        _trust_check(
            "Prediction coverage",
            "pass",
            f"Latest {prediction.prediction_type} score is {prediction.score:.1f}/100 from model {prediction.model_version}.",
        ),
        _trust_check(
            "Evidence completeness",
            "pass" if explanation and evidence_hashes else ("warn" if explanation else "fail"),
            (
                f"{len(evidence_hashes)} evidence hashes and {len(explanation.reason_codes or []) if explanation else 0} reason codes attached."
                if explanation
                else "No explanation record is attached to this prediction."
            ),
            action="Attach or regenerate explanation artifacts before formal escalation." if not explanation else None,
        ),
        _trust_check(
            "Graph reasoning",
            "pass" if path_score and evidence_paths else ("warn" if path_score or evidence_paths else "fail"),
            (
                f"Path score {float(path_score.path_score or 0.0):.1f}/100 across {int(path_score.hop_count or 0)} hops."
                if path_score
                else "No path score or graph route is attached yet."
            ),
            action="Run graph/path workers before relying on structural campaign reasoning." if not path_score else None,
        ),
        _trust_check(
            "Response readiness",
            "pass" if recommended_controls and active_webhooks > 0 else ("warn" if recommended_controls or active_webhooks > 0 else "fail"),
            (
                f"{len(recommended_controls)} recommended controls and {active_webhooks} matching containment webhooks available for {containment_action}."
                if recommended_controls or active_webhooks > 0
                else f"No recommended controls or matching containment webhooks are available for {containment_action}."
            ),
            action="Register at least one containment webhook and validate the Defense workflow." if active_webhooks == 0 else None,
        ),
        _trust_check(
            "Governance guards",
            "pass" if real_data_passed and fairness_status == "pass" and drift_status in {"ok", "stable", "unknown"} else ("warn" if fairness_status != "fail" else "fail"),
            f"Real-data gate={'pass' if real_data_passed else 'warn'}, fairness={fairness_status}, drift={drift_status}.",
            action="Review rollout or hold escalation if fairness or drift has degraded." if fairness_status == "fail" or drift_status not in {"ok", "stable", "unknown"} else None,
        ),
        _trust_check(
            "Investigator defensibility",
            "pass" if evidence_hashes and (evidence_paths or counterfactual) else ("warn" if evidence_hashes else "fail"),
            (
                f"{len(evidence_hashes)} evidence hashes, {len(evidence_paths)} graph paths, counterfactual={'yes' if counterfactual else 'no'}."
                if evidence_hashes or evidence_paths or counterfactual
                else "No defensibility artifacts are attached beyond the raw prediction."
            ),
            action="Generate the explanation and legal report before formal handoff." if not evidence_hashes else None,
        ),
        _trust_check(
            "Analyst feedback loop",
            "pass" if feedback_rows else "warn",
            f"{len(feedback_rows)} analyst feedback records captured for this entity." if feedback_rows else "No analyst feedback has been captured for this entity yet.",
            action="Capture analyst disposition after review to improve future label quality." if not feedback_rows else None,
        ),
    ]

    failing_actions = [check["action"] for check in trust_checks if check.get("action") and check["status"] != "pass"]
    next_actions = list(dict.fromkeys(recommended_controls + failing_actions))
    if not next_actions:
        next_actions = [
            "Open the Defense Center to create an incident playbook run if human review confirms this entity is actionable.",
            "Download the entity investigation report before escalating outside the SOC.",
        ]

    label_strategy = dict((run.metrics_json or {}).get("label_strategy") or {}) if run else {}
    operator_brief = {
        "headline": (
            f"{entity_key} is currently assessed as {_severity(prediction.score)} risk at {float(prediction.score or 0.0):.1f}/100. "
            f"{operator_decision}"
        ),
        "what_system_saw": [
            f"{len(explanation.reason_codes or []) if explanation else len(prediction.reason_codes or [])} reason codes contributed to the latest score.",
            f"{len(linked_campaigns)} linked campaign indicators reference this entity." if linked_campaigns else "No linked campaign indicators currently reference this entity.",
            f"{len(technique_rows)} ATT&CK technique hits and {len(inferred_tools)} inferred attacker tools are attached.",
            f"{len(evidence_hashes)} evidence hashes and {len(evidence_paths)} evidence paths are available for review.",
        ],
        "why_it_matters": [
            operator_reason,
            f"Decision source: {prediction.decision_source or 'model'}; kill-chain stage: {prediction.kill_chain_stage or 'unknown'}.",
            f"Decision fusion is {fusion.decision if fusion else 'not available'} with score {float(fusion.fused_score or 0.0):.1f}/100." if fusion else "No decision-fusion record is available yet.",
            "AI output is an investigative indicator and must be corroborated before enforcement.",
        ],
        "next_actions": next_actions[:5],
        "caveat": str(label_strategy.get("eval_caveat") or "Model quality depends on the current event and analyst-feedback coverage."),
        "operator_decision": operator_decision,
        "likelihood_indicator": f"{round(float(prediction.score or 0.0))}/100 cyber-risk likelihood indicator",
        "graph_meaning": _graph_meaning(path_score, evidence_paths),
        "data_realism": _data_realism_note(
            real_ratio=real_ratio,
            avg_real_signal_ratio=avg_real_signal_ratio,
            feedback_override_count=feedback_override_count,
            feedback_consumed_count=feedback_consumed_count,
        ),
        "containment_readiness": _containment_readiness(active_webhooks, recommended_controls, latest_containment),
    }

    return {
        "entity_key": entity_key,
        "prediction_type": prediction.prediction_type,
        "prediction": {
            "id": str(prediction.id),
            "score": float(prediction.score or 0.0),
            "confidence": float(prediction.confidence or 0.0),
            "uncertainty": float(prediction.uncertainty or 0.0),
            "severity": _severity(prediction.score),
            "kill_chain_stage": prediction.kill_chain_stage,
            "decision_source": prediction.decision_source,
            "model_version": prediction.model_version,
            "window_end": prediction.window_end.isoformat(),
        },
        "operator_brief": operator_brief,
        "evidence_summary": {
            "reason_count": len(explanation.reason_codes or []) if explanation else len(prediction.reason_codes or []),
            "evidence_hash_count": len(evidence_hashes),
            "evidence_path_count": len(evidence_paths),
            "counterfactual_available": bool(counterfactual),
            "linked_campaign_count": len(linked_campaigns),
            "technique_count": len(technique_rows),
            "tool_count": len(inferred_tools),
        },
        "action_summary": {
            "recommended_controls": recommended_controls,
            "containment_webhook_count": active_webhooks,
            "fusion_decision": fusion.decision if fusion else None,
            "fusion_score": float(fusion.fused_score or 0.0) if fusion else None,
        },
        "governance": {
            "run_id": str(run.id) if run else None,
            "model_version": prediction.model_version,
            "rollout_mode": rollout.rollout_mode if rollout else None,
            "rollout_status": rollout.status if rollout else None,
            "real_data_gate_passed": real_data_passed,
            "real_data_gate": real_gate,
            "fairness": fairness,
            "fairness_status": fairness_status,
            "drift_status": drift_status,
            "drift_score": float(drift.drift_score or 0.0) if drift else None,
            "label_strategy": label_strategy,
            "provenance": provenance,
            "feedback_metrics": feedback_metrics,
        },
        "trust_checks": trust_checks,
        "linked_campaigns": linked_campaigns[:8],
        "feedback": {
            "count": len(feedback_rows),
            "latest_status": feedback_rows[0].status if feedback_rows else None,
            "latest_label": int(feedback_rows[0].feedback_label) if feedback_rows else None,
        },
        "generated_at": _utcnow().isoformat(),
    }


def build_campaign_trust_summary(
    db: Session,
    *,
    campaign_id: str,
) -> dict[str, Any]:
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not campaign:
        raise ValueError("campaign_not_found")

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
        .limit(100)
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

    trust_checks = [
        _trust_check(
            "Campaign evidence coverage",
            "pass" if events and entities else ("warn" if entities or events else "fail"),
            f"{len(entities)} entities and {len(events)} recent campaign events are linked.",
            action="Refresh campaign correlation before briefing if the campaign has no supporting events." if not events else None,
        ),
        _trust_check(
            "AI campaign scoring",
            "pass" if indicator else "warn",
            (
                f"Latest campaign AI indicator is {float(indicator.score or 0.0):.1f}/100 "
                f"with {int(indicator.flagged_entity_count or 0)} flagged entities."
                if indicator else
                "No campaign-level AI indicator is attached yet."
            ),
            action="Run or refresh the post-prediction campaign indicator pipeline before escalation." if not indicator else None,
        ),
        _trust_check(
            "Legal packaging",
            "pass" if latest_bundle else "warn",
            (
                f"Legal evidence bundle {latest_bundle.bundle_id} is available for this campaign."
                if latest_bundle else
                "No legal evidence bundle is available yet for this campaign."
            ),
            action="Generate the legal evidence bundle before external enforcement or prosecutor handoff." if not latest_bundle else None,
        ),
    ]

    next_actions = [
        check["action"]
        for check in trust_checks
        if check.get("action") and check["status"] != "pass"
    ]
    if not next_actions:
        next_actions = [
            "Validate the highest-risk entities inside the campaign before escalation.",
            "Preserve linked events and graph relationships as evidence.",
            "Refresh the case packet before inter-agency handoff.",
        ]

    return {
        "campaign_id": str(campaign.id),
        "operator_brief": {
            "headline": f"Campaign {campaign.type} is currently {_severity(campaign.score)} risk.",
            "what_system_saw": [
                f"{len(entities)} linked entities and {len(events)} recent campaign events remain attached.",
                (
                    f"Latest campaign AI indicator is {float(indicator.score or 0.0):.1f}/100."
                    if indicator else
                    "No campaign-level AI indicator is attached yet."
                ),
                (
                    f"Legal bundle {latest_bundle.bundle_id} is available for downstream sharing."
                    if latest_bundle else
                    "No legal bundle is attached yet."
                ),
            ],
            "why_it_matters": [
                "Campaign-level reporting explains connected activity, not just isolated alerts.",
                "Coordinated campaigns are harder to dismiss and easier to escalate with evidence continuity.",
            ],
            "next_actions": next_actions[:5],
            "caveat": "Campaign AI indicators summarize linked evidence and should still be validated by an analyst before enforcement.",
        },
        "evidence_summary": {
            "entity_count": len(entities),
            "event_count": len(events),
            "ai_indicator_available": bool(indicator),
            "legal_bundle_available": bool(latest_bundle),
        },
        "trust_checks": trust_checks,
        "generated_at": _utcnow().isoformat(),
    }


def build_platform_trust_summary(db: Session) -> dict[str, Any]:
    now = _utcnow()
    prediction_types = ("risk_gnn", "corruption_risk")

    latest_prediction = db.query(AIPrediction).order_by(AIPrediction.created_at.desc()).first()
    latest_explanation = db.query(AIExplanation).order_by(AIExplanation.created_at.desc()).first()
    latest_snapshot = db.query(GraphFeatureSnapshot).order_by(GraphFeatureSnapshot.created_at.desc()).first()
    latest_threat_intel = db.query(ThreatIntelIndicator).order_by(ThreatIntelIndicator.updated_at.desc()).first()

    active_webhooks = db.query(ContainmentWebhook).filter(ContainmentWebhook.is_active.is_(True)).count()
    executed_actions_24h = (
        db.query(ContainmentAction)
        .filter(ContainmentAction.executed_at >= now - timedelta(hours=24))
        .count()
    )
    pending_actions = db.query(ContainmentAction).filter(ContainmentAction.status == "queued").count()
    incident_runs_24h = (
        db.query(IncidentPlaybookRun)
        .filter(IncidentPlaybookRun.created_at >= now - timedelta(hours=24))
        .count()
    )
    backup_attestations_30d = (
        db.query(BackupAttestation)
        .filter(BackupAttestation.created_at >= now - timedelta(days=30))
        .count()
    )
    latest_restore = db.query(RestoreDrill).order_by(RestoreDrill.created_at.desc()).first()
    restore_status = "pass" if latest_restore and latest_restore.success else ("warn" if latest_restore else "fail")

    source_count = len({row[0] for row in db.query(ThreatIntelIndicator.source).distinct().all() if row[0]})
    worker_freshness = summarize_worker_freshness(
        db,
        worker_names=[
            "neo4j_worker",
            "graph_feature_worker",
            "gnn_train_worker",
            "corruption_train_worker",
            "ai_inference_worker",
        ],
    )

    model_summaries: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    recommended_actions: list[str] = []

    for prediction_type in prediction_types:
        run = _latest_training_run(db, prediction_type=prediction_type)
        drift = _latest_drift_report(db, prediction_type=prediction_type, model_version=run.model_version if run else None)
        rollout = _latest_rollout(db, prediction_type=prediction_type)
        fairness = dict((run.metrics_json or {}).get("fairness") or {}) if run else {}
        provenance = dict((run.metrics_json or {}).get("provenance") or {}) if run else {}
        feedback = dict((run.metrics_json or {}).get("feedback") or {}) if run else {}
        fairness_disparity = float(fairness.get("max_positive_rate_disparity", 0.0) or 0.0)
        fairness_status = "fail" if fairness_disparity >= 0.75 else ("warn" if fairness_disparity >= 0.35 else "pass")
        real_gate = dict((run.metrics_json or {}).get("real_data_gate") or {}) if run else {}
        real_data_passed = bool(real_gate.get("passed", False))
        drift_state = str(drift.status or "unknown") if drift else "unknown"
        status = "pass"
        if not run:
            status = "fail"
        elif fairness_status == "fail" or not real_data_passed or drift_state not in {"ok", "stable", "unknown"}:
            status = "warn"

        model_summaries.append(
            {
                "prediction_type": prediction_type,
                "model_version": run.model_version if run else None,
                "window_end": run.window_end.isoformat() if run else None,
                "fairness_status": fairness_status,
                "real_data_gate_passed": real_data_passed,
                "real_ratio": float(provenance.get("real_ratio") or 0.0),
                "avg_real_signal_ratio": float(provenance.get("avg_real_signal_ratio") or 0.0),
                "feedback_override_count": int(feedback.get("override_count") or 0),
                "feedback_consumed_count": int(feedback.get("consumed_count") or feedback.get("new_feedback_count") or 0),
                "drift_status": drift_state,
                "rollout_mode": rollout.rollout_mode if rollout else None,
                "rollout_status": rollout.status if rollout else None,
                "latest_prediction_source": (
                    str(latest_prediction.decision_source or "unknown")
                    if latest_prediction and latest_prediction.prediction_type == prediction_type
                    else None
                ),
                "label_caveat": str(((run.metrics_json or {}).get("label_strategy") or {}).get("eval_caveat") or "") if run else "",
                "status": status,
            }
        )

    prediction_freshness_status, prediction_freshness_detail, prediction_age_hours = _status_from_age(
        latest_prediction.created_at if latest_prediction else None,
        warn_hours=6,
        fail_hours=24,
    )
    graph_freshness_status, graph_freshness_detail, graph_age_hours = _status_from_age(
        latest_snapshot.created_at if latest_snapshot else None,
        warn_hours=6,
        fail_hours=24,
    )
    intel_freshness_status, intel_freshness_detail, intel_age_hours = _status_from_age(
        latest_threat_intel.updated_at if latest_threat_intel else None,
        warn_hours=12,
        fail_hours=48,
    )

    checks.extend(
        [
            _trust_check("Prediction freshness", prediction_freshness_status, prediction_freshness_detail, action="Run inference or training to refresh the AI queue." if prediction_freshness_status != "pass" else None),
            _trust_check("Graph freshness", graph_freshness_status, graph_freshness_detail, action="Run the graph feature worker before relying on graph intelligence." if graph_freshness_status != "pass" else None),
            _trust_check("Threat-intel freshness", intel_freshness_status, intel_freshness_detail, action="Refresh Feodo/OTX/URLhaus feeds before national briefing." if intel_freshness_status != "pass" else None),
            _trust_check(
                "Containment readiness",
                "pass" if active_webhooks > 0 else "warn",
                f"{active_webhooks} active containment webhooks, {executed_actions_24h} executed actions in the last 24h, {pending_actions} queued.",
                action="Register or test a containment webhook before demo if zero active hooks remain." if active_webhooks == 0 else None,
            ),
            _trust_check(
                "Resilience posture",
                "pass" if backup_attestations_30d > 0 and restore_status == "pass" else ("warn" if backup_attestations_30d > 0 or restore_status != "fail" else "fail"),
                f"{backup_attestations_30d} backup attestations in 30d; latest restore drill is {'successful' if latest_restore and latest_restore.success else ('recorded but failed' if latest_restore else 'missing')}.",
                action="Record a fresh backup attestation and one successful restore drill." if backup_attestations_30d == 0 or restore_status != "pass" else None,
            ),
        ]
    )
    worker_problem = next((w for w in worker_freshness if str(w.get("freshness")) != "pass"), None)
    checks.append(
        _trust_check(
            "Worker freshness",
            (
                "warn"
                if not worker_freshness
                else ("pass" if not worker_problem else ("warn" if str(worker_problem.get("freshness")) == "warn" else "fail"))
            ),
            (
                "No worker heartbeat records have been captured yet."
                if not worker_freshness
                else (
                    "All core analytics workers are fresh."
                    if not worker_problem
                    else f"{worker_problem.get('worker_name')} is {worker_problem.get('freshness')} with last status {worker_problem.get('last_status')}."
                )
            ),
            action=(
                "Run the core analytics workers once so freshness can be measured."
                if not worker_freshness
                else ("Refresh the stale worker before relying on live analytics." if worker_problem else None)
            ),
        )
    )

    for summary in model_summaries:
        checks.append(
            _trust_check(
                f"{summary['prediction_type']} governance",
                summary["status"],
                (
                    f"Model {summary['model_version'] or 'n/a'}; fairness={summary['fairness_status']}; "
                    f"real-data gate={'pass' if summary['real_data_gate_passed'] else 'warn'}; "
                    f"real ratio={float(summary['real_ratio']):.2f}; "
                    f"feedback overrides={int(summary['feedback_override_count'])}; "
                    f"drift={summary['drift_status']}."
                ),
                action="Review model rollout and governance metrics before claiming this model is production-ready." if summary["status"] != "pass" else None,
            )
        )

    for check in checks:
        action = check.get("action")
        if action and check["status"] != "pass":
            recommended_actions.append(str(action))

    overall_status = "pass"
    if any(check["status"] == "fail" for check in checks):
        overall_status = "fail"
    elif any(check["status"] == "warn" for check in checks):
        overall_status = "warn"

    return {
        "overall_status": overall_status,
        "headline": (
            "AI trust posture is ready for operator use."
            if overall_status == "pass"
            else ("AI trust posture is usable with caveats." if overall_status == "warn" else "AI trust posture needs remediation before high-confidence use.")
        ),
        "freshness": {
            "prediction_age_hours": prediction_age_hours,
            "graph_age_hours": graph_age_hours,
            "intel_age_hours": intel_age_hours,
            "latest_prediction_at": latest_prediction.created_at.isoformat() if latest_prediction else None,
            "latest_prediction_source": str(latest_prediction.decision_source or "unknown") if latest_prediction else None,
            "latest_explanation_at": latest_explanation.created_at.isoformat() if latest_explanation else None,
            "latest_graph_snapshot_at": latest_snapshot.created_at.isoformat() if latest_snapshot else None,
            "latest_threat_intel_at": latest_threat_intel.updated_at.isoformat() if latest_threat_intel else None,
            "threat_intel_source_count": source_count,
        },
        "action_readiness": {
            "active_webhooks": active_webhooks,
            "executed_actions_24h": executed_actions_24h,
            "pending_actions": pending_actions,
            "incident_runs_24h": incident_runs_24h,
        },
        "resilience": {
            "backup_attestations_30d": backup_attestations_30d,
            "latest_restore_success": bool(latest_restore.success) if latest_restore else False,
            "latest_restore_at": latest_restore.created_at.isoformat() if latest_restore else None,
        },
        "model_governance": model_summaries,
        "worker_freshness": worker_freshness,
        "checks": checks,
        "recommended_actions": list(dict.fromkeys(recommended_actions))[:6],
        "generated_at": now.isoformat(),
    }

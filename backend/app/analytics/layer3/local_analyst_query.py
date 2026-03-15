from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Sequence

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.analytics.ai_models import (
    AIExplanation,
    AIAttackPathScore,
    AIAttackTechniqueHit,
    AIDecisionFusion,
    AIPrediction,
)
from app.analytics.layer3.ai_intel import techniques_to_tools
from app.analytics.layer3.forecasting import build_risk_forecast
from app.core.config import settings
from app.defense.models import ContainmentAction
from app.legal.models import LegalEvidenceBundle


ENTITY_KEY_RE = re.compile(
    r"\b(?:ip|domain|url|service_id|endpoint|provider_id|device_id|account_h|phone_h|person_h):[A-Za-z0-9._:/-]+\b"
)

SUSPICIOUS_EVENT_TYPES = (
    "DDOS_SIGNAL_EVENT",
    "SIM_SWAP_EVENT",
    "PHISHING_MESSAGE_EVENT",
    "DFIR_FINDING_EVENT",
    "FILE_INTEGRITY_EVENT",
    "DB_AUDIT_EVENT",
    "VULNERABILITY_EVENT",
)


def _pick_entity_key(question: str, context: Mapping[str, Any] | None) -> str | None:
    if context:
        raw = str(context.get("entity_key") or "").strip()
        if raw:
            return raw
    match = ENTITY_KEY_RE.search(question or "")
    return match.group(0) if match else None


def _detect_intent(question: str) -> str:
    q = str(question or "").lower()
    score_map = {
        "forecast": sum(w in q for w in ("forecast", "predict", "likelihood", "next week", "trend", "rising")),
        "containment": sum(w in q for w in ("contain", "block", "isolate", "mitigate", "response", "action")),
        "tools": sum(w in q for w in ("tool", "malware", "software", "family", "mimikatz", "cobalt", "impacket")),
        "evidence": sum(w in q for w in ("evidence", "proof", "why", "explain", "legal", "bundle", "path")),
        "timing": sum(w in q for w in ("when", "time", "hour", "daily", "weekly", "weekday", "peak", "occur")),
    }
    best = max(score_map.items(), key=lambda item: item[1])
    return best[0] if best[1] > 0 else "summary"


def _latest_prediction(db: Session, entity_key: str | None) -> Optional[AIPrediction]:
    q = db.query(AIPrediction).filter(AIPrediction.prediction_type == "risk_gnn")
    if entity_key:
        q = q.filter(AIPrediction.entity_key == entity_key)
    return q.order_by(AIPrediction.window_end.desc(), AIPrediction.score.desc()).first()


def _latest_explanation(db: Session, prediction_id: str | None) -> Optional[AIExplanation]:
    if not prediction_id:
        return None
    return db.query(AIExplanation).filter(AIExplanation.prediction_id == prediction_id).first()


def _latest_path_score(db: Session, entity_key: str) -> Optional[AIAttackPathScore]:
    return (
        db.query(AIAttackPathScore)
        .filter(AIAttackPathScore.entity_key == entity_key)
        .filter(AIAttackPathScore.prediction_type == "risk_gnn")
        .order_by(AIAttackPathScore.window_end.desc())
        .first()
    )


def _latest_fusion_score(db: Session, entity_key: str) -> Optional[AIDecisionFusion]:
    return (
        db.query(AIDecisionFusion)
        .filter(AIDecisionFusion.entity_key == entity_key)
        .filter(AIDecisionFusion.prediction_type == "risk_gnn")
        .order_by(AIDecisionFusion.window_end.desc())
        .first()
    )


def _latest_containment(db: Session, entity_key: str) -> Optional[ContainmentAction]:
    target = entity_key.split(":", 1)[1] if ":" in entity_key else entity_key
    return (
        db.query(ContainmentAction)
        .filter(ContainmentAction.target.in_([entity_key, target]))
        .order_by(ContainmentAction.executed_at.desc(), ContainmentAction.created_at.desc())
        .first()
    )


def _latest_bundle(db: Session, campaign_id: str | None = None) -> Optional[LegalEvidenceBundle]:
    q = db.query(LegalEvidenceBundle)
    if campaign_id:
        q = q.filter(LegalEvidenceBundle.campaign_id == campaign_id)
    return q.order_by(LegalEvidenceBundle.created_at.desc()).first()


def _latest_techniques(db: Session, entity_key: str, window_end: datetime | None) -> List[AIAttackTechniqueHit]:
    q = (
        db.query(AIAttackTechniqueHit)
        .filter(AIAttackTechniqueHit.entity_key == entity_key)
        .filter(AIAttackTechniqueHit.prediction_type == "risk_gnn")
    )
    if window_end is not None:
        q = q.filter(AIAttackTechniqueHit.window_end == window_end)
    return q.order_by(AIAttackTechniqueHit.confidence.desc()).limit(10).all()


def _timing_summary(db: Session, days: int = 14) -> Dict[str, Any]:
    rows = db.execute(
        text(
            """
            SELECT
                EXTRACT(DOW FROM occurred_at AT TIME ZONE 'UTC')::int AS dow,
                EXTRACT(HOUR FROM occurred_at AT TIME ZONE 'UTC')::int AS hour,
                COUNT(*)::int AS n
            FROM event_log
            WHERE occurred_at >= NOW() - INTERVAL '1 day' * :days
              AND event_type = ANY(:event_types)
            GROUP BY 1, 2
            ORDER BY n DESC
            LIMIT 10
            """
        ),
        {"days": days, "event_types": list(SUSPICIOUS_EVENT_TYPES)},
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


def _forecast_summary(db: Session, days: int = 14, horizon: int = 7) -> Dict[str, Any]:
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
        {"days": days},
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


def _format_list(values: Sequence[str]) -> str:
    vals = [str(v) for v in values if str(v).strip()]
    if not vals:
        return "none"
    return ", ".join(vals)


def answer_local_analyst_query(
    *,
    db: Session,
    question: str,
    context: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    entity_key = _pick_entity_key(question, context)
    intent = _detect_intent(question)
    prediction = _latest_prediction(db, entity_key)
    explanation = _latest_explanation(db, prediction.id if prediction else None)
    path_score = _latest_path_score(db, entity_key) if entity_key else None
    fusion = _latest_fusion_score(db, entity_key) if entity_key else None
    containment = _latest_containment(db, entity_key) if entity_key else None
    bundle = _latest_bundle(db)

    if intent == "forecast":
        forecast = _forecast_summary(db)
        if forecast.get("status") == "insufficient_data":
            answer = "Forecast unavailable: there are fewer than 3 daily cyber-risk data points."
        else:
            next_peak = forecast["alert_recommendation"]["peak_forecast_score"]
            answer = (
                f"Risk trend is {forecast['trend_direction']}. "
                f"Peak forecasted cyber-risk signal over the next {forecast['horizon_days']} days is {next_peak:.2f}. "
                f"Recommended posture: {forecast['alert_recommendation']['level']}."
            )
        return {
            "answer": answer,
            "model": settings.ai_copilot_model,
            "intent": intent,
            "sources": ["ai_prediction", "risk_forecast"],
        }

    if intent == "timing":
        timing = _timing_summary(db)
        if timing["samples"] == 0:
            answer = "No suspicious-event timing data is available yet for the requested lookback window."
        else:
            answer = (
                f"Observed suspicious activity peaks on {timing['peak_day']} around {timing['peak_hour']:02d}:00 UTC "
                f"over the current lookback sample ({timing['samples']} grouped observations)."
            )
        return {
            "answer": answer,
            "model": settings.ai_copilot_model,
            "intent": intent,
            "sources": ["event_log"],
        }

    if entity_key and prediction:
        technique_rows = _latest_techniques(db, entity_key, prediction.window_end)
        technique_ids = [str(r.technique_id) for r in technique_rows]
        tools = techniques_to_tools(technique_ids)
        top_reasons = list(prediction.reason_codes or [])[:4]
        evidence_paths = list((explanation.evidence_paths if explanation else []) or [])
        control_list = list((explanation.recommended_controls_json if explanation else []) or [])
        path_value = float(path_score.path_score or 0.0) if path_score else 0.0
        fusion_value = float(fusion.fused_score or 0.0) if fusion else 0.0

        if intent == "tools":
            if tools:
                tool_names = [str(t.get("name") or "unknown") for t in tools[:6]]
                answer = (
                    f"Most likely attacker tooling for {entity_key} is inferred from ATT&CK techniques "
                    f"{_format_list(technique_ids[:6])}: {_format_list(tool_names)}."
                )
            else:
                answer = (
                    f"No concrete tool family is mapped yet for {entity_key}. "
                    f"Observed techniques: {_format_list(technique_ids[:6])}."
                )
        elif intent == "containment":
            if containment:
                answer = (
                    f"Latest containment status for {entity_key}: {containment.action_type} "
                    f"on target {containment.target} is {containment.status}."
                )
            else:
                answer = (
                    f"Recommended actions for {entity_key}: {_format_list(control_list[:5])}. "
                    f"No executed containment action is recorded yet."
                )
        elif intent == "evidence":
            answer = (
                f"{entity_key} scored {float(prediction.score or 0.0):.2f} with reasons {_format_list(top_reasons)}. "
                f"Evidence hashes recorded: {len(list((explanation.evidence_hashes if explanation else []) or []))}. "
                f"Graph evidence paths recorded: {len(evidence_paths)}. "
                f"Latest legal bundle present: {'yes' if bundle else 'no'}."
            )
        else:
            answer = (
                f"{entity_key} is currently scored {float(prediction.score or 0.0):.2f} "
                f"({str(prediction.kill_chain_stage or 'unknown_stage')}). "
                f"Top reasons: {_format_list(top_reasons)}. "
                f"Path score: {path_value:.2f}. "
                f"Fusion score: {fusion_value:.2f}."
            )

        return {
            "answer": answer,
            "model": settings.ai_copilot_model,
            "intent": intent,
            "sources": [
                "ai_prediction",
                "ai_explanation",
                "ai_attack_path_score",
                "ai_decision_fusion",
                "ai_attack_technique_hit",
            ],
        }

    if prediction:
        answer = (
            f"Latest national cyber prediction window is {prediction.window_key} ending "
            f"{prediction.window_end.isoformat()}. Highest observed entity score is "
            f"{float(prediction.score or 0.0):.2f} for {prediction.entity_key}."
        )
    else:
        answer = "No cyber AI predictions are available yet. Train or infer a risk_gnn model first."

    return {
        "answer": answer,
        "model": settings.ai_copilot_model,
        "intent": intent,
        "sources": ["ai_prediction"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

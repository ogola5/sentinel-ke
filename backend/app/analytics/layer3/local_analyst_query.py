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
from app.analytics.layer3.trust_service import build_entity_trust_summary, build_platform_trust_summary
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

PLATFORM_PRESENTATION_FLOW = [
    "Open National Command first to frame the national threat picture and platform readiness.",
    "Move to Entity Investigation to explain one entity in plain language: score, uncertainty, graph links, and actions.",
    "Then show Campaigns and Cases to prove escalation from one entity to a coordinated case.",
    "Close with Reports or Defense so the audience sees operational output, not just analytics.",
]

SCREEN_GUIDE = {
    "command": "Use National Command for national posture, partner freshness, resilience, and governance.",
    "investigation": "Use Entity Investigation for one entity, one explanation, one decision. It is the best screen for live explanation.",
    "campaigns": "Use Campaigns to show how isolated entities become coordinated activity.",
    "cases": "Use Cases to export a structured case packet or STIX artifact.",
    "reports": "Use Reports to show plain-English outputs for leadership, investigators, or oversight.",
    "gnn": "Use GNN Intelligence to explain model quality, uncertainty, real-vs-synthetic mix, and analyst feedback usage.",
    "defense": "Use Defense to show governed action, webhook delivery, and incident-run tracking.",
}


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
        "presentation": sum(w in q for w in ("present", "presentation", "demo", "judge", "show", "screen", "click", "say")),
        "platform": sum(w in q for w in ("platform", "workflow", "what can", "how do i use", "which screen", "where should")),
        "mfa": sum(w in q for w in ("mfa", "otp", "totp", "two-factor", "2fa", "step-up", "authenticator")),
        "gnn": sum(w in q for w in ("gnn", "model", "uncertainty", "confidence", "fused", "score meaning")),
        "graph": sum(w in q for w in ("graph", "path", "hop", "linked", "campaign link", "relationship")),
        "data_realism": sum(w in q for w in ("real data", "synthetic", "realness", "provenance", "mixed data", "public feed")),
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


def _screen_hint_from_question(question: str) -> str | None:
    q = str(question or "").lower()
    for key, text in SCREEN_GUIDE.items():
        if key in q:
            return text
    if "investigate" in q or "entity" in q:
        return SCREEN_GUIDE["investigation"]
    if "report" in q:
        return SCREEN_GUIDE["reports"]
    if "federation" in q:
        return SCREEN_GUIDE["command"]
    return None


def _screen_hint_from_context(context: Mapping[str, Any] | None) -> str | None:
    if not context:
        return None
    current_screen = str(context.get("current_screen") or "").strip().lower()
    if current_screen and current_screen in SCREEN_GUIDE:
        return SCREEN_GUIDE[current_screen]
    screen_title = str(context.get("screen_title") or "").strip()
    screen_purpose = str(context.get("screen_purpose") or "").strip()
    next_screen = str(context.get("next_screen") or "").strip()
    bits = [part for part in (screen_title, screen_purpose) if part]
    if next_screen:
        bits.append(f"Best next move from the UI is {next_screen}.")
    return " ".join(bits) if bits else None


def _presentation_answer(
    *,
    entity_key: str | None,
    trust_summary: Mapping[str, Any] | None,
    platform_summary: Mapping[str, Any] | None,
    screen_hint: str | None,
) -> str:
    parts: list[str] = []
    if entity_key and trust_summary:
        brief = dict(trust_summary.get("operator_brief") or {})
        parts.append(
            f"For a strong live demo, start with Entity Investigation on {entity_key}. "
            f"Lead with: {str(brief.get('headline') or 'Explain the current risk posture in plain language.')}"
        )
        if brief.get("graph_meaning"):
            parts.append(f"When asked about the graph, say: {brief['graph_meaning']}")
        if brief.get("data_realism"):
            parts.append(f"When asked about data quality, say: {brief['data_realism']}")
        if brief.get("containment_readiness"):
            parts.append(f"For response, say: {brief['containment_readiness']}")
    else:
        parts.append("Use this order in the presentation: " + " ".join(PLATFORM_PRESENTATION_FLOW))

    if platform_summary:
        headline = str(platform_summary.get("headline") or "").strip()
        if headline:
            parts.append(f"Platform trust summary right now: {headline}")
        actions = list(platform_summary.get("recommended_actions") or [])
        if actions:
            parts.append(f"Most defensible platform follow-up: {actions[0]}")
    if screen_hint:
        parts.append(screen_hint)
    return " ".join(part for part in parts if part)


def _platform_answer(platform_summary: Mapping[str, Any] | None, screen_hint: str | None) -> str:
    if not platform_summary:
        return screen_hint or "Sentinel-KE is strongest when you show Command, Entity Investigation, Campaigns, Cases, and Reports in one sequence."
    headline = str(platform_summary.get("headline") or "Platform trust summary unavailable.")
    actions = list(platform_summary.get("recommended_actions") or [])
    tail = f" Recommended next step: {actions[0]}." if actions else ""
    hint = f" {screen_hint}" if screen_hint else ""
    return (
        f"{headline}{tail}{hint} "
        "The strongest story is event to entity to campaign to case to report, with governance visible throughout."
    )


def _entity_gnn_answer(
    *,
    entity_key: str,
    prediction: AIPrediction,
    trust_summary: Mapping[str, Any] | None,
    fusion_value: float,
) -> str:
    brief = dict((trust_summary or {}).get("operator_brief") or {})
    severity = str((trust_summary or {}).get("prediction", {}).get("severity") or "unknown")
    headline = str(brief.get("headline") or "")
    graph_meaning = str(brief.get("graph_meaning") or "").strip()
    return (
        f"The GNN is not claiming certainty. It is estimating how risky {entity_key} looks after considering graph neighbourhood, shared behaviour, and prior evidence. "
        f"Current posture is {severity} risk at {float(prediction.score or 0.0):.1f}/100 with uncertainty {float(prediction.uncertainty or 0.0):.2f}. "
        f"Fusion score is {fusion_value:.1f}/100. "
        f"{headline} {graph_meaning}".strip()
    )


def _entity_graph_answer(entity_key: str, trust_summary: Mapping[str, Any] | None) -> str:
    brief = dict((trust_summary or {}).get("operator_brief") or {})
    graph_meaning = str(brief.get("graph_meaning") or "").strip()
    linked = list((trust_summary or {}).get("linked_campaigns") or [])
    linked_sentence = (
        f"{len(linked)} linked campaign indicator(s) currently reference this entity."
        if linked
        else "No linked campaign indicators currently reference this entity."
    )
    if graph_meaning:
        return f"{graph_meaning} {linked_sentence}"
    return (
        f"For {entity_key}, the graph view should be read as relationship evidence: who this entity is connected to, what they shared, "
        "and whether those links look operationally risky."
    )


def _data_realism_answer(
    *,
    trust_summary: Mapping[str, Any] | None,
    platform_summary: Mapping[str, Any] | None,
) -> str:
    if trust_summary:
        brief = dict(trust_summary.get("operator_brief") or {})
        if brief.get("data_realism"):
            return str(brief["data_realism"])
    if platform_summary:
        models = list(platform_summary.get("model_governance") or [])
        if models:
            bits = []
            for row in models[:2]:
                prediction_type = str(row.get("prediction_type") or "model")
                real_ratio = row.get("real_ratio")
                caveat = str(row.get("label_caveat") or "").strip()
                if isinstance(real_ratio, (int, float)):
                    bits.append(f"{prediction_type} real-signal ratio is {round(float(real_ratio) * 100)}%")
                if caveat:
                    bits.append(caveat)
            if bits:
                return " ".join(bits) + " Mixed public threat feeds, synthetic scenarios, and analyst feedback are all visible in governance."
    return "The platform uses mixed public threat feeds, synthetic scenarios, and analyst feedback. The key is to state that provenance honestly, not to overclaim."


def _mfa_answer(context: Mapping[str, Any] | None, screen_hint: str | None) -> str:
    mfa_authenticated = bool((context or {}).get("principal_mfa_authenticated") is True)
    state = (
        "The current session already has recent MFA authentication."
        if mfa_authenticated
        else "The current session is not yet step-up authenticated."
    )
    screen_part = f" {screen_hint}" if screen_hint else ""
    return (
        f"{state} To demonstrate MFA live, use the Assistant security tools to start enrollment, add the TOTP secret to an authenticator app, verify one 6-digit code, "
        "then sign in again so the login flow prompts for the code. After that, central write actions that require step-up are easier to defend in front of judges."
        f"{screen_part}"
    )


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
    trust_summary = None
    platform_summary = None
    screen_hint = _screen_hint_from_question(question) or _screen_hint_from_context(context)

    if entity_key and prediction:
        try:
            trust_summary = build_entity_trust_summary(
                db=db,
                entity_key=entity_key,
                prediction_type=prediction.prediction_type,
            )
        except Exception:
            trust_summary = None

    if intent in {"presentation", "platform", "data_realism"} or not entity_key:
        try:
            platform_summary = build_platform_trust_summary(db=db)
        except Exception:
            platform_summary = None

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

    if intent == "presentation":
        return {
            "answer": _presentation_answer(
                entity_key=entity_key,
                trust_summary=trust_summary,
                platform_summary=platform_summary,
                screen_hint=screen_hint,
            ),
            "model": settings.ai_copilot_model,
            "intent": intent,
            "sources": ["ai_prediction", "trust_summary", "platform_trust_summary"],
        }

    if intent == "platform":
        return {
            "answer": _platform_answer(platform_summary=platform_summary, screen_hint=screen_hint),
            "model": settings.ai_copilot_model,
            "intent": intent,
            "sources": ["platform_trust_summary"],
        }

    if intent == "mfa":
        return {
            "answer": _mfa_answer(context, screen_hint),
            "model": settings.ai_copilot_model,
            "intent": intent,
            "sources": ["auth_workflow", "platform_trust_summary"],
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
        operator_brief = dict((trust_summary or {}).get("operator_brief") or {})

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
            if operator_brief.get("containment_readiness"):
                answer = f"{answer} {operator_brief['containment_readiness']}"
        elif intent == "evidence":
            answer = (
                f"{entity_key} scored {float(prediction.score or 0.0):.2f} with reasons {_format_list(top_reasons)}. "
                f"Evidence hashes recorded: {len(list((explanation.evidence_hashes if explanation else []) or []))}. "
                f"Graph evidence paths recorded: {len(evidence_paths)}. "
                f"Latest legal bundle present: {'yes' if bundle else 'no'}."
            )
        elif intent == "graph":
            answer = _entity_graph_answer(entity_key, trust_summary)
        elif intent == "gnn":
            answer = _entity_gnn_answer(
                entity_key=entity_key,
                prediction=prediction,
                trust_summary=trust_summary,
                fusion_value=fusion_value,
            )
        elif intent == "data_realism":
            answer = _data_realism_answer(trust_summary=trust_summary, platform_summary=platform_summary)
        else:
            if operator_brief:
                answer = " ".join(
                    [
                        str(operator_brief.get("headline") or "").strip(),
                        str(operator_brief.get("graph_meaning") or "").strip(),
                        str(operator_brief.get("containment_readiness") or "").strip(),
                        str(operator_brief.get("data_realism") or "").strip(),
                    ]
                ).strip()
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
        answer = _platform_answer(platform_summary=platform_summary, screen_hint=screen_hint)
    else:
        answer = (
            "No cyber AI predictions are available yet. Bootstrap demo data or run a risk_gnn training cycle first, "
            "then use Entity Investigation to explain one entity clearly."
        )

    return {
        "answer": answer,
        "model": settings.ai_copilot_model,
        "intent": intent,
        "sources": ["ai_prediction", "platform_trust_summary"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

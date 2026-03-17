from app.analytics.layer3.local_analyst_query import _detect_intent, _pick_entity_key
from app.api.ai import CopilotQueryRequest, nl_copilot_query


def test_detect_intent_prefers_forecast_keywords():
    assert _detect_intent("forecast the attack likelihood for next week") == "forecast"


def test_detect_intent_handles_presentation_keywords():
    assert _detect_intent("what should I show in the demo presentation screen first") == "presentation"


def test_detect_intent_handles_mfa_keywords():
    assert _detect_intent("how do I show MFA and step-up in the demo") == "mfa"


def test_pick_entity_key_prefers_context_over_question():
    out = _pick_entity_key(
        "What should I do with ip:41.90.0.1?",
        {"entity_key": "service_id:core-banking"},
    )
    assert out == "service_id:core-banking"


def test_nl_copilot_query_uses_local_engine(monkeypatch):
    monkeypatch.setattr(
        "app.api.ai.answer_local_analyst_query",
        lambda **kwargs: {
            "answer": "Local analyst response",
            "model": "sentinel-local-analyst-v1",
            "intent": "summary",
            "sources": ["ai_prediction"],
        },
    )

    out = nl_copilot_query(
        CopilotQueryRequest(question="Summarize the latest risk."),
        db=object(),
    )

    assert out["answer"] == "Local analyst response"
    assert out["model"] == "sentinel-local-analyst-v1"
    assert out["sources"] == ["ai_prediction"]

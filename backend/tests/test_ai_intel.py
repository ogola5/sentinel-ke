from app.analytics.layer3.ai_intel import (
    build_counterfactual,
    event_types_to_attack_techniques,
    event_types_to_kill_chain_stage,
    reason_codes_to_d3fend_controls,
)


def test_event_types_to_attack_techniques_maps_known_events():
    out = event_types_to_attack_techniques(
        {
            "PHISHING_MESSAGE_EVENT": 3,
            "DDOS_SIGNAL_EVENT": 2,
        }
    )
    ids = {x["technique_id"] for x in out}
    assert "T1566" in ids
    assert "T1498" in ids


def test_event_types_to_kill_chain_stage_picks_highest_precedence():
    out = event_types_to_kill_chain_stage(
        {
            "PHISHING_MESSAGE_EVENT": 2,
            "TRANSACTION_EVENT": 1,
        }
    )
    # actions-on-objectives outranks initial-access in precedence
    assert out == "actions-on-objectives"


def test_reason_codes_to_d3fend_controls_dedupes():
    out = reason_codes_to_d3fend_controls(
        [
            "DDOS_ALERT_ACTIVE",
            "DDOS_ALERT_ACTIVE",
            "CAMPAIGN_LINKED",
        ]
    )
    assert "D3-NTA" in out
    assert "D3-INV" in out
    assert len(out) == len(set(out))


def test_build_counterfactual_returns_shift_direction():
    out = build_counterfactual(probability=0.82, threshold_score=75.0, top_feature_hint="event_count")
    assert out["recommended_direction"] == "decrease"
    assert out["required_probability_shift"] >= 0.0

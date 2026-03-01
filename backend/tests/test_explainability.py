from app.analytics.explainability import (
    FEATURE_NAMES,
    heuristic_signal_attributions,
    summarize_feature_attributions,
    summarize_group_scores,
    top_feature_hint,
)


def test_summarize_feature_attributions_ranks_by_absolute_contribution():
    values = [0.0] * len(FEATURE_NAMES)
    contribs = [0.0] * len(FEATURE_NAMES)
    values[10] = 2.0
    values[18] = 1.0
    contribs[10] = 0.3
    contribs[18] = -0.8

    out = summarize_feature_attributions(
        feature_values=values,
        feature_contributions=contribs,
        top_k=2,
    )
    assert len(out) == 2
    assert out[0]["feature"] == "chain_score"
    assert out[0]["direction"] == "decrease_risk"
    assert out[1]["feature"] == "log_event_count"


def test_heuristic_signal_attributions_captures_event_and_flags():
    out = heuristic_signal_attributions(
        event_count=25,
        source_count=4,
        event_types={"DDOS_SIGNAL_EVENT": 10, "SIM_SWAP_EVENT": 2},
        risk_flags=["DDOS_ALERT_SERVICE", "CAMPAIGN_ENTITY"],
        top_k=5,
    )
    names = {row["feature"] for row in out}
    assert "log_event_count" in names
    assert "event_count_ddos_signal_event" in names
    assert "flag_ddos_alert" in names


def test_group_scores_and_top_hint():
    attributions = [
        {"feature": "log_event_count", "group": "volume", "contribution": 0.4, "abs_contribution": 0.4},
        {"feature": "chain_score", "group": "temporal", "contribution": 0.7, "abs_contribution": 0.7},
    ]
    groups = summarize_group_scores(attributions)
    assert groups[0]["group"] == "temporal"
    assert top_feature_hint(attributions) == "log_event_count"

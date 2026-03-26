from datetime import datetime, timezone

from app.analytics.ai_models import GraphFeatureSnapshot
from app.analytics.layer3.ai_inference_worker import (
    _default_threshold_score,
    _gnn_reason_codes,
)


def _snapshot(entity_type: str = "ip") -> GraphFeatureSnapshot:
    now = datetime.now(timezone.utc)
    return GraphFeatureSnapshot(
        entity_key=f"{entity_type}:demo",
        entity_type=entity_type,
        window_key="Wmid",
        window_start=now,
        window_end=now,
        degree=3,
        weighted_degree=3,
        event_count=9,
        first_seen=now,
        last_seen=now,
        risk_flags=["CAMPAIGN_ENTITY"],
        features={"source_count": 2, "event_types": {"DFIR_FINDING_EVENT": 1}},
    )


def test_default_threshold_score_varies_by_entity_type():
    assert _default_threshold_score("ip") == 78.0
    assert _default_threshold_score("phone_h") == 70.0
    assert _default_threshold_score("supplier") == 75.0


def test_gnn_reason_codes_include_threshold_position():
    snap = _snapshot()
    above = _gnn_reason_codes(0.82, snap, threshold_score=78.0)
    below = _gnn_reason_codes(0.62, snap, threshold_score=78.0)

    assert "ABOVE_ENTITY_THRESHOLD" in above
    assert "BELOW_ENTITY_THRESHOLD" not in above
    assert "BELOW_ENTITY_THRESHOLD" in below
    assert "ABOVE_ENTITY_THRESHOLD" not in below

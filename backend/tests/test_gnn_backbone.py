from app.analytics.layer3.gnn_backbone import (
    _extract_truth_label,
    build_feature_vector,
    collapse_edges,
    entity_key_to_neo4j_ref,
    weak_label,
)


def test_weak_label_prioritizes_risk_flags():
    y = weak_label(
        risk_flags=["CAMPAIGN_ENTITY"],
        event_count=1,
        source_count=1,
    )
    assert y == 1


def test_weak_label_uses_volume_fallback():
    y = weak_label(
        risk_flags=[],
        event_count=30,
        source_count=4,
    )
    assert y == 1


def test_weak_label_low_signal_is_negative():
    y = weak_label(
        risk_flags=[],
        event_count=3,
        source_count=1,
    )
    assert y == 0


def test_feature_vector_shape_and_recency():
    from app.analytics.layer3.gnn_backbone import FEATURE_DIM
    v = build_feature_vector(
        entity_type="ip",
        event_count=10,
        source_count=3,
        degree=4,
        weighted_degree=6,
        risk_flags=["VPN_CLUSTER_MEMBER"],
        features={
            "last_seen_age_sec": 60,
            "event_types": {
                "DDOS_SIGNAL_EVENT": 2,
                "TRANSACTION_EVENT": 5,
            },
        },
    )
    assert len(v) == FEATURE_DIM
    # Recency signal is in Block 2 (temporal), should be > 0 for recent activity
    assert v[15] > 0
    # VPN_CLUSTER_MEMBER flag is in Block 3 risk flags (index 21)
    assert v[21] == 1.0


def test_collapse_edges_merges_bidirectional_duplicates():
    edges = [
        ("a", "b", 2.0),
        ("b", "a", 1.5),
        ("a", "c", 1.0),
    ]
    out = collapse_edges(edges)
    assert out[0][0] == "a"
    assert out[0][1] == "b"
    assert out[0][2] == 3.5
    assert len(out) == 2


def test_entity_key_to_neo4j_ref_mapping():
    assert entity_key_to_neo4j_ref("ip:203.0.113.1") == ("IP", "203.0.113.1")
    assert entity_key_to_neo4j_ref("service_id:core-payments") == ("Service", "core-payments")
    assert entity_key_to_neo4j_ref("account_h:abc123") == ("Account", "account_h:abc123")
    assert entity_key_to_neo4j_ref("unknown:x1") is None


def test_extract_truth_label_accepts_confirmed_positive_variants():
    assert _extract_truth_label({"confirmed_incident": True}) == 1
    assert _extract_truth_label({"ground_truth_label": "malicious"}) == 1
    assert _extract_truth_label({"incident_disposition": "true_positive"}) == 1


def test_extract_truth_label_accepts_confirmed_negative_variants():
    assert _extract_truth_label({"confirmed_benign": True}) == 0
    assert _extract_truth_label({"ground_truth_label": "benign"}) == 0
    assert _extract_truth_label({"case_outcome": "false_positive"}) == 0

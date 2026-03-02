from app.analytics.layer3.gnn_train_worker import (
    _compute_provenance_metrics,
    _normalize_provenance_tag,
)


def test_normalize_provenance_tag_defaults_unknown():
    assert _normalize_provenance_tag("real") == "real"
    assert _normalize_provenance_tag("synthetic") == "synthetic"
    assert _normalize_provenance_tag("mixed") == "mixed"
    assert _normalize_provenance_tag("n/a") == "unknown"
    assert _normalize_provenance_tag(None) == "unknown"


def test_compute_provenance_metrics_summarizes_mix_and_gate_inputs():
    node_meta = [
        {"provenance_tag": "real", "real_signal_ratio": 1.0},
        {"provenance_tag": "mixed", "real_signal_ratio": 0.5},
        {"provenance_tag": "synthetic", "real_signal_ratio": 0.0},
        {"provenance_tag": "unknown", "real_signal_ratio": 0.0},
    ]
    probs = [0.8, 0.7, 0.9, 0.1]
    out = _compute_provenance_metrics(node_meta=node_meta, probabilities=probs, threshold_score=70.0)

    assert out["counts"]["real"] == 1
    assert out["counts"]["mixed"] == 1
    assert out["counts"]["synthetic"] == 1
    assert out["high_risk_counts"]["synthetic"] == 1
    assert out["real_ratio"] == 0.5  # (real + mixed) / total
    assert out["avg_real_signal_ratio"] == 0.375

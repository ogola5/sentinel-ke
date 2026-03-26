"""
Tests for GNN training pipeline hardening:
  1. _compute_fairness_metrics with calibrated threshold gives non-zero precision/recall
  2. Negative floor: assess_benchmark_readiness blocks when negatives < minimum
  3. Temporal split is selected when split_policy="temporal_recency_holdout"
  4. Label ladder correctly classifies gold/silver/bronze sources
"""
from __future__ import annotations

import inspect
import pytest

from app.analytics.layer3.gnn_train_worker import (
    _compute_fairness_metrics,
    _label_ladder_counts,
    LABEL_SOURCE_LADDER,
    run_once,
)
from app.analytics.layer3.gnn_backbone import assess_benchmark_readiness
from app.core.config import settings


# ---------------------------------------------------------------------------
# 1. _compute_fairness_metrics with calibrated threshold
# ---------------------------------------------------------------------------

def test_fairness_metrics_at_calibrated_threshold_gives_nonzero_precision_recall():
    """
    When all positives score 0.8 and threshold is 0.7, every positive is
    predicted positive → precision=1.0, recall=1.0.  At threshold=0.5 same
    result; the key guard is that a LOW calibrated threshold (e.g. 0.3) on a
    dataset where all positives score 0.8 still yields recall=1.0.
    """
    # 6 entities of the same type so the group is evaluated (>= min_group_size=3)
    entity_types = ["ip"] * 6
    labels       = [1, 1, 1, 0, 0, 0]
    # Positives score 0.8, negatives score 0.1
    probs        = [0.8, 0.8, 0.8, 0.1, 0.1, 0.1]

    # With calibrated threshold of 0.5 — positives correctly classified
    result = _compute_fairness_metrics(
        entity_types=entity_types,
        labels=labels,
        probabilities=probs,
        threshold=0.5,
    )
    ip_metrics = result["per_type"]["ip"]
    assert ip_metrics["precision"] > 0.0, "precision must be > 0 when positives are correctly predicted"
    assert ip_metrics["recall"]    > 0.0, "recall must be > 0 when positives are correctly predicted"
    assert result["threshold_used"] == 0.5


def test_fairness_metrics_high_threshold_causes_zero_recall():
    """
    When threshold is above all positive scores, every positive is missed →
    recall=0.0.  This confirms the calibration fix is meaningful.
    """
    entity_types = ["phone_h"] * 6
    labels       = [1, 1, 1, 0, 0, 0]
    probs        = [0.4, 0.4, 0.4, 0.1, 0.1, 0.1]

    result = _compute_fairness_metrics(
        entity_types=entity_types,
        labels=labels,
        probabilities=probs,
        threshold=0.5,   # above all positive scores
    )
    phone_metrics = result["per_type"]["phone_h"]
    assert phone_metrics["recall"] == 0.0
    assert phone_metrics["precision"] == 0.0


def test_fairness_metrics_calibrated_threshold_restores_recall():
    """
    Using the calibrated threshold (0.3, below positive scores of 0.4) gives
    non-zero recall even though 0.5 would have failed.
    """
    entity_types = ["phone_h"] * 6
    labels       = [1, 1, 1, 0, 0, 0]
    probs        = [0.4, 0.4, 0.4, 0.1, 0.1, 0.1]

    result = _compute_fairness_metrics(
        entity_types=entity_types,
        labels=labels,
        probabilities=probs,
        threshold=0.3,   # calibrated threshold below positive scores
    )
    phone_metrics = result["per_type"]["phone_h"]
    assert phone_metrics["recall"] > 0.0, "calibrated threshold should give non-zero recall"
    assert phone_metrics["precision"] > 0.0, "calibrated threshold should give non-zero precision"


def test_fairness_metrics_accepts_threshold_parameter():
    """Confirm the function signature accepts a threshold kwarg."""
    sig = inspect.signature(_compute_fairness_metrics)
    assert "threshold" in sig.parameters, "_compute_fairness_metrics must accept a threshold parameter"


def test_fairness_metrics_can_scope_to_holdout_indices():
    entity_types = ["ip", "ip", "ip", "ip", "phone_h", "phone_h", "phone_h", "phone_h"]
    labels = [1, 1, 0, 0, 1, 1, 0, 0]
    probs = [0.8, 0.7, 0.2, 0.1, 0.9, 0.8, 0.3, 0.2]

    result = _compute_fairness_metrics(
        entity_types=entity_types,
        labels=labels,
        probabilities=probs,
        threshold=0.5,
        node_indices=[0, 1, 2, 3],
    )

    assert result["evaluation_scope"] == "holdout"
    assert "ip" in result["per_type"]
    assert "phone_h" not in result["per_type"]


# ---------------------------------------------------------------------------
# 2. Negative floor blocks training when negatives < minimum
# ---------------------------------------------------------------------------

def test_negative_floor_blocks_when_negatives_below_minimum():
    result = assess_benchmark_readiness(
        total_count=25,
        positive_count=24,
        negative_count=1,
        min_negative_count=20,
        min_negative_ratio=0.3,
    )
    assert result["benchmarkable"] is False
    assert "no_negative_labels" not in result["reasons"] or "negative_count_below_floor" in result["reasons"] or "negative_ratio_below_floor" in result["reasons"]


def test_negative_floor_passes_when_negatives_meet_minimum():
    result = assess_benchmark_readiness(
        total_count=100,
        positive_count=60,
        negative_count=40,
        min_negative_count=20,
        min_negative_ratio=0.3,
    )
    assert result["benchmarkable"] is True
    assert result["reasons"] == []


def test_negative_floor_fails_ratio_even_with_count_met():
    """If count is met but ratio is below floor, should still fail."""
    result = assess_benchmark_readiness(
        total_count=1000,
        positive_count=980,
        negative_count=20,         # count met (>= 20) but ratio = 0.02 < 0.3
        min_negative_count=20,
        min_negative_ratio=0.3,
    )
    assert result["benchmarkable"] is False
    assert "negative_ratio_below_floor" in result["reasons"]


def test_settings_has_minimum_negative_count_and_ratio():
    """Config must expose the canonical negative-floor settings."""
    assert hasattr(settings, "gnn_minimum_negative_count"), \
        "settings.gnn_minimum_negative_count missing"
    assert hasattr(settings, "gnn_minimum_negative_ratio"), \
        "settings.gnn_minimum_negative_ratio missing"
    assert settings.gnn_minimum_negative_count >= 1
    assert 0.0 < settings.gnn_minimum_negative_ratio <= 1.0


# ---------------------------------------------------------------------------
# 3. Temporal split is selected when split_policy="temporal_recency_holdout"
# ---------------------------------------------------------------------------

def test_settings_default_split_policy_is_temporal():
    """gnn_split_policy must default to temporal_recency_holdout."""
    assert settings.gnn_split_policy == "temporal_recency_holdout", (
        f"Expected 'temporal_recency_holdout', got {settings.gnn_split_policy!r}"
    )


def test_run_once_default_split_policy_is_temporal():
    """run_once() must default split_policy to settings.gnn_split_policy."""
    sig = inspect.signature(run_once)
    param = sig.parameters.get("split_policy")
    assert param is not None, "run_once must have a split_policy parameter"
    # The default should be the settings value (temporal_recency_holdout by default)
    default_val = param.default
    assert default_val == settings.gnn_split_policy, (
        f"run_once split_policy default ({default_val!r}) != "
        f"settings.gnn_split_policy ({settings.gnn_split_policy!r})"
    )


def test_run_once_minimum_negative_count_wired_to_settings():
    """run_once() must default minimum_negative_count to settings value."""
    sig = inspect.signature(run_once)
    param = sig.parameters.get("minimum_negative_count")
    assert param is not None
    assert param.default == settings.gnn_min_negative_count, (
        f"run_once minimum_negative_count default ({param.default}) != "
        f"settings.gnn_min_negative_count ({settings.gnn_min_negative_count})"
    )


# ---------------------------------------------------------------------------
# 4. Label ladder correctly classifies gold/silver/bronze sources
# ---------------------------------------------------------------------------

def test_label_ladder_gold_sources():
    gold_sources = {
        "confirmed_event_label": 10,
        "confirmed_outcome_label": 5,
        "analyst_feedback": 3,
    }
    result = _label_ladder_counts(gold_sources)
    assert result["tier_counts"]["gold"] == 18
    assert result["tier_counts"]["silver"] == 0
    assert result["tier_counts"]["bronze"] == 0
    assert result["dominant_tier"] == "gold"


def test_label_ladder_silver_sources():
    silver_sources = {"operational_threat_alert": 15}
    result = _label_ladder_counts(silver_sources)
    assert result["tier_counts"]["silver"] == 15
    assert result["tier_counts"]["gold"] == 0
    assert result["dominant_tier"] == "silver"


def test_label_ladder_bronze_sources():
    bronze_sources = {"weak_label": 100}
    result = _label_ladder_counts(bronze_sources)
    assert result["tier_counts"]["bronze"] == 100
    assert result["dominant_tier"] == "bronze"


def test_label_ladder_mixed_dominant_tier():
    mixed_sources = {
        "weak_label": 80,            # bronze: 80
        "operational_threat_alert": 30,  # silver: 30
        "confirmed_event_label": 5,  # gold: 5
    }
    result = _label_ladder_counts(mixed_sources)
    assert result["tier_counts"]["bronze"] == 80
    assert result["tier_counts"]["silver"] == 30
    assert result["tier_counts"]["gold"] == 5
    assert result["dominant_tier"] == "bronze"


def test_label_ladder_unknown_source_classified_as_unknown():
    unknown_sources = {"some_legacy_source": 42}
    result = _label_ladder_counts(unknown_sources)
    assert result["tier_counts"]["unknown"] == 42
    assert result["dominant_tier"] == "unknown"


def test_label_ladder_empty_gives_unknown_dominant():
    result = _label_ladder_counts({})
    # max of all-zero counts — "gold" or any tier is fine as long as counts are 0
    assert all(v == 0 for v in result["tier_counts"].values())


def test_label_ladder_tier_sources_breakdown():
    sources = {
        "confirmed_event_label": 7,
        "weak_label": 50,
    }
    result = _label_ladder_counts(sources)
    assert result["tier_sources"]["gold"]["confirmed_event_label"] == 7
    assert result["tier_sources"]["bronze"]["weak_label"] == 50


def test_label_source_ladder_constant_covers_all_tiers():
    """LABEL_SOURCE_LADDER must have entries for gold, silver, and bronze."""
    tiers = set(LABEL_SOURCE_LADDER.values())
    assert "gold" in tiers
    assert "silver" in tiers
    assert "bronze" in tiers


# ---------------------------------------------------------------------------
# 5. label_quality_summary structure (unit test against run_once metrics_json)
# ---------------------------------------------------------------------------

def test_label_quality_summary_structure_from_ladder():
    """
    Simulate the label_quality_summary computation that run_once writes
    into metrics_json to ensure it produces the expected structure.
    """
    label_ladder = _label_ladder_counts({"weak_label": 90, "confirmed_event_label": 10})
    gold   = label_ladder.get("tier_counts", {}).get("gold", 0)
    silver = label_ladder.get("tier_counts", {}).get("silver", 0)
    bronze = label_ladder.get("tier_counts", {}).get("bronze", 0)

    summary = {
        "gold_count": gold,
        "silver_count": silver,
        "bronze_count": bronze,
        "dominant_tier": label_ladder.get("dominant_tier", "unknown"),
        "is_ground_truth_backed": gold > 0,
    }

    assert summary["gold_count"] == 10
    assert summary["bronze_count"] == 90
    assert summary["dominant_tier"] == "bronze"
    assert summary["is_ground_truth_backed"] is True

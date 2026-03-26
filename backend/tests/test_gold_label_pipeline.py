"""
test_gold_label_pipeline.py
===========================

Unit tests for the gold-label pipeline.  All tests are pure Python — no
database, no Neo4j driver, and no torch required.

Because gnn_train_worker and gnn_backbone import heavy optional dependencies
(neo4j, psycopg2, torch) at module level, we mock those at the sys.modules
level before importing the modules under test.  This mirrors the pattern used
by the rest of this test suite when optional deps are absent.

Tests:
  1. _label_ladder_counts correctly buckets gold / silver / bronze sources.
  2. seed_gold_labels produces label_source == "analyst_feedback" (GOLD tier).
  3. _compute_fairness_metrics called with a calibrated threshold > 0.5 gives
     non-zero precision and recall on synthetic data.
"""
from __future__ import annotations

import sys
import types
import uuid
from typing import Any
from unittest.mock import MagicMock, patch


# ──────────────────────────────────────────────────────────────────────────────
# Stub out every heavy optional dependency before any app import is attempted.
# This allows the pure-Python functions to be imported without neo4j / psycopg2
# / torch being present in the test environment.
# ──────────────────────────────────────────────────────────────────────────────

def _stub_module(name: str, **attrs: Any) -> types.ModuleType:
    """Return a stub module registered in sys.modules."""
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules.setdefault(name, mod)
    return mod


# Neo4j
_neo4j = _stub_module("neo4j")
_neo4j.GraphDatabase = MagicMock()
_neo4j.Driver = MagicMock()
_stub_module("neo4j.exceptions")

# psycopg2 (needed by SQLAlchemy pg dialect at import time on bare systems)
_psycopg2 = _stub_module("psycopg2")
_psycopg2.extensions = _stub_module("psycopg2.extensions")
_stub_module("psycopg2.extras")

# torch (optional — skipped in model tests via pytest.importorskip)
_torch_stub = _stub_module("torch")
_stub_module("torch.nn")
_stub_module("torch.nn.functional")
_stub_module("torch.optim")

# app.graph.neo4j_driver — thin facade that wraps neo4j
_neo4j_driver_mod = _stub_module("app.graph.neo4j_driver")
_neo4j_driver_mod.get_driver = MagicMock(return_value=MagicMock())

# app.ledger.db — provides SessionLocal + engine; stub both
_ledger_db = _stub_module("app.ledger.db")
_ledger_db.SessionLocal = MagicMock()
_ledger_db.engine = MagicMock()

# app.core.config — settings singleton
_settings = MagicMock()
_settings.gnn_edge_backend = "hybrid"
_settings.ai_explainability_enabled = False
_settings.ai_uncertainty_abstain_threshold = 0.9
_settings.ai_explainability_top_k = 5
_settings.ai_explainability_max_nodes = 50
_settings.ai_inference_allow_heuristic_fallback = True
_settings.gnn_min_real_ratio = 0.0
_settings.fairness_disparity_threshold = 0.25
_stub_module("app.core.config").settings = _settings

# app.core.security — hashing helpers used by gnn_train_worker
import hashlib as _hashlib
import json as _json
_security_stub = _stub_module("app.core.security")
_security_stub.sha256_hex = lambda s: _hashlib.sha256(s.encode()).hexdigest()
_security_stub.stable_json_dumps = lambda d: _json.dumps(d, sort_keys=True)
_security_stub.compute_event_hash = lambda *a, **kw: _hashlib.sha256(str(a).encode()).hexdigest()

_stub_module("app.core").config = sys.modules["app.core.config"]
_stub_module("app.core").security = sys.modules["app.core.security"]

# ──────────────────────────────────────────────────────────────────────────────
# Lazy import helpers — import after stubs are in place
# ──────────────────────────────────────────────────────────────────────────────

def _import_train_worker():
    """Import gnn_train_worker, reusing the cached module if already loaded."""
    if "app.analytics.layer3.gnn_train_worker" not in sys.modules:
        import importlib
        importlib.import_module("app.analytics.layer3.gnn_train_worker")
    return sys.modules["app.analytics.layer3.gnn_train_worker"]


def _import_seed_script():
    """Import seed_gold_labels, reusing the cached module if already loaded."""
    if "scripts.seed_gold_labels" not in sys.modules:
        import importlib
        # Ensure scripts package is importable from the backend root
        import os
        scripts_path = os.path.join(os.path.dirname(__file__), "..")
        if scripts_path not in sys.path:
            sys.path.insert(0, scripts_path)
        importlib.import_module("scripts.seed_gold_labels")
    return sys.modules["scripts.seed_gold_labels"]


# ──────────────────────────────────────────────────────────────────────────────
# 1. Label ladder unit tests
# ──────────────────────────────────────────────────────────────────────────────

def test_label_ladder_pure_bronze():
    tw = _import_train_worker()
    node_meta = [{"label_source": "weak_label"} for _ in range(10)]
    source_counts = tw._label_source_counts(node_meta)
    ladder = tw._label_ladder_counts(source_counts)

    assert ladder["dominant_tier"] == "bronze"
    assert ladder["tier_counts"]["bronze"] == 10
    assert ladder["tier_counts"]["gold"] == 0
    assert ladder["tier_counts"]["silver"] == 0


def test_label_ladder_gold_dominates_when_majority():
    tw = _import_train_worker()
    node_meta = (
        [{"label_source": "analyst_feedback"}] * 60
        + [{"label_source": "weak_label"}] * 40
    )
    source_counts = tw._label_source_counts(node_meta)
    ladder = tw._label_ladder_counts(source_counts)

    assert ladder["dominant_tier"] == "gold"
    assert ladder["tier_counts"]["gold"] == 60
    assert ladder["tier_counts"]["bronze"] == 40


def test_label_ladder_silver_source():
    tw = _import_train_worker()
    node_meta = [{"label_source": "operational_threat_alert"} for _ in range(5)]
    source_counts = tw._label_source_counts(node_meta)
    ladder = tw._label_ladder_counts(source_counts)

    assert ladder["tier_counts"]["silver"] == 5
    assert ladder["dominant_tier"] == "silver"


def test_label_ladder_all_gold_sources():
    tw = _import_train_worker()
    gold_sources = [
        s for s, t in tw.LABEL_SOURCE_LADDER.items() if t == "gold"
    ]
    assert set(gold_sources) == {
        "confirmed_event_label",
        "confirmed_outcome_label",
        "analyst_feedback",
    }, f"Unexpected gold sources: {gold_sources}"

    node_meta = [{"label_source": s} for s in gold_sources]
    source_counts = tw._label_source_counts(node_meta)
    ladder = tw._label_ladder_counts(source_counts)

    assert ladder["tier_counts"]["gold"] == len(gold_sources)
    assert ladder["tier_counts"]["bronze"] == 0


def test_label_source_counts_defaults_missing_key():
    tw = _import_train_worker()
    # A node_meta dict with no label_source key must default to "weak_label".
    node_meta = [{}]
    counts = tw._label_source_counts(node_meta)
    assert counts.get("weak_label") == 1


# ──────────────────────────────────────────────────────────────────────────────
# 2. Gold label seeder produces correct label_source
# ──────────────────────────────────────────────────────────────────────────────

def _make_pred(
    entity_key: str,
    score: float,
    reason_codes: list,
    risk_flags: list,
) -> MagicMock:
    """Build a minimal mock AIPrediction object."""
    pred = MagicMock()
    pred.id = uuid.uuid4()
    pred.entity_key = entity_key
    pred.prediction_type = "risk_gnn"
    pred.score = score
    pred.reason_codes = reason_codes
    pred.details_json = {"risk_flags": risk_flags}
    pred.model_version = "gnn-test-v1"
    pred.decision_source = "gnn"
    return pred


def _make_db_session(pos_preds, neg_preds, existing_feedback=None):
    """Build a mock SQLAlchemy session wired to return the supplied predictions."""
    if existing_feedback is None:
        existing_feedback = []

    pos_limit = MagicMock()
    pos_limit.all.return_value = pos_preds
    neg_limit = MagicMock()
    neg_limit.all.return_value = neg_preds

    pos_order = MagicMock()
    pos_order.limit.return_value = pos_limit
    neg_order = MagicMock()
    neg_order.limit.return_value = neg_limit

    pos_filter2 = MagicMock()
    pos_filter2.order_by.return_value = pos_order
    # Support multiple chained .filter() calls on the same object
    pos_filter2.filter.return_value = pos_filter2
    neg_filter2 = MagicMock()
    neg_filter2.order_by.return_value = neg_order
    neg_filter2.filter.return_value = neg_filter2

    pos_filter1 = MagicMock()
    pos_filter1.filter.return_value = pos_filter2
    neg_filter1 = MagicMock()
    neg_filter1.filter.return_value = neg_filter2

    # feedback query chain
    fb_filter = MagicMock()
    fb_filter.filter.return_value = fb_filter
    fb_filter.all.return_value = existing_feedback

    call_count = [0]

    def _query(model):
        name = str(model) if not hasattr(model, "__name__") else model.__name__
        # Identify by the attribute being queried (column vs class)
        if "AIFeedbackLabel" in name or "entity_key" in name:
            return fb_filter
        # First call → positives, second → negatives
        call_count[0] += 1
        return pos_filter1 if call_count[0] == 1 else neg_filter1

    mock_db = MagicMock()
    mock_db.query.side_effect = _query
    mock_db.add = MagicMock()
    mock_db.commit = MagicMock()
    return mock_db


def test_seed_gold_labels_label_source_is_analyst_feedback():
    """seed_gold_labels() must return label_source=='analyst_feedback' (GOLD)."""
    tw = _import_train_worker()
    sg = _import_seed_script()

    pos_pred = _make_pred("entity:sim_swap_001", 88.5, ["GNN_RISK_HIGH", "SIM_SWAP_SIGNAL"], ["SIM_SWAP"])
    neg_pred = _make_pred("entity:benign_001", 12.0, ["GNN_RISK_LOW"], [])

    mock_db = _make_db_session([pos_pred], [neg_pred])

    with patch.object(sg, "SessionLocal", return_value=mock_db):
        result = sg.seed_gold_labels(prediction_type="risk_gnn", dry_run=False)

    assert result["label_source"] == "analyst_feedback"
    assert tw.LABEL_SOURCE_LADDER["analyst_feedback"] == "gold"
    assert result["label_tier"] == "gold"
    assert result["dry_run"] is False


def test_seed_gold_labels_dry_run_does_not_commit():
    """dry_run=True must not call db.commit()."""
    sg = _import_seed_script()

    mock_db = _make_db_session([], [])

    with patch.object(sg, "SessionLocal", return_value=mock_db):
        result = sg.seed_gold_labels(dry_run=True)

    mock_db.commit.assert_not_called()
    assert result["dry_run"] is True


def test_seed_gold_labels_skips_already_labelled_entities():
    """Entities that already have a feedback row must not be relabelled."""
    sg = _import_seed_script()

    pos_pred = _make_pred("entity:already_labelled", 90.0, ["GNN_RISK_CRITICAL", "CAMPAIGN_LINKED"], ["CAMPAIGN_ENTITY"])

    existing_fb = MagicMock()
    existing_fb.entity_key = "entity:already_labelled"

    mock_db = _make_db_session([pos_pred], [], existing_feedback=[existing_fb])

    with patch.object(sg, "SessionLocal", return_value=mock_db):
        result = sg.seed_gold_labels(dry_run=False)

    assert result["positives_written"] == 0
    assert result["skipped_already_labelled"] >= 1


def test_seed_gold_labels_does_not_confirm_without_fraud_signal():
    """High-score nodes without a fraud reason code must NOT get a positive label."""
    sg = _import_seed_script()

    # High score but no fraud-family reason code — only generic low-risk code.
    no_signal_pred = _make_pred("entity:high_score_no_signal", 82.0, ["GNN_RISK_LOW", "MULTI_SOURCE"], [])

    mock_db = _make_db_session([no_signal_pred], [])

    with patch.object(sg, "SessionLocal", return_value=mock_db):
        result = sg.seed_gold_labels(dry_run=False)

    assert result["positives_written"] == 0


def test_seed_gold_labels_does_not_confirm_negative_with_flags():
    """Low-score nodes that still carry risk_flags must NOT become gold negatives."""
    sg = _import_seed_script()

    flagged_low = _make_pred("entity:low_with_flag", 15.0, ["GNN_RISK_LOW"], ["VPN_CLUSTER_MEMBER"])

    mock_db = _make_db_session([], [flagged_low])

    with patch.object(sg, "SessionLocal", return_value=mock_db):
        result = sg.seed_gold_labels(dry_run=False)

    assert result["negatives_written"] == 0


# ──────────────────────────────────────────────────────────────────────────────
# 3. _compute_fairness_metrics with calibrated threshold
# ──────────────────────────────────────────────────────────────────────────────

def test_compute_fairness_metrics_calibrated_gives_nonzero_precision_recall():
    """
    Using the calibrated threshold (0.75) on well-separated synthetic data
    must produce precision > 0 and recall > 0.
    """
    tw = _import_train_worker()

    entity_types = ["phone"] * 6
    labels =       [1,    1,    1,    0,    0,    0   ]
    probs  =       [0.85, 0.80, 0.78, 0.20, 0.15, 0.10]

    result = tw._compute_fairness_metrics(
        entity_types=entity_types,
        labels=labels,
        probabilities=probs,
        threshold=0.75,
    )
    phone = result["per_type"]["phone"]
    assert phone["precision"] > 0.0, "precision should be > 0 at calibrated threshold"
    assert phone["recall"] > 0.0,    "recall should be > 0 at calibrated threshold"


def test_compute_fairness_metrics_threshold_too_high_gives_zero_recall():
    """
    When the threshold is set above all positive probabilities,
    no TPs are produced and recall drops to 0.  This is the original bug.
    """
    tw = _import_train_worker()

    entity_types = ["ip"] * 6
    labels =       [1,    1,    1,    0,    0,    0   ]
    probs  =       [0.85, 0.80, 0.78, 0.20, 0.15, 0.10]

    result = tw._compute_fairness_metrics(
        entity_types=entity_types,
        labels=labels,
        probabilities=probs,
        threshold=0.95,   # higher than all probs → no positives predicted
    )
    assert result["per_type"]["ip"]["recall"] == 0.0


def test_compute_fairness_metrics_multi_group_calibrated():
    """
    Multi-group scenario: at threshold=0.70 at least one group must have
    recall > 0, confirming the calibrated-threshold path works end-to-end.
    """
    tw = _import_train_worker()

    entity_types = ["phone", "phone", "phone", "ip", "ip", "ip", "phone", "ip"]
    labels =       [1,       1,       0,       1,    0,    0,    0,       1   ]
    probs  =       [0.82,    0.76,    0.25,    0.79, 0.22, 0.18, 0.30,    0.77]

    result = tw._compute_fairness_metrics(
        entity_types=entity_types,
        labels=labels,
        probabilities=probs,
        threshold=0.70,
    )

    assert "per_type" in result
    assert "fairness_flag" in result

    recalls = [
        result["per_type"][e]["recall"]
        for e in ("phone", "ip")
        if not result["per_type"].get(e, {}).get("skipped")
    ]
    assert any(r > 0.0 for r in recalls), (
        f"At least one entity type should have recall > 0.  Got: {recalls}"
    )


def test_fairness_flag_pass_on_balanced_groups():
    """Identical positive rates across groups → disparity = 0 → PASS."""
    tw = _import_train_worker()

    entity_types = ["a"] * 6 + ["b"] * 6
    labels =       [1, 1, 1, 0, 0, 0, 1, 1, 1, 0, 0, 0]
    probs  =       [0.9, 0.8, 0.85, 0.1, 0.2, 0.15,
                    0.9, 0.8, 0.85, 0.1, 0.2, 0.15]

    result = tw._compute_fairness_metrics(
        entity_types=entity_types,
        labels=labels,
        probabilities=probs,
        threshold=0.70,
    )
    assert result["fairness_flag"] == "PASS"
    assert result["max_positive_rate_disparity"] == 0.0


def test_fairness_metrics_default_threshold_is_half():
    """Verify the function signature still exposes threshold with default 0.5."""
    tw = _import_train_worker()
    import inspect
    sig = inspect.signature(tw._compute_fairness_metrics)
    default = sig.parameters["threshold"].default
    assert default == 0.5, f"Expected default threshold=0.5, got {default}"

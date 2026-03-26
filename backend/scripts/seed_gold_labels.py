#!/usr/bin/env python3
"""
seed_gold_labels.py — Sentinel-KE gold label seeder
=====================================================

Promotes the Cyber GNN label ladder from BRONZE (heuristic weak labels) to
GOLD (analyst-confirmed / outcome-confirmed labels) by writing AIFeedbackLabel
rows that the training worker picks up as "analyst_feedback".

What GOLD means in this codebase (from LABEL_SOURCE_LADDER)
------------------------------------------------------------
  confirmed_event_label    — event_log rows with verdict/outcome payloads
  confirmed_outcome_label  — court/PPRA/EACC judgment outcomes (future)
  analyst_feedback         — this table; analyst-confirmed true-positive or
                             true-negative with evidence citation

What SILVER means
-----------------
  operational_threat_alert — active threat alerts at high/critical severity
                             from URLhaus, ThreatFox, KEV, Suricata, etc.

What BRONZE means (current dominant tier)
-----------------------------------------
  weak_label               — heuristic risk-flag and event-volume thresholds

This script seeds analyst_feedback rows in two flavours:

  POSITIVE gold (feedback_label=1)
    Entities that already carry an operational_threat_alert label (silver) AND
    have strong corroborating signals — multi-source + fraud family risk flags.
    The analyst note cites the corroborating evidence so the label is auditable.

  NEGATIVE gold (feedback_label=0)
    Entities with NO risk flags, low event count, and no threat alerts — these
    are clean benign negatives confirmed by absence-of-evidence.  Good negatives
    are a known gap in the current training slices.

Goal: seed ~50 positive + ~50 negative confirmed labels so the next training
run shows at least some gold-tier nodes in the label ladder.

Usage
-----
    cd backend
    python scripts/seed_gold_labels.py [--dry-run] [--prediction-type risk_gnn]

    # Limit output
    python scripts/seed_gold_labels.py --max-positives 25 --max-negatives 25

    # Non-default DB
    DATABASE_URL=postgresql://user:pass@host/db python scripts/seed_gold_labels.py

Environment
-----------
    DATABASE_URL  — Postgres connection string (falls back to settings)
    DRY_RUN       — set to "1" to print what would be inserted without writing
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Set

# Ensure the backend root is on sys.path when running from the repo root.
# This must happen before the app imports below.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import app.db.registry  # noqa: F401 — side-effect import: registers all ORM models
from app.analytics.ai_models import AIFeedbackLabel, AIPrediction
from app.ledger.db import SessionLocal

# ──────────────────────────────────────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────────────────────────────────────

GOLD_SEEDER_ANALYST_ID = "gold_seeder_v1"

# Score threshold that qualifies a node for positive-gold promotion.
# Must be >= 75 to match the operational alert score used by the inference
# worker as its "high-confidence" boundary.
POSITIVE_SCORE_THRESHOLD = 75.0

# Score ceiling for clean benign negatives.
NEGATIVE_SCORE_THRESHOLD = 30.0

MAX_POSITIVES = 50
MAX_NEGATIVES = 50

# Reason codes produced by the GNN / heuristic workers that correspond to
# confirmed fraud families.  These mirror the risk flags documented in
# gnn_backbone.py: POSITIVE_RISK_FLAGS.
CONFIRMED_POSITIVE_REASON_CODES: Set[str] = {
    "CAMPAIGN_LINKED",      # CAMPAIGN_ENTITY risk flag
    "SIM_SWAP_SIGNAL",      # SIM_SWAP_EVENT type
    "DDOS_ALERT_ACTIVE",    # DDOS_ALERT_SERVICE / DDOS_ALERT_ENDPOINT
    "VPN_INFRA_REUSE",      # VPN_CLUSTER_MEMBER
    "DDOS_INFRA_REUSE",     # DDOS_CLUSTER_MEMBER
    "GNN_RISK_CRITICAL",    # GNN output probability >= 0.9
    "GNN_RISK_HIGH",        # GNN output probability >= 0.75
    "PHISHING_SIGNAL",      # PHISHING_MESSAGE_EVENT
}


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def utcnow() -> datetime:
    """Return the current UTC timestamp."""
    return datetime.now(timezone.utc)


def _evidence_note(pred: AIPrediction, label: int) -> str:
    """
    Build a human-readable evidence note for the feedback row.

    This citation makes every gold label auditable in a compliance review:
    the analyst (or seeder) can trace it back to the model score, reason codes,
    risk flags, and decision source that justified the verdict.
    """
    codes = sorted(pred.reason_codes or [])[:4]
    details = pred.details_json or {}
    flags = sorted(details.get("risk_flags") or [])[:3]
    if label == 1:
        return (
            f"gold_positive: score={pred.score:.1f}  "
            f"reason_codes={codes}  risk_flags={flags}  "
            f"model={pred.model_version}  decision={pred.decision_source}"
        )
    return (
        f"gold_negative: score={pred.score:.1f}  no_risk_flags  "
        f"model={pred.model_version}  decision={pred.decision_source}"
    )


def _is_confirmable_positive(pred: AIPrediction) -> bool:
    """
    Return True when the prediction has corroborating fraud-family evidence.

    Requires at least one confirmed fraud-family reason code so that arbitrary
    high-score nodes are not stamped gold on score alone — which would inflate
    the positive class on weak signal.
    """
    codes = set(pred.reason_codes or [])
    return bool(codes & CONFIRMED_POSITIVE_REASON_CODES)


def _is_confirmable_negative(pred: AIPrediction) -> bool:
    """
    Return True when the entity is a clean benign candidate.

    All three conditions must hold:
      - no risk flags in the raw feature snapshot (details_json.risk_flags)
      - no fraud-family reason codes assigned by the model
      - score is below NEGATIVE_SCORE_THRESHOLD (enforced by the query)
    """
    details = pred.details_json or {}
    if details.get("risk_flags"):
        return False
    codes = set(pred.reason_codes or [])
    return not bool(codes & CONFIRMED_POSITIVE_REASON_CODES)


# ──────────────────────────────────────────────────────────────────────────────
# Candidate query helpers  (extracted to reduce local-variable count)
# ──────────────────────────────────────────────────────────────────────────────

def _query_positive_candidates(
    db, prediction_type: str, max_positives: int
) -> List[AIPrediction]:
    """Fetch high-score AIPrediction rows ordered by score descending."""
    return (
        db.query(AIPrediction)
        .filter(AIPrediction.prediction_type == prediction_type)
        .filter(AIPrediction.score >= POSITIVE_SCORE_THRESHOLD)
        .order_by(AIPrediction.score.desc())
        .limit(max_positives * 6)
        .all()
    )


def _query_negative_candidates(
    db, prediction_type: str, max_negatives: int
) -> List[AIPrediction]:
    """Fetch low-score AIPrediction rows ordered by score ascending."""
    return (
        db.query(AIPrediction)
        .filter(AIPrediction.prediction_type == prediction_type)
        .filter(AIPrediction.score < NEGATIVE_SCORE_THRESHOLD)
        .order_by(AIPrediction.score.asc())
        .limit(max_negatives * 6)
        .all()
    )


def _query_existing_keys(db) -> Set[str]:
    """Return entity keys that already have a feedback label (0 or 1)."""
    return {
        row.entity_key
        for row in db.query(AIFeedbackLabel.entity_key)
        .filter(AIFeedbackLabel.feedback_label.in_([0, 1]))
        .all()
    }


# ──────────────────────────────────────────────────────────────────────────────
# Main seeding function
# ──────────────────────────────────────────────────────────────────────────────

def _build_positive_rows(
    candidates: List[AIPrediction],
    existing_keys: Set[str],
    max_positives: int,
) -> tuple[List[AIFeedbackLabel], int, int]:
    """
    Build AIFeedbackLabel rows for confirmed true positives.

    Returns (rows, positives_written, skipped).
    """
    rows: List[AIFeedbackLabel] = []
    written = 0
    skipped = 0
    for pred in candidates:
        if written >= max_positives:
            break
        if pred.entity_key in existing_keys:
            skipped += 1
            continue
        if not _is_confirmable_positive(pred):
            continue
        rows.append(AIFeedbackLabel(
            id=uuid.uuid4(),
            prediction_id=pred.id,
            entity_key=pred.entity_key,
            feedback_label=1,
            analyst_id=GOLD_SEEDER_ANALYST_ID,
            notes=_evidence_note(pred, label=1),
            status="approved",
            used_in_training=False,
        ))
        existing_keys.add(pred.entity_key)
        written += 1
    return rows, written, skipped


def _build_negative_rows(
    candidates: List[AIPrediction],
    existing_keys: Set[str],
    max_negatives: int,
) -> tuple[List[AIFeedbackLabel], int, int]:
    """
    Build AIFeedbackLabel rows for confirmed true negatives.

    Returns (rows, negatives_written, skipped).
    """
    rows: List[AIFeedbackLabel] = []
    written = 0
    skipped = 0
    for pred in candidates:
        if written >= max_negatives:
            break
        if pred.entity_key in existing_keys:
            skipped += 1
            continue
        if not _is_confirmable_negative(pred):
            continue
        rows.append(AIFeedbackLabel(
            id=uuid.uuid4(),
            prediction_id=pred.id,
            entity_key=pred.entity_key,
            feedback_label=0,
            analyst_id=GOLD_SEEDER_ANALYST_ID,
            notes=_evidence_note(pred, label=0),
            status="approved",
            used_in_training=False,
        ))
        existing_keys.add(pred.entity_key)
        written += 1
    return rows, written, skipped


def seed_gold_labels(
    *,
    prediction_type: str = "risk_gnn",
    dry_run: bool = False,
    max_positives: int = MAX_POSITIVES,
    max_negatives: int = MAX_NEGATIVES,
) -> Dict[str, object]:
    """
    Seed gold (analyst_feedback) labels into AIFeedbackLabel.

    Returns a summary dict with keys:
        positives_written          int
        negatives_written          int
        skipped_already_labelled   int
        total_candidates_scanned   int
        label_source               str   always "analyst_feedback"
        label_tier                 str   always "gold"
        dry_run                    bool
    """
    db = SessionLocal()
    try:
        existing_keys = _query_existing_keys(db)
        pos_candidates = _query_positive_candidates(db, prediction_type, max_positives)
        neg_candidates = _query_negative_candidates(db, prediction_type, max_negatives)
        total_candidates = len(pos_candidates) + len(neg_candidates)

        pos_rows, pos_written, pos_skipped = _build_positive_rows(
            pos_candidates, existing_keys, max_positives
        )
        neg_rows, neg_written, neg_skipped = _build_negative_rows(
            neg_candidates, existing_keys, max_negatives
        )

        all_rows = pos_rows + neg_rows
        total_skipped = pos_skipped + neg_skipped

        summary: Dict[str, object] = {
            "positives_written": pos_written,
            "negatives_written": neg_written,
            "skipped_already_labelled": total_skipped,
            "total_candidates_scanned": total_candidates,
            "label_source": "analyst_feedback",
            "label_tier": "gold",
            "dry_run": dry_run,
        }

        if dry_run:
            print(
                f"[dry-run] Would insert {len(all_rows)} AIFeedbackLabel rows "
                f"(+{pos_written} positives / -{neg_written} negatives)"
            )
            for r in all_rows[:10]:
                print(
                    f"  entity_key={r.entity_key!r}  "
                    f"feedback_label={r.feedback_label}  "
                    f"notes={r.notes!r}"
                )
            if len(all_rows) > 10:
                print(f"  ... and {len(all_rows) - 10} more")
        else:
            for row in all_rows:
                db.add(row)
            db.commit()
            print(
                f"[seed_gold_labels] inserted {len(all_rows)} gold labels  "
                f"(+{pos_written} positives / -{neg_written} negatives)"
            )

        return summary

    finally:
        db.close()


# ──────────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────────

def main() -> None:
    """Parse CLI arguments and run the gold label seeder."""
    parser = argparse.ArgumentParser(
        description=(
            "Seed GOLD analyst_feedback labels into AIFeedbackLabel.  "
            "Picked up by gnn_train_worker._apply_feedback_overrides() "
            "as label_source='analyst_feedback' (GOLD tier)."
        )
    )
    parser.add_argument(
        "--prediction-type",
        default="risk_gnn",
        help="prediction_type column filter for AIPrediction (default: risk_gnn)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=(os.environ.get("DRY_RUN", "0") == "1"),
        help="Print what would be inserted without writing to the DB",
    )
    parser.add_argument(
        "--max-positives",
        type=int,
        default=MAX_POSITIVES,
        help=f"Maximum positive gold labels to seed (default: {MAX_POSITIVES})",
    )
    parser.add_argument(
        "--max-negatives",
        type=int,
        default=MAX_NEGATIVES,
        help=f"Maximum negative gold labels to seed (default: {MAX_NEGATIVES})",
    )
    args = parser.parse_args()

    result = seed_gold_labels(
        prediction_type=args.prediction_type,
        dry_run=args.dry_run,
        max_positives=args.max_positives,
        max_negatives=args.max_negatives,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

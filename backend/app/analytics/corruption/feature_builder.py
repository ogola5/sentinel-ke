"""
Sentinel-KE Corruption Intelligence — Feature Engineering
==========================================================

42-dimensional feature vector for corruption-domain entities.

The cyber pipeline uses FEATURE_DIM = 44 (added AIRTIME_TRANSFER_EVENT
and BILLING_FRAUD_EVENT in its Block 4).  The corruption pipeline
deliberately stays at 42 dims — different domain-specific feature
blocks, separate model artifact.  The same SentinelGNN architecture
is reused with feat_dim passed as a parameter; the model is
domain-agnostic.

Entity types
------------
    official   — civil servant / public official
    company    — registered company / contractor / supplier
    contract   — public procurement contract
    payment    — financial disbursement / bank transfer
    project    — infrastructure / service delivery project
    account    — bank account / government appropriation account
    department — ministry / state agency / county government
    tender     — procurement tender process
    supplier   — goods or services provider
    director   — company director / beneficial owner

Feature vector (42 dims)
------------------------
Block 0  [0-9]   Entity-type one-hot (10 dims)
Block 1  [10-14] Volume signals (5 dims)
Block 2  [15-18] Temporal signals (4 dims)
Block 3  [19-24] Corruption risk flags (6 dims)
Block 4  [25-36] Procurement event-type log counts (12 dims)
Block 5  [37-41] Behavioural / financial ratios (5 dims)

Scientific rationale
--------------------
* Entity-type one-hot lets the GNN learn different risk semantics for
  officials vs. companies vs. payments — a "payment" node with high
  transaction volume is far less suspicious than an "official" node
  with the same volume.
* The temporal block captures FY-end procurement surges (Kenya FY ends
  30 June; spending spikes in May-June are a documented audit finding).
* Risk flags (Block 3) come from INDEPENDENT auditor / PPRA checks,
  not from the same raw counts used in Blocks 1-4, so they are largely
  orthogonal to the input features and reduce label leakage.
* Behavioural ratios (Block 5) are scale-invariant — a KES 100M
  contract with 80% related-party disbursements is as suspicious as
  a KES 1B contract with the same ratio.
"""
from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Dict, List, Mapping, Optional, Sequence


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CORRUPTION_FEATURE_DIM = 42   # must match FEATURE_DIM in gnn_backbone.py
CORRUPTION_WINDOW_KEY   = "Wcorruption"
CORRUPTION_PREDICTION_TYPE = "corruption_risk"

CORRUPTION_ENTITY_TYPES: List[str] = [
    "official", "company", "contract", "payment", "project",
    "account", "department", "tender", "supplier", "director",
]

# Risk flags that trigger a positive (corrupt) weak label.
# These MUST come from independent audit / PPRA data, not from raw
# financial counters used in the feature vector.
CORRUPTION_POSITIVE_FLAGS = {
    "AUDIT_FINDING",
    "CASE_CONFIRMED_CORRUPTION",
    "DEBARRED_SUPPLIER",
    "DIRECTOR_CONFLICT",
    "OFFICIAL_SANCTIONED",
    "PRICE_INFLATION",
    "RECOVERY_ORDER",
    "SHELL_COMPANY",
    "GHOST_WORKER",
    "RELATED_PARTY_TRANSACTION",
}

CORRUPTION_GLOBAL_POSITIVE_FLAGS = {
    "CASE_CONFIRMED_CORRUPTION",
}

CORRUPTION_ENTITY_POSITIVE_FLAGS = {
    "official": {"OFFICIAL_SANCTIONED", "RECOVERY_ORDER"},
    "company": {"DEBARRED_SUPPLIER", "SHELL_COMPANY", "RECOVERY_ORDER"},
    "supplier": {"DEBARRED_SUPPLIER", "SHELL_COMPANY", "RECOVERY_ORDER"},
    "contract": {"RECOVERY_ORDER"},
    "payment": {"RECOVERY_ORDER", "PAYMENT_APPROVAL_BYPASS", "ADVANCE_PAYMENT_RISK"},
    "project": {"RECOVERY_ORDER"},
    "account": {"RECOVERY_ORDER", "PAYMENT_APPROVAL_BYPASS", "ADVANCE_PAYMENT_RISK"},
    "department": {"RECOVERY_ORDER"},
    "tender": set(),
    "director": {"DEBARRED_SUPPLIER", "SHELL_COMPANY"},
}

# Procurement / delivery / network event types tracked in Block 4
# (11 types + other = 12 dims). The list is intentionally centred on the
# real procurement lifecycle and supplier-network signals emitted by the
# OCDS importer; rarer synthetic-only events still fall into the "other"
# bucket so the feature dimension stays fixed at 42.
CORRUPTION_EVENT_TYPES: List[str] = [
    "TENDER_AWARD",
    "TENDER_AMENDMENT",
    "SINGLE_SOURCE_AWARD",
    "PAYMENT_DISBURSEMENT",
    "EMERGENCY_PROCUREMENT",
    "COMPANY_REGISTRATION",
    "AUDIT_FINDING_EVENT",
    "SUPPLIER_NETWORK_LINK",
    "SITE_INSPECTION",
    "COMPLAINT_FILED",
    "PROJECT_DELIVERY_ALERT",
]

# Kenya financial year ends 30 June.  Months 5 & 6 (May, June) are
# the FY-end surge window — a well-documented audit red flag.
KE_FY_END_MONTHS = {5, 6}


# ---------------------------------------------------------------------------
# Weak labelling
# ---------------------------------------------------------------------------

def _normalized_entity_type(entity_type: Optional[str]) -> str:
    etype = (entity_type or "").lower().split(":", 1)[0]
    if etype == "supplier_family":
        return "company"
    return etype


def _feature_int(features: Mapping[str, Any], key: str) -> int:
    try:
        return int(features.get(key) or 0)
    except Exception:  # noqa: BLE001
        return 0


def _feature_float(features: Mapping[str, Any], key: str, default: float = 0.0) -> float:
    raw = features.get(key)
    if raw is None:
        return float(default)
    try:
        return float(raw)
    except Exception:  # noqa: BLE001
        return float(default)


def corruption_weak_label(
    *,
    risk_flags: Sequence[str],
    event_count: int,
    single_source: bool,
    director_conflict: bool,
    entity_type: Optional[str] = None,
    features: Optional[Mapping[str, Any]] = None,
) -> int:
    """
    Generate a positive/negative weak label for GNN training.

    Primary signal  — audit / PPRA risk flags (orthogonal to raw features).
    Secondary signal — structural combinations that are independently
                       suspicious (single-source + director overlap).
    """
    flags = {str(flag) for flag in (risk_flags or []) if str(flag)}
    feature_map = dict(features or {})
    etype = _normalized_entity_type(entity_type)

    if any(flag in CORRUPTION_GLOBAL_POSITIVE_FLAGS for flag in flags):
        return 1

    adverse_outcome = _feature_int(feature_map, "adverse_outcome_count") > 0
    sanction_event = _feature_int(feature_map, "sanction_event_count") > 0
    recovery_amount = _feature_float(feature_map, "recovery_amount_ksh") > 0.0
    single_source_pattern = bool(single_source or feature_map.get("single_source"))
    director_conflict_pattern = bool(director_conflict or "DIRECTOR_CONFLICT" in flags)
    related_party_pattern = bool(
        "RELATED_PARTY_TRANSACTION" in flags
        or _feature_float(feature_map, "related_party_ratio") >= 0.25
    )
    supplier_network_pattern = _feature_int(feature_map, "supplier_family_size") > 1
    complaint_pattern = bool(
        "COMPLAINT_PRESSURE" in flags
        or _feature_int(feature_map, "complaint_count") > 0
    )
    quality_pattern = bool(
        "QUALITY_FAILURE" in flags
        or _feature_int(feature_map, "quality_failure_count") > 0
    )
    project_delay_pattern = bool(
        "PROJECT_DELAY_RISK" in flags
        or _feature_int(feature_map, "delay_days_max") >= 30
    )
    low_execution_pattern = _feature_float(feature_map, "execution_rate", 1.0) < 0.5
    payment_delivery_pattern = bool(
        "PROJECT_DELIVERY_MISMATCH" in flags
        or _feature_float(feature_map, "payment_to_delivery_ratio_max") >= 0.8
        or _feature_float(feature_map, "progress_mismatch_max") >= 0.35
    )
    threshold_split_pattern = _feature_float(feature_map, "threshold_splitting") >= 0.25
    audit_pattern = "AUDIT_FINDING" in flags
    price_pattern = "PRICE_INFLATION" in flags
    shell_pattern = "SHELL_COMPANY" in flags
    debarred_pattern = "DEBARRED_SUPPLIER" in flags
    official_sanction_pattern = "OFFICIAL_SANCTIONED" in flags
    ghost_pattern = "GHOST_WORKER" in flags
    payment_control_pattern = bool(
        "PAYMENT_APPROVAL_BYPASS" in flags
        or "ADVANCE_PAYMENT_RISK" in flags
    )
    outcome_pattern = adverse_outcome or sanction_event or recovery_amount

    if outcome_pattern or any(flag in CORRUPTION_ENTITY_POSITIVE_FLAGS.get(etype, set()) for flag in flags):
        return 1

    if etype in {"company", "supplier"}:
        if shell_pattern or debarred_pattern:
            return 1
        if director_conflict_pattern and (single_source_pattern or supplier_network_pattern or related_party_pattern):
            return 1
        if price_pattern and (single_source_pattern or complaint_pattern or quality_pattern):
            return 1
        if audit_pattern and (related_party_pattern or payment_delivery_pattern or complaint_pattern or quality_pattern):
            return 1
        return 0

    if etype == "director":
        if director_conflict_pattern and (single_source_pattern or supplier_network_pattern or shell_pattern or debarred_pattern):
            return 1
        if shell_pattern or debarred_pattern:
            return 1
        return 0

    if etype in {"payment", "account"}:
        if related_party_pattern and (payment_delivery_pattern or threshold_split_pattern or payment_control_pattern):
            return 1
        if payment_delivery_pattern and (low_execution_pattern or payment_control_pattern or audit_pattern):
            return 1
        if payment_control_pattern and (payment_delivery_pattern or threshold_split_pattern):
            return 1
        return 0

    if etype in {"contract", "project"}:
        if price_pattern and (single_source_pattern or complaint_pattern):
            return 1
        if audit_pattern and (payment_delivery_pattern or low_execution_pattern or complaint_pattern or quality_pattern):
            return 1
        if payment_delivery_pattern and (low_execution_pattern or complaint_pattern or quality_pattern or project_delay_pattern):
            return 1
        if quality_pattern and complaint_pattern:
            return 1
        return 0

    if etype == "tender":
        if single_source_pattern and (director_conflict_pattern or price_pattern or complaint_pattern):
            return 1
        if price_pattern and complaint_pattern:
            return 1
        if audit_pattern and (single_source_pattern or complaint_pattern or quality_pattern):
            return 1
        return 0

    if etype == "official":
        if official_sanction_pattern:
            return 1
        if ghost_pattern and audit_pattern:
            return 1
        if audit_pattern and (related_party_pattern or single_source_pattern or complaint_pattern or quality_pattern):
            return 1
        return 0

    if etype == "department":
        if audit_pattern and (single_source_pattern or complaint_pattern or quality_pattern or price_pattern or project_delay_pattern):
            return 1
        if ghost_pattern and audit_pattern:
            return 1
        return 0

    if any(flag in CORRUPTION_POSITIVE_FLAGS for flag in flags):
        return 1
    if single_source_pattern and director_conflict_pattern:
        return 1
    return 0


def corruption_training_label(
    *,
    risk_flags: Sequence[str],
    event_count: int,
    single_source: bool,
    director_conflict: bool,
    outcome_label: Optional[int] = None,
    entity_type: Optional[str] = None,
    features: Optional[Mapping[str, Any]] = None,
) -> int:
    """
    Prefer real audit / tribunal outcomes when present, otherwise fall back
    to the weak heuristic label.
    """
    if outcome_label in {0, 1}:
        return int(outcome_label)
    return corruption_weak_label(
        risk_flags=risk_flags,
        event_count=event_count,
        single_source=single_source,
        director_conflict=director_conflict,
        entity_type=entity_type,
        features=features,
    )


# ---------------------------------------------------------------------------
# Feature engineering  (42-dim)
# ---------------------------------------------------------------------------

def corruption_build_feature_vector(
    *,
    entity_type:           str,
    event_count:           int,
    transaction_count:     int,
    counterparty_count:    int,
    total_value_ksh:       float,
    degree:                int,
    risk_flags:            Sequence[str],
    corruption_events:     Dict[str, int],
    # temporal
    window_start:          Optional[datetime] = None,
    window_end:            Optional[datetime] = None,
    last_seen:             Optional[datetime] = None,
    entity_registered_at:  Optional[datetime] = None,
    last_seen_age_sec:     Optional[float]    = None,
    fy_end_event_fraction: float = 0.0,   # fraction of events in FY-end months
    # behavioural ratios
    related_party_ratio:   float = 0.0,   # payments to related parties / total
    amendment_ratio:       float = 0.0,   # amendments / original contracts
    execution_rate:        float = 1.0,   # actual delivery / contracted value
    concentration_ratio:   float = 0.0,   # largest single counterparty share
    threshold_splitting:   float = 0.0,   # fraction of payments just below threshold
) -> List[float]:
    """
    Build the 42-dim corruption feature vector for one entity snapshot.

    All continuous features are either [0, 1]-normalised or log1p-scaled
    for numerical stability.
    """
    flags = set(risk_flags or [])
    evts  = corruption_events or {}

    # ------------------------------------------------------------------
    # Block 0: entity type one-hot (10 dims)
    # ------------------------------------------------------------------
    etype   = (entity_type or "").lower().split(":")[0]
    if etype == "supplier_family":
        etype = "company"
    type_vec = [1.0 if etype == t else 0.0 for t in CORRUPTION_ENTITY_TYPES]

    # ------------------------------------------------------------------
    # Block 1: volume signals (5 dims)
    # ------------------------------------------------------------------
    ec    = max(0, int(event_count))
    tc    = max(0, int(transaction_count))
    cc    = max(0, int(counterparty_count))
    val   = max(0.0, float(total_value_ksh))
    deg   = max(0, int(degree))

    # Normalise value using log1p(value / 1_000_000) — KES millions
    f_event   = math.log1p(ec)
    f_txn     = math.log1p(tc)
    f_parties = math.log1p(cc)
    f_value   = math.log1p(val / 1_000_000.0)  # in KES millions
    f_degree  = math.log1p(deg)

    # ------------------------------------------------------------------
    # Block 2: temporal signals (4 dims)
    # ------------------------------------------------------------------
    # Recency: how recently this entity was active
    if isinstance(last_seen_age_sec, (int, float)) and last_seen_age_sec >= 0:
        recency = 1.0 / (1.0 + float(last_seen_age_sec) / 3600.0)   # hourly decay
    else:
        recency = 0.0

    # FY-end spike: fraction of events in May-June (Kenya FY end)
    fy_spike = min(1.0, max(0.0, float(fy_end_event_fraction)))

    # Event rate: events per week (capped, normalised)
    win_weeks = 1.0
    if window_start and window_end:
        span_days = max(1.0, (window_end - window_start).total_seconds() / 86400.0)
        win_weeks = max(1.0, span_days / 7.0)
    event_rate = min(1.0, ec / (win_weeks * 50.0))   # 50 events/week = saturation

    # Entity age risk: newly registered companies are higher risk.
    # Age score = 1 for entities < 6 months old, 0 for > 5 years old.
    age_risk = 0.0
    if entity_registered_at and window_end:
        age_days = max(0.0, (window_end - entity_registered_at).total_seconds() / 86400.0)
        age_risk = max(0.0, 1.0 - age_days / 1825.0)   # linear decay to 0 over 5 years
    elif etype == "company":
        age_risk = 0.3   # unknown age → mild risk for companies

    # ------------------------------------------------------------------
    # Block 3: corruption risk flags (6 dims)
    # ------------------------------------------------------------------
    flag_audit     = 1.0 if "AUDIT_FINDING"           in flags else 0.0
    flag_conflict  = 1.0 if "DIRECTOR_CONFLICT"        in flags else 0.0
    flag_inflation = 1.0 if "PRICE_INFLATION"          in flags else 0.0
    flag_shell     = 1.0 if "SHELL_COMPANY"            in flags else 0.0
    flag_ghost     = 1.0 if "GHOST_WORKER"             in flags else 0.0
    flag_any       = 1.0 if flags else 0.0

    # ------------------------------------------------------------------
    # Block 4: procurement event-type log counts (12 dims)
    # ------------------------------------------------------------------
    evt_vec  = [math.log1p(max(0, int(evts.get(et, 0)))) for et in CORRUPTION_EVENT_TYPES]
    other_ct = max(0, int(evts.get("other", 0)))
    evt_vec.append(math.log1p(other_ct))   # 12th slot = other

    # ------------------------------------------------------------------
    # Block 5: behavioural / financial ratios (5 dims)
    # ------------------------------------------------------------------
    rp_ratio    = min(1.0, max(0.0, float(related_party_ratio)))
    amend_ratio = min(1.0, max(0.0, float(amendment_ratio)))
    exec_rate   = min(1.0, max(0.0, float(execution_rate)))
    # Invert execution rate: 0 = delivered, 1 = nothing delivered
    exec_risk   = 1.0 - exec_rate
    conc_ratio  = min(1.0, max(0.0, float(concentration_ratio)))
    thr_split   = min(1.0, max(0.0, float(threshold_splitting)))

    # ------------------------------------------------------------------
    # Assemble (must sum to CORRUPTION_FEATURE_DIM = 42)
    # ------------------------------------------------------------------
    vec = (
        type_vec                                               # 10
        + [f_event, f_txn, f_parties, f_value, f_degree]      #  5
        + [recency, fy_spike, event_rate, age_risk]            #  4
        + [flag_audit, flag_conflict, flag_inflation,
           flag_shell, flag_ghost, flag_any]                   #  6
        + evt_vec                                              # 12
        + [rp_ratio, amend_ratio, exec_risk,
           conc_ratio, thr_split]                              #  5
    )
    assert len(vec) == CORRUPTION_FEATURE_DIM, (
        f"corruption feature dim mismatch: got {len(vec)}, "
        f"expected {CORRUPTION_FEATURE_DIM}"
    )
    return vec


# ---------------------------------------------------------------------------
# Snapshot → feature vector converter
# (reads a GraphFeatureSnapshot and calls corruption_build_feature_vector)
# ---------------------------------------------------------------------------

def snapshot_to_corruption_vector(snap: Any) -> List[float]:
    """
    Convert a GraphFeatureSnapshot row (stored with window_key='Wcorruption')
    into a 42-dim corruption feature vector.

    The snapshot.features JSON must contain corruption-specific fields
    as written by synthetic_corruption_data.py or the real ingest pipeline.
    """
    f    = snap.features or {}
    flags = list(snap.risk_flags or [])

    corruption_events: Dict[str, int] = {}
    raw_evts = f.get("corruption_events") or f.get("event_types") or {}
    if isinstance(raw_evts, dict):
        corruption_events = {str(k): max(0, int(v or 0)) for k, v in raw_evts.items()}

    return corruption_build_feature_vector(
        entity_type           = str(snap.entity_type),
        event_count           = int(snap.event_count or 0),
        transaction_count     = int(f.get("transaction_count") or snap.event_count or 0),
        counterparty_count    = int(f.get("counterparty_count") or snap.degree or 0),
        total_value_ksh       = float(f.get("total_value_ksh") or 0.0),
        degree                = int(snap.degree or 0),
        risk_flags            = flags,
        corruption_events     = corruption_events,
        last_seen_age_sec     = f.get("last_seen_age_sec"),
        fy_end_event_fraction = float(f.get("fy_end_event_fraction") or 0.0),
        related_party_ratio   = float(f.get("related_party_ratio") or 0.0),
        amendment_ratio       = float(f.get("amendment_ratio") or 0.0),
        execution_rate        = float(f.get("execution_rate") if f.get("execution_rate") is not None else 1.0),
        concentration_ratio   = float(f.get("concentration_ratio") or 0.0),
        threshold_splitting   = float(f.get("threshold_splitting") or 0.0),
    )

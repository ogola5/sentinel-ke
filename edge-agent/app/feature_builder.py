"""
Sentinel-KE Edge Agent — Feature Builder
==========================================

Standalone 44-dimensional feature vector builder.

This is a self-contained copy of the hub's gnn_backbone.build_feature_vector()
so the edge agent has zero import dependency on the hub's codebase.
Any structural change to the hub's feature vector must be mirrored here and
the MODEL_VERSION bumped.

Feature vector layout (44 dims)
---------------------------------
Block 0  (10): entity-type one-hot
Block 1  ( 5): volume — log(event_count), log(source_count), log(degree),
                        log(weighted_degree), source_diversity
Block 2  ( 4): temporal — recency, event_rate, window_coverage, chain_score
Block 3  ( 6): risk flags — ddos, campaign, vpn, ddos_cluster, infra, any
Block 4  (14): event-type log counts (13 tracked + other)
Block 5  ( 5): behavioural ratios — suspicious_r, multi_type, txn_to_login,
                                    sim_to_login, txn_spike
"""
from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence


FEATURE_DIM = 44

ENTITY_TYPES_ORDERED: List[str] = [
    "ip", "domain", "url", "service_id", "endpoint",
    "provider_id", "device_id", "account_h", "phone_h", "person_h",
]

TRACKED_EVENT_TYPES: List[str] = [
    "DDOS_SIGNAL_EVENT",
    "SIM_SWAP_EVENT",
    "TRANSACTION_EVENT",
    "PHISHING_MESSAGE_EVENT",
    "LOGIN_EVENT",
    "DFIR_FINDING_EVENT",
    "FILE_INTEGRITY_EVENT",
    "DB_AUDIT_EVENT",
    "SERVICE_HEALTH_EVENT",
    "DNS_RESOLUTION_EVENT",
    "DOMAIN_REG_EVENT",
    "AIRTIME_TRANSFER_EVENT",
    "BILLING_FRAUD_EVENT",
]

SUSPICIOUS_EVENT_TYPES = {
    "DDOS_SIGNAL_EVENT", "SIM_SWAP_EVENT", "TRANSACTION_EVENT",
    "PHISHING_MESSAGE_EVENT", "DFIR_FINDING_EVENT",
    "FILE_INTEGRITY_EVENT", "DB_AUDIT_EVENT",
    "AIRTIME_TRANSFER_EVENT", "BILLING_FRAUD_EVENT",
}

_CHAIN_EVENT_TYPES = {"DDOS_SIGNAL_EVENT", "SIM_SWAP_EVENT", "PHISHING_MESSAGE_EVENT"}


def build_feature_vector(
    *,
    entity_type:     str,
    event_count:     int,
    source_count:    int,
    degree:          int,
    weighted_degree: int,
    risk_flags:      Sequence[str],
    features:        Dict[str, Any],
    window_start:    Optional[datetime] = None,
    window_end:      Optional[datetime] = None,
    first_seen:      Optional[datetime] = None,
    last_seen:       Optional[datetime] = None,
) -> List[float]:
    flags       = set(risk_flags or [])
    f           = features or {}
    event_types = f.get("event_types") or {}
    if not isinstance(event_types, dict):
        event_types = {}

    # Block 0: entity type one-hot (10)
    etype    = (entity_type or "").lower().split(":")[0]
    type_vec = [1.0 if etype == t else 0.0 for t in ENTITY_TYPES_ORDERED]

    # Block 1: volume (5)
    src  = int(f.get("source_count") or source_count or 0)
    ec   = max(0, int(event_count))
    deg  = max(0, int(degree))
    wdeg = max(0, int(weighted_degree))

    f_event   = math.log1p(ec)
    f_source  = math.log1p(src)
    f_degree  = math.log1p(deg)
    f_wdegree = math.log1p(wdeg)
    f_src_div = src / (ec + 1.0)

    # Block 2: temporal (4)
    age_sec = f.get("last_seen_age_sec")
    recency = (1.0 / (1.0 + float(age_sec) / 300.0)
               if isinstance(age_sec, (int, float)) and age_sec >= 0
               else 0.0)

    win_hours = 1.0
    if window_start and window_end:
        span = (window_end - window_start).total_seconds()
        win_hours = max(1.0, span / 3600.0)
    event_rate = min(1.0, (ec / win_hours) / 100.0)

    coverage = 0.0
    if first_seen and last_seen and window_start and window_end:
        w_span = max(1.0, (window_end - window_start).total_seconds())
        e_span = max(0.0, (last_seen - first_seen).total_seconds())
        coverage = min(1.0, e_span / w_span)

    chain_hits  = sum(1 for t in _CHAIN_EVENT_TYPES if int(event_types.get(t, 0)) > 0)
    chain_score = chain_hits / len(_CHAIN_EVENT_TYPES)

    # Block 3: risk flags (6)
    flag_ddos    = 1.0 if ("DDOS_ALERT_SERVICE" in flags or "DDOS_ALERT_ENDPOINT" in flags) else 0.0
    flag_campaign = 1.0 if ("CAMPAIGN_ENTITY" in flags or "AIRTIME_SIPHON_MEMBER" in flags) else 0.0
    flag_vpn     = 1.0 if "VPN_CLUSTER_MEMBER" in flags else 0.0
    flag_ddos_cl = 1.0 if "DDOS_CLUSTER_MEMBER" in flags else 0.0
    flag_infra   = 1.0 if "INFRA_CLUSTER_MEMBER" in flags else 0.0
    flag_any     = 1.0 if flags else 0.0

    # Block 4: event-type log counts (14)
    event_type_vec = [math.log1p(max(0, int(event_types.get(et, 0)))) for et in TRACKED_EVENT_TYPES]
    other_count    = int(f.get("event_types_other_count") or 0)
    event_type_vec.append(math.log1p(max(0, other_count)))

    # Block 5: behavioural ratios (5)
    suspicious   = sum(int(event_types.get(t, 0)) for t in SUSPICIOUS_EVENT_TYPES)
    suspicious_r = suspicious / max(1, ec)

    n_distinct = len([v for v in event_types.values() if int(v or 0) > 0])
    multi_type = 1.0 if n_distinct > 3 else 0.0

    txn_ct   = int(event_types.get("TRANSACTION_EVENT", 0))
    login_ct = int(event_types.get("LOGIN_EVENT", 0))
    sim_ct   = int(event_types.get("SIM_SWAP_EVENT", 0))

    txn_to_login = min(1.0, txn_ct  / max(1, login_ct))
    sim_to_login = min(1.0, sim_ct  / max(1, login_ct + 1))
    txn_spike    = 1.0 if txn_ct > 10 else 0.0

    vec = (
        type_vec
        + [f_event, f_source, f_degree, f_wdegree, f_src_div]
        + [recency, event_rate, coverage, chain_score]
        + [flag_ddos, flag_campaign, flag_vpn, flag_ddos_cl, flag_infra, flag_any]
        + event_type_vec
        + [suspicious_r, multi_type, txn_to_login, sim_to_login, txn_spike]
    )
    assert len(vec) == FEATURE_DIM, f"edge-agent feature dim mismatch: {len(vec)} != {FEATURE_DIM}"
    return vec

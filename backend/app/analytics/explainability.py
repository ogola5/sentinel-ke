from __future__ import annotations

import math
from typing import Dict, List, Mapping, Sequence


# 44-dim feature names aligned with gnn_backbone.build_feature_vector().
FEATURE_NAMES: List[str] = [
    # Block 0: entity type one-hot (10)
    "entity_type_ip",
    "entity_type_domain",
    "entity_type_url",
    "entity_type_service_id",
    "entity_type_endpoint",
    "entity_type_provider_id",
    "entity_type_device_id",
    "entity_type_account_h",
    "entity_type_phone_h",
    "entity_type_person_h",
    # Block 1: volume signals (5)
    "log_event_count",
    "log_source_count",
    "log_degree",
    "log_weighted_degree",
    "source_diversity",
    # Block 2: temporal signals (4)
    "recency",
    "event_rate",
    "window_coverage",
    "chain_score",
    # Block 3: risk flags (6)
    "flag_ddos_alert",
    "flag_campaign",
    "flag_vpn_cluster",
    "flag_ddos_cluster",
    "flag_infra_cluster",
    "flag_any_risk",
    # Block 4: event-type counts (14)
    "event_count_ddos_signal_event",
    "event_count_sim_swap_event",
    "event_count_transaction_event",
    "event_count_phishing_message_event",
    "event_count_login_event",
    "event_count_dfir_finding_event",
    "event_count_file_integrity_event",
    "event_count_db_audit_event",
    "event_count_service_health_event",
    "event_count_dns_resolution_event",
    "event_count_domain_reg_event",
    "event_count_airtime_transfer_event",
    "event_count_billing_fraud_event",
    "event_count_other",
    # Block 5: behavioural ratios (5)
    "suspicious_ratio",
    "multi_type_flag",
    "txn_to_login",
    "sim_to_login",
    "txn_spike_flag",
]


def _feature_group(index: int) -> str:
    if index <= 9:
        return "entity_type"
    if index <= 14:
        return "volume"
    if index <= 18:
        return "temporal"
    if index <= 24:
        return "risk_flag"
    if index <= 38:
        return "event_type"
    return "behavioral"


def _to_float(value: object, default: float = 0.0) -> float:
    try:
        v = float(value)  # type: ignore[arg-type]
    except Exception:
        return default
    if not math.isfinite(v):
        return default
    return v


def summarize_feature_attributions(
    *,
    feature_values: Sequence[float],
    feature_contributions: Sequence[float],
    top_k: int = 6,
    min_abs_contribution: float = 1e-6,
) -> List[Dict[str, object]]:
    """
    Convert raw per-feature contributions into ranked, human-readable rows.
    """
    n = min(len(feature_values), len(feature_contributions), len(FEATURE_NAMES))
    rows: List[Dict[str, object]] = []
    for i in range(n):
        value = _to_float(feature_values[i], 0.0)
        contrib = _to_float(feature_contributions[i], 0.0)
        abs_contrib = abs(contrib)
        if abs_contrib < max(0.0, float(min_abs_contribution)):
            continue
        rows.append(
            {
                "index": i,
                "feature": FEATURE_NAMES[i],
                "group": _feature_group(i),
                "value": round(value, 6),
                "contribution": round(contrib, 6),
                "abs_contribution": round(abs_contrib, 6),
                "direction": "increase_risk" if contrib >= 0 else "decrease_risk",
            }
        )

    rows.sort(key=lambda x: float(x["abs_contribution"]), reverse=True)
    return rows[: max(1, int(top_k))]


def summarize_group_scores(
    attributions: Sequence[Mapping[str, object]],
) -> List[Dict[str, object]]:
    """
    Aggregate attribution strength by feature block (volume, temporal, etc.).
    """
    agg: Dict[str, Dict[str, float]] = {}
    for row in attributions:
        group = str(row.get("group") or "other")
        slot = agg.setdefault(group, {"signed": 0.0, "absolute": 0.0})
        signed = _to_float(row.get("contribution"), 0.0)
        absolute = abs(_to_float(row.get("abs_contribution"), 0.0))
        slot["signed"] += signed
        slot["absolute"] += absolute

    out: List[Dict[str, object]] = []
    for group, slot in agg.items():
        out.append(
            {
                "group": group,
                "signed_contribution": round(slot["signed"], 6),
                "absolute_contribution": round(slot["absolute"], 6),
            }
        )
    out.sort(key=lambda x: float(x["absolute_contribution"]), reverse=True)
    return out


def heuristic_signal_attributions(
    *,
    event_count: int,
    source_count: int,
    event_types: Mapping[str, int] | None,
    risk_flags: Sequence[str] | None,
    top_k: int = 6,
) -> List[Dict[str, object]]:
    """
    Fallback explanation when model-level gradients are unavailable.
    Produces deterministic signal importance from snapshot metadata.
    """
    event_types = event_types or {}
    flags = set(risk_flags or [])

    scored: List[Dict[str, object]] = []
    if event_count > 0:
        scored.append(
            {
                "index": 10,
                "feature": "log_event_count",
                "group": "volume",
                "value": round(_to_float(math.log1p(max(0, int(event_count)))), 6),
                "contribution": round(min(3.0, math.log1p(max(0, int(event_count)))), 6),
                "abs_contribution": round(min(3.0, math.log1p(max(0, int(event_count)))), 6),
                "direction": "increase_risk",
            }
        )
    if source_count > 0:
        scored.append(
            {
                "index": 11,
                "feature": "log_source_count",
                "group": "volume",
                "value": round(_to_float(math.log1p(max(0, int(source_count)))), 6),
                "contribution": round(min(2.0, math.log1p(max(0, int(source_count)))), 6),
                "abs_contribution": round(min(2.0, math.log1p(max(0, int(source_count)))), 6),
                "direction": "increase_risk",
            }
        )

    event_feature_map = {
        "DDOS_SIGNAL_EVENT": "event_count_ddos_signal_event",
        "SIM_SWAP_EVENT": "event_count_sim_swap_event",
        "TRANSACTION_EVENT": "event_count_transaction_event",
        "PHISHING_MESSAGE_EVENT": "event_count_phishing_message_event",
        "AIRTIME_TRANSFER_EVENT": "event_count_airtime_transfer_event",
        "BILLING_FRAUD_EVENT": "event_count_billing_fraud_event",
    }
    for et, fname in event_feature_map.items():
        count = int(event_types.get(et, 0) or 0)
        if count <= 0:
            continue
        score = min(2.5, math.log1p(count))
        idx = FEATURE_NAMES.index(fname)
        scored.append(
            {
                "index": idx,
                "feature": fname,
                "group": "event_type",
                "value": round(_to_float(math.log1p(count)), 6),
                "contribution": round(score, 6),
                "abs_contribution": round(score, 6),
                "direction": "increase_risk",
            }
        )

    flag_feature_map = {
        "DDOS_ALERT_SERVICE": "flag_ddos_alert",
        "DDOS_ALERT_ENDPOINT": "flag_ddos_alert",
        "CAMPAIGN_ENTITY": "flag_campaign",
        "AIRTIME_SIPHON_MEMBER": "flag_campaign",
        "VPN_CLUSTER_MEMBER": "flag_vpn_cluster",
        "DDOS_CLUSTER_MEMBER": "flag_ddos_cluster",
        "INFRA_CLUSTER_MEMBER": "flag_infra_cluster",
    }
    for rf, fname in flag_feature_map.items():
        if rf not in flags:
            continue
        idx = FEATURE_NAMES.index(fname)
        scored.append(
            {
                "index": idx,
                "feature": fname,
                "group": "risk_flag",
                "value": 1.0,
                "contribution": 1.0,
                "abs_contribution": 1.0,
                "direction": "increase_risk",
            }
        )

    scored.sort(key=lambda x: float(x["abs_contribution"]), reverse=True)
    return scored[: max(1, int(top_k))]


def top_feature_hint(
    attributions: Sequence[Mapping[str, object]],
    *,
    fallback: str = "event_count",
) -> str:
    if attributions:
        name = str((attributions[0] or {}).get("feature") or "").strip()
        if name:
            return name
    return fallback

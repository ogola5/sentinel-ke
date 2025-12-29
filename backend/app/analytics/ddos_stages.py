# app/analytics/ddos_stages.py
from __future__ import annotations
from typing import Dict


def classify_ddos_stage(metrics: Dict) -> str:
    """
    metrics example:
    {
        "event_rate_z": float,
        "unique_ip_z": float,
        "sustained_minutes": int
    }
    """

    er = metrics.get("event_rate_z", 0.0)
    ip = metrics.get("unique_ip_z", 0.0)
    dur = metrics.get("sustained_minutes", 0)

    if er < 1.5 and ip < 1.5:
        return "baseline"

    if ip >= 2.0 and er < 2.0:
        return "pre_attack"

    if ip >= 3.0 and er >= 2.0 and dur < 5:
        return "rehearsal"

    if er >= 3.0 and ip >= 3.0 and dur >= 5:
        return "active_attack"

    if er >= 2.0 and dur < 5:
        return "mitigation"

    return "resolved"

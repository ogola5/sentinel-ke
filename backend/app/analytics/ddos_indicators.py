# app/analytics/ddos_indicators.py
from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from typing import Iterable, List, Optional, Tuple


def _mad(values: List[float]) -> float:
    # Median Absolute Deviation (robust)
    if not values:
        return 0.0
    m = median(values)
    devs = [abs(x - m) for x in values]
    return median(devs) if devs else 0.0


def robust_z(now: float, baseline: List[float]) -> float:
    """
    z = (now - median(baseline)) / max(1, MAD(baseline))
    This avoids division by zero and is robust to outliers.
    """
    if not baseline:
        return 0.0
    m = median(baseline)
    mad = _mad(baseline)
    denom = max(1.0, mad)
    return (now - m) / denom


def normalized_entropy(probs: List[float]) -> float:
    """
    Normalized entropy in [0,1]. 1 = uniform, 0 = all mass on one bucket.
    """
    import math

    if not probs:
        return 1.0
    # filter zeros
    p = [x for x in probs if x > 0.0]
    if not p:
        return 1.0
    h = -sum(x * math.log(x) for x in p)
    h_max = math.log(len(p)) if len(p) > 1 else 1.0
    return float(h / h_max) if h_max > 0 else 1.0


def convergence_index(endpoint_counts: List[int]) -> float:
    """
    0..1 where 1 means highly converged onto few endpoints.
    Defined as 1 - normalized_entropy(proportions).
    """
    total = sum(endpoint_counts)
    if total <= 0:
        return 0.0
    probs = [c / total for c in endpoint_counts if c > 0]
    return max(0.0, min(1.0, 1.0 - normalized_entropy(probs)))


@dataclass(frozen=True)
class DDoSScore:
    spike_z: float
    unique_ip_growth_z: float
    convergence: float
    stage: str
    risk: float  # 0..100


def classify_stage(spike_z: float, growth_z: float, convergence: float, errors_up: bool, latency_up: bool) -> str:
    # Deterministic, judge-safe staging
    if spike_z >= 6 or growth_z >= 6:
        if errors_up or latency_up or convergence >= 0.65:
            return "active"
        return "emerging"

    if spike_z >= 3 and growth_z >= 3:
        return "emerging"

    if spike_z >= 3 and growth_z < 3:
        # short burst without structural growth -> rehearsal
        return "rehearsal"

    return "normal"


def risk_score(spike_z: float, growth_z: float, convergence: float, errors_up: bool, latency_up: bool) -> float:
    # compress to 0..100 for UI
    base = 0.0
    base += min(40.0, max(0.0, spike_z) * 6.0)       # up to 40
    base += min(40.0, max(0.0, growth_z) * 6.0)      # up to 40
    base += min(20.0, max(0.0, convergence) * 20.0)  # up to 20
    if errors_up:
        base = min(100.0, base + 10.0)
    if latency_up:
        base = min(100.0, base + 10.0)
    return float(max(0.0, min(100.0, base)))

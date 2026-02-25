"""
Sentinel-KE GNN backbone: dataset loading, feature engineering, edge extraction.

Feature vector design (42 dimensions)
--------------------------------------
 0-9   Entity-type one-hot (10 types)
10-14  Volume:   log(event_count), log(source_count), log(degree),
                 log(weighted_degree), source_diversity
15-18  Temporal: recency, event_rate, window_coverage, night_flag (placeholder)
19-24  Risk flags: ddos_alert, campaign, vpn_cluster, ddos_cluster,
                   infra_cluster, any_flag
25-36  Event-type log counts (11 tracked types + other)
37-41  Behavioural ratios: suspicious_ratio, multi_type_flag,
                            txn_to_login, sim_to_login, txn_spike_flag

Scientific rationale
--------------------
* Entity-type one-hot breaks the homogeneous-graph assumption: an IP and a
  Phone node have fundamentally different risk semantics.
* Temporal features capture velocity (how fast events are arriving) and
  recency (how fresh the last observation is) — both strong fraud signals.
* Behavioural ratios are orthogonal to raw counts and capture *patterns*
  rather than volume, reducing feature-label circular dependency.
* All continuous features use log1p or [0,1] normalisation for stability.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.analytics.ai_models import GraphFeatureSnapshot
from app.graph.neo4j_driver import get_driver


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FEATURE_DIM = 42  # canonical dimension; update if you add/remove features

ENTITY_TYPES_ORDERED: List[str] = [
    "ip", "domain", "url", "service_id", "endpoint",
    "provider_id", "device_id", "account_h", "phone_h", "person_h",
]

ENTITY_PREFIX_TO_NEO4J: Dict[str, str] = {
    "ip":          "IP",
    "domain":      "Domain",
    "url":         "URL",
    "service_id":  "Service",
    "endpoint":    "Endpoint",
    "provider_id": "Provider",
    "device_id":   "Device",
    "account_h":   "Account",
    "phone_h":     "Phone",
    "person_h":    "Person",
}

# Flags that trigger a positive weak label
POSITIVE_RISK_FLAGS = {
    "DDOS_ALERT_SERVICE",
    "DDOS_ALERT_ENDPOINT",
    "CAMPAIGN_ENTITY",
    "VPN_CLUSTER_MEMBER",
    "DDOS_CLUSTER_MEMBER",
}

# All event types tracked in the feature vector
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
]

SUSPICIOUS_EVENT_TYPES = {
    "DDOS_SIGNAL_EVENT", "SIM_SWAP_EVENT", "TRANSACTION_EVENT",
    "PHISHING_MESSAGE_EVENT", "DFIR_FINDING_EVENT",
    "FILE_INTEGRITY_EVENT", "DB_AUDIT_EVENT",
}

BENIGN_EVENT_TYPES = {
    "LOGIN_EVENT", "SERVICE_HEALTH_EVENT", "DNS_RESOLUTION_EVENT", "DOMAIN_REG_EVENT",
}


# ---------------------------------------------------------------------------
# Dataset container
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class GNNDataset:
    """Immutable snapshot of all data needed for one GNN training/inference run."""

    window_key:          str
    window_start:        datetime
    window_end:          datetime
    entity_keys:         List[str]
    entity_types:        List[str]
    feature_matrix:      List[List[float]]
    labels:              List[int]
    edges:               List[Tuple[int, int, float]]
    node_meta:           List[Dict[str, Any]]
    source_backend_used: str
    edge_source_counts:  Dict[str, int] = field(default_factory=dict)
    positive_count:      int = 0
    negative_count:      int = 0
    benign_negative_count: int = 0


# ---------------------------------------------------------------------------
# Labelling
# ---------------------------------------------------------------------------

def weak_label(
    *,
    risk_flags: Sequence[str],
    event_count: int,
    source_count: int,
) -> int:
    """
    Generate a weak positive/negative label for training.

    Primary signal  — risk_flags from other workers (orthogonal to raw features).
    Secondary signal — high-volume multi-source threshold (mild circular dependency;
    kept as fallback for early deployment when risk_flags are sparse).
    """
    if any(flag in POSITIVE_RISK_FLAGS for flag in (risk_flags or [])):
        return 1
    # Secondary: only fires when no flags exist and both thresholds are met
    if event_count >= 25 and source_count >= 3:
        return 1
    return 0


# ---------------------------------------------------------------------------
# Feature engineering  (42-dim)
# ---------------------------------------------------------------------------

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
    """
    Build the 42-dimensional feature vector for a single entity snapshot.

    All features are either binary [0,1] or normalised continuous values.
    log1p is applied to counts for numerical stability.
    """
    flags       = set(risk_flags or [])
    f           = features or {}
    event_types = f.get("event_types") or {}
    if not isinstance(event_types, dict):
        event_types = {}

    # ------------------------------------------------------------------
    # Block 0: entity type one-hot (10 dims)
    # ------------------------------------------------------------------
    etype = (entity_type or "").lower().split(":")[0]
    type_vec = [1.0 if etype == t else 0.0 for t in ENTITY_TYPES_ORDERED]

    # ------------------------------------------------------------------
    # Block 1: volume signals (5 dims)
    # ------------------------------------------------------------------
    src  = int(f.get("source_count") or source_count or 0)
    ec   = max(0, int(event_count))
    deg  = max(0, int(degree))
    wdeg = max(0, int(weighted_degree))

    f_event   = math.log1p(ec)
    f_source  = math.log1p(src)
    f_degree  = math.log1p(deg)
    f_wdegree = math.log1p(wdeg)
    f_src_div = src / (ec + 1.0)        # source diversity: 0 if all events from 1 source

    # ------------------------------------------------------------------
    # Block 2: temporal signals (4 dims)
    # ------------------------------------------------------------------
    age_sec = f.get("last_seen_age_sec")
    if isinstance(age_sec, (int, float)) and age_sec >= 0:
        recency = 1.0 / (1.0 + float(age_sec) / 300.0)
    else:
        recency = 0.0

    # Event rate: events per hour (capped and normalised)
    win_hours = 1.0
    if window_start and window_end:
        span = (window_end - window_start).total_seconds()
        win_hours = max(1.0, span / 3600.0)
    event_rate = min(1.0, (ec / win_hours) / 100.0)

    # Window coverage: how much of the window this entity was active
    coverage = 0.0
    if first_seen and last_seen and window_start and window_end:
        w_span = max(1.0, (window_end - window_start).total_seconds())
        e_span = max(0.0, (last_seen - first_seen).total_seconds())
        coverage = min(1.0, e_span / w_span)

    night_flag = 0.0  # reserved for future telco hour-of-day signal

    # ------------------------------------------------------------------
    # Block 3: risk flags (6 dims)
    # ------------------------------------------------------------------
    flag_ddos    = 1.0 if ("DDOS_ALERT_SERVICE" in flags or "DDOS_ALERT_ENDPOINT" in flags) else 0.0
    flag_campaign = 1.0 if "CAMPAIGN_ENTITY" in flags else 0.0
    flag_vpn     = 1.0 if "VPN_CLUSTER_MEMBER" in flags else 0.0
    flag_ddos_cl = 1.0 if "DDOS_CLUSTER_MEMBER" in flags else 0.0
    flag_infra   = 1.0 if "INFRA_CLUSTER_MEMBER" in flags else 0.0
    flag_any     = 1.0 if flags else 0.0

    # ------------------------------------------------------------------
    # Block 4: event-type log counts (12 dims = 11 tracked + other)
    # ------------------------------------------------------------------
    event_type_vec = [math.log1p(max(0, int(event_types.get(et, 0)))) for et in TRACKED_EVENT_TYPES]
    other_count    = int(f.get("event_types_other_count") or 0)
    event_type_vec.append(math.log1p(max(0, other_count)))   # 12th slot = other

    # ------------------------------------------------------------------
    # Block 5: behavioural ratios (5 dims)
    # ------------------------------------------------------------------
    suspicious    = sum(int(event_types.get(t, 0)) for t in SUSPICIOUS_EVENT_TYPES)
    suspicious_r  = suspicious / max(1, ec)

    n_distinct    = len([v for v in event_types.values() if int(v or 0) > 0])
    multi_type    = 1.0 if n_distinct > 3 else 0.0

    txn_ct  = int(event_types.get("TRANSACTION_EVENT", 0))
    login_ct = int(event_types.get("LOGIN_EVENT", 0))
    sim_ct   = int(event_types.get("SIM_SWAP_EVENT", 0))

    txn_to_login = min(1.0, txn_ct  / max(1, login_ct))
    sim_to_login = min(1.0, sim_ct  / max(1, login_ct + 1))
    txn_spike    = 1.0 if txn_ct > 10 else 0.0

    # ------------------------------------------------------------------
    # Assemble (must sum to FEATURE_DIM = 42)
    # ------------------------------------------------------------------
    vec = (
        type_vec                                                    # 10
        + [f_event, f_source, f_degree, f_wdegree, f_src_div]      # 5
        + [recency, event_rate, coverage, night_flag]               # 4
        + [flag_ddos, flag_campaign, flag_vpn,
           flag_ddos_cl, flag_infra, flag_any]                      # 6
        + event_type_vec                                            # 12
        + [suspicious_r, multi_type, txn_to_login,
           sim_to_login, txn_spike]                                 # 5
    )
    assert len(vec) == FEATURE_DIM, f"feature dim mismatch: got {len(vec)}, expected {FEATURE_DIM}"
    return vec


# ---------------------------------------------------------------------------
# Benign candidate detection
# ---------------------------------------------------------------------------

def _is_benign_candidate(
    *,
    risk_flags:  Sequence[str],
    event_count: int,
    source_count: int,
    event_types:  Dict[str, int],
) -> bool:
    if risk_flags:
        return False
    if source_count > 2 or event_count > 12:
        return False
    if sum(int(event_types.get(t, 0)) for t in SUSPICIOUS_EVENT_TYPES) > 0:
        return False
    benign_hits = sum(int(event_types.get(t, 0)) for t in BENIGN_EVENT_TYPES)
    return benign_hits > 0 or event_count <= 3


# ---------------------------------------------------------------------------
# Edge extraction helpers
# ---------------------------------------------------------------------------

def collapse_edges(edges: Sequence[Tuple[str, str, float]]) -> List[Tuple[str, str, float]]:
    """Deduplicate and sum weights for bidirectional (src < dst) edge pairs."""
    rolled: Dict[Tuple[str, str], float] = {}
    for src, dst, w in edges:
        if not src or not dst or src == dst:
            continue
        a, b = (src, dst) if src < dst else (dst, src)
        rolled[(a, b)] = rolled.get((a, b), 0.0) + float(w)
    out = [(a, b, round(w, 6)) for (a, b), w in rolled.items()]
    out.sort(key=lambda x: x[2], reverse=True)
    return out


def _edges_from_postgres(
    db: Session,
    *,
    entity_keys: List[str],
    window_start: datetime,
    window_end: datetime,
    min_edge_weight: int,
    max_edges: int,
) -> List[Tuple[str, str, float]]:
    """Co-occurrence edges: two entities sharing an event get an edge."""
    if not entity_keys:
        return []

    rows = db.execute(
        text(
            """
            SELECT
                a.entity_key AS src,
                b.entity_key AS dst,
                COUNT(*)::float AS weight
            FROM event_entity_index a
            JOIN event_entity_index b
              ON a.event_hash = b.event_hash
             AND a.entity_key < b.entity_key
            JOIN event_log el ON el.event_hash = a.event_hash
            WHERE el.occurred_at >= :window_start
              AND el.occurred_at <= :window_end
              AND a.entity_key = ANY(:entity_keys)
              AND b.entity_key = ANY(:entity_keys)
            GROUP BY a.entity_key, b.entity_key
            HAVING COUNT(*) >= :min_edge_weight
            ORDER BY weight DESC
            LIMIT :max_edges
            """
        ),
        {
            "window_start":    window_start,
            "window_end":      window_end,
            "entity_keys":     entity_keys,
            "min_edge_weight": max(1, int(min_edge_weight)),
            "max_edges":       max(1, int(max_edges)),
        },
    ).fetchall()

    return [(str(r[0]), str(r[1]), float(r[2] or 0.0)) for r in rows]


def _parse_entity_key(entity_key: str) -> Tuple[str, str]:
    if ":" not in entity_key:
        return entity_key, ""
    prefix, raw = entity_key.split(":", 1)
    return prefix.strip(), raw.strip()


def entity_key_to_neo4j_ref(entity_key: str) -> Optional[Tuple[str, str]]:
    prefix, raw = _parse_entity_key(entity_key)
    label = ENTITY_PREFIX_TO_NEO4J.get(prefix)
    if not label:
        return None
    if prefix in {"account_h", "phone_h", "person_h"}:
        return label, f"{prefix}:{raw}"
    return label, raw


def _edges_from_neo4j(
    *,
    entity_keys: List[str],
    max_edges: int,
) -> List[Tuple[str, str, float]]:
    """Structural edges from the Neo4j graph projection."""
    if not entity_keys:
        return []

    ref_to_entity: Dict[str, str]       = {}
    endpoint_raw_to_entity: Dict[str, str] = {}
    refs: List[str] = []

    for ek in entity_keys:
        prefix, raw = _parse_entity_key(ek)
        ref = entity_key_to_neo4j_ref(ek)
        if not ref:
            if prefix == "endpoint" and raw:
                endpoint_raw_to_entity[raw] = ek
            continue
        label, key = ref
        node_ref = f"{label}|{key}"
        ref_to_entity[node_ref] = ek
        refs.append(node_ref)
        if prefix == "endpoint" and raw:
            endpoint_raw_to_entity[raw] = ek

    endpoint_raws = sorted(endpoint_raw_to_entity.keys())
    if not refs and not endpoint_raws:
        return []

    query = """
    MATCH (a)-[r]-(b)
    WITH a, b, r, head(labels(a)) AS src_label, head(labels(b)) AS dst_label
    WHERE src_label IS NOT NULL AND dst_label IS NOT NULL
      AND (
        (src_label + '|' + a.key) IN $node_refs
        OR (src_label = 'Endpoint'
            AND any(raw IN $endpoint_raws
                    WHERE a.key = raw OR a.key ENDS WITH (':' + raw)))
      )
      AND (
        (dst_label + '|' + b.key) IN $node_refs
        OR (dst_label = 'Endpoint'
            AND any(raw IN $endpoint_raws
                    WHERE b.key = raw OR b.key ENDS WITH (':' + raw)))
      )
      AND (src_label + '|' + a.key) < (dst_label + '|' + b.key)
    RETURN src_label, a.key AS src_key, dst_label, b.key AS dst_key,
           count(r) AS weight
    ORDER BY weight DESC
    LIMIT $max_edges
    """

    driver = get_driver()
    try:
        with driver.session() as sess:
            rows = sess.run(
                query,
                node_refs=refs,
                endpoint_raws=endpoint_raws,
                max_edges=max(1, int(max_edges)),
            )
            out: List[Tuple[str, str, float]] = []

            def _resolve(label: str, key: str) -> Optional[str]:
                exact = ref_to_entity.get(f"{label}|{key}")
                if exact:
                    return exact
                if label == "Endpoint":
                    if key in endpoint_raw_to_entity:
                        return endpoint_raw_to_entity[key]
                    if ":" in key:
                        _, raw = key.split(":", 1)
                        return endpoint_raw_to_entity.get(raw)
                return None

            for r in rows:
                src = _resolve(str(r.get("src_label") or ""), str(r.get("src_key") or ""))
                dst = _resolve(str(r.get("dst_label") or ""), str(r.get("dst_key") or ""))
                if src and dst and src != dst:
                    out.append((src, dst, float(r.get("weight") or 0.0)))
            return out
    finally:
        try:
            driver.close()
        except Exception:  # noqa: BLE001
            pass


def _latest_window_end(db: Session, window_key: str) -> Optional[datetime]:
    return (
        db.query(func.max(GraphFeatureSnapshot.window_end))
        .filter(GraphFeatureSnapshot.window_key == window_key)
        .scalar()
    )


# ---------------------------------------------------------------------------
# Dataset loader
# ---------------------------------------------------------------------------

def load_dataset(
    db: Session,
    *,
    window_key:          str = "Wmid",
    window_end:          Optional[datetime] = None,
    max_entities:        int = 3000,
    edge_backend:        str = "hybrid",
    min_edge_weight:     int = 1,
    max_edges:           int = 30_000,
    negative_multiplier: float = 1.5,
) -> Optional[GNNDataset]:
    """
    Build a GNNDataset from the current state of the feature store.

    Sampling strategy (prevents class imbalance pathology):
        1. All positives (risk_flag entities) up to pos_quota
        2. Benign negatives (confirmed low-risk) — cleanest negative signal
        3. Remaining other negatives (ambiguous but useful)
    """
    if max_entities is not None and int(max_entities) <= 0:
        return None
    if window_end is None:
        window_end = _latest_window_end(db, window_key)
    if window_end is None:
        return None

    candidate_limit = max(200, int(max_entities) * 4)
    snapshots = (
        db.query(GraphFeatureSnapshot)
        .filter(GraphFeatureSnapshot.window_key == window_key)
        .filter(GraphFeatureSnapshot.window_end == window_end)
        .order_by(GraphFeatureSnapshot.event_count.desc())
        .limit(candidate_limit)
        .all()
    )
    if not snapshots:
        return None

    entries: List[Dict[str, Any]] = []
    for s in snapshots:
        risk_flags   = list(s.risk_flags or [])
        features_raw = dict(s.features or {})
        event_types  = features_raw.get("event_types") if isinstance(features_raw.get("event_types"), dict) else {}
        source_count = int(features_raw.get("source_count") or 0)
        event_count  = int(s.event_count or 0)
        label        = weak_label(
            risk_flags=risk_flags,
            event_count=event_count,
            source_count=source_count,
        )
        entries.append({
            "snap":          s,
            "entity_key":    str(s.entity_key),
            "entity_type":   str(s.entity_type),
            "risk_flags":    risk_flags,
            "features":      features_raw,
            "event_types":   dict(event_types),
            "source_count":  source_count,
            "event_count":   event_count,
            "degree":        int(s.degree or 0),
            "weighted_degree": int(s.weighted_degree or 0),
            "window_start":  s.window_start,
            "window_end":    s.window_end,
            "first_seen":    s.first_seen,
            "last_seen":     s.last_seen,
            "label":         label,
            "is_benign": _is_benign_candidate(
                risk_flags=risk_flags,
                event_count=event_count,
                source_count=source_count,
                event_types=dict(event_types),
            ),
        })

    positives       = sorted([e for e in entries if e["label"] == 1],
                              key=lambda x: (-x["event_count"], x["entity_key"]))
    benign_negatives = sorted([e for e in entries if e["label"] == 0 and e["is_benign"]],
                               key=lambda x: (x["event_count"], x["entity_key"]))
    other_negatives  = sorted([e for e in entries if e["label"] == 0 and not e["is_benign"]],
                               key=lambda x: (x["event_count"], x["entity_key"]))

    selected: List[Dict[str, Any]] = []
    neg_mult = max(0.0, float(negative_multiplier))

    if positives:
        pos_quota = max(1, int(max_entities / (1.0 + neg_mult))) if neg_mult > 0 else max_entities
        selected.extend(positives[:pos_quota])
        remaining = max(0, max_entities - len(selected))
        selected.extend(benign_negatives[:remaining])
        remaining = max(0, max_entities - len(selected))
        if remaining > 0:
            selected.extend(other_negatives[:remaining])
        remaining = max(0, max_entities - len(selected))
        if remaining > 0 and len(positives) > pos_quota:
            selected.extend(positives[pos_quota: pos_quota + remaining])
    else:
        selected.extend(benign_negatives[:max_entities])
        remaining = max(0, max_entities - len(selected))
        if remaining > 0:
            selected.extend(other_negatives[:remaining])

    if not selected:
        return None
    selected = selected[:max_entities]

    entity_keys:    List[str]          = []
    entity_types:   List[str]          = []
    feature_matrix: List[List[float]]  = []
    labels:         List[int]          = []
    node_meta:      List[Dict[str, Any]] = []

    for e in selected:
        entity_keys.append(e["entity_key"])
        entity_types.append(e["entity_type"])
        feature_matrix.append(
            build_feature_vector(
                entity_type    = e["entity_type"],
                event_count    = e["event_count"],
                source_count   = e["source_count"],
                degree         = e["degree"],
                weighted_degree= e["weighted_degree"],
                risk_flags     = e["risk_flags"],
                features       = e["features"],
                window_start   = e["window_start"],
                window_end     = e["window_end"],
                first_seen     = e["first_seen"],
                last_seen      = e["last_seen"],
            )
        )
        labels.append(int(e["label"]))
        node_meta.append({
            "entity_key":        e["entity_key"],
            "entity_type":       e["entity_type"],
            "event_count":       e["event_count"],
            "source_count":      e["source_count"],
            "risk_flags":        e["risk_flags"],
            "event_types":       e["event_types"],
            "is_benign_negative": bool(e["label"] == 0 and e["is_benign"]),
        })

    key_to_idx = {k: i for i, k in enumerate(entity_keys)}

    raw_edges: List[Tuple[str, str, float]] = []
    backend = (edge_backend or "hybrid").lower().strip()
    edge_source_counts: Dict[str, int] = {}
    backend_used: List[str] = []

    if backend in {"neo4j", "hybrid"}:
        try:
            neo_edges = _edges_from_neo4j(entity_keys=entity_keys, max_edges=max_edges)
            raw_edges.extend(neo_edges)
            edge_source_counts["neo4j"] = len(neo_edges)
            if neo_edges:
                backend_used.append("neo4j")
        except Exception:  # noqa: BLE001
            edge_source_counts["neo4j"] = 0
            if backend == "neo4j":
                raise

    if backend in {"postgres", "hybrid"}:
        pg_edges = _edges_from_postgres(
            db,
            entity_keys=entity_keys,
            window_start=selected[0]["snap"].window_start,
            window_end=window_end,
            min_edge_weight=min_edge_weight,
            max_edges=max_edges,
        )
        raw_edges.extend(pg_edges)
        edge_source_counts["postgres"] = len(pg_edges)
        if pg_edges:
            backend_used.append("postgres")

    collapsed = collapse_edges(raw_edges)
    edges: List[Tuple[int, int, float]] = []
    for src, dst, w in collapsed[:max_edges]:
        i = key_to_idx.get(src)
        j = key_to_idx.get(dst)
        if i is None or j is None or i == j:
            continue
        edges.append((i, j, float(w)))

    # Fallback chain: if no edges, create a minimal spanning path
    if not edges and len(entity_keys) > 1:
        for i in range(len(entity_keys) - 1):
            edges.append((i, i + 1, 1.0))

    used = "+".join(sorted(set(backend_used))) if backend_used else "none"
    benign_count = sum(1 for m, lbl in zip(node_meta, labels)
                       if lbl == 0 and m.get("is_benign_negative"))

    return GNNDataset(
        window_key=window_key,
        window_start=selected[0]["snap"].window_start,
        window_end=window_end,
        entity_keys=entity_keys,
        entity_types=entity_types,
        feature_matrix=feature_matrix,
        labels=labels,
        edges=edges,
        node_meta=node_meta,
        source_backend_used=used,
        edge_source_counts=edge_source_counts,
        positive_count=sum(labels),
        negative_count=len(labels) - sum(labels),
        benign_negative_count=benign_count,
    )

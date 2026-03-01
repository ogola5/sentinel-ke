from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
import logging
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.analytics.ai_models import (
    AIExplanation,
    AIPrediction,
    AICampaignRiskIndicator,
    AIRiskThreshold,
    AIAttackTechniqueHit,
    AILinkPrediction,
    AIModelLineage,
    EntityEmbedding,
    GNNTrainingRun,
)
from app.analytics.layer3.ai_intel import (
    build_counterfactual,
    event_types_to_attack_techniques,
    event_types_to_kill_chain_stage,
    reason_codes_to_d3fend_controls,
)
from app.analytics.layer3.gnn_backbone import GNNDataset, load_dataset
from app.analytics.layer3.gnn_model import train_graphsage
from app.campaign.models import Campaign, CampaignEntity
from app.core.config import settings
from app.core.security import compute_event_hash, sha256_hex, stable_json_dumps
from app.db.base import Base
from app.ledger.db import SessionLocal, engine
import app.db.registry  # noqa: F401


LEGAL_RISK_NOTICE = (
    "AI output is a risk indicator for investigative prioritization only; "
    "it is not final proof and requires legal/forensic corroboration."
)


COMPONENT_CAMPAIGN_TYPE = "GNN_COMPONENT"
COMPONENT_RULE_VERSION = "gnn.component.v1"
log = logging.getLogger("sentinel.gnn_train_worker")


def _ensure_ai_tables() -> None:
    Base.metadata.create_all(
        bind=engine,
        tables=[
            Campaign.__table__,
            CampaignEntity.__table__,
            EntityEmbedding.__table__,
            AIPrediction.__table__,
            AIExplanation.__table__,
            GNNTrainingRun.__table__,
            AIRiskThreshold.__table__,
            AICampaignRiskIndicator.__table__,
            AIAttackTechniqueHit.__table__,
            AILinkPrediction.__table__,
            AIModelLineage.__table__,
        ],
    )


def _event_hashes(
    db: Session,
    *,
    entity_key: str,
    window_start: datetime,
    window_end: datetime,
    limit: int = 20,
) -> List[str]:
    rows = db.execute(
        text(
            """
            SELECT ee.event_hash
            FROM event_entity_index ee
            JOIN event_log el ON el.event_hash = ee.event_hash
            WHERE ee.entity_key = :entity_key
              AND el.occurred_at >= :start
              AND el.occurred_at <= :end
            ORDER BY el.occurred_at DESC
            LIMIT :limit
            """
        ),
        {
            "entity_key": entity_key,
            "start": window_start,
            "end": window_end,
            "limit": limit,
        },
    ).fetchall()
    return [str(r[0]) for r in rows]


def _severity_from_score(score: float) -> str:
    s = float(score)
    if s >= 90.0:
        return "critical"
    if s >= 75.0:
        return "high"
    if s >= 55.0:
        return "medium"
    return "low"


def _default_threshold(entity_type: str) -> float:
    et = (entity_type or "").lower()
    if et in {"ip", "domain", "url", "endpoint", "service_id"}:
        return 78.0
    if et in {"account_h", "phone_h", "person_h", "device_id"}:
        return 70.0
    return 75.0


def _reason_codes(meta: Dict[str, object], prob: float, is_indicator: bool) -> List[str]:
    reasons: List[str] = []
    risk_flags = set(meta.get("risk_flags") or [])
    event_count = int(meta.get("event_count") or 0)
    source_count = int(meta.get("source_count") or 0)
    event_types = meta.get("event_types") or {}

    if prob >= 0.9:
        reasons.append("GNN_RISK_CRITICAL")
    elif prob >= 0.75:
        reasons.append("GNN_RISK_HIGH")
    elif prob >= 0.55:
        reasons.append("GNN_RISK_ELEVATED")
    else:
        reasons.append("GNN_RISK_LOW")

    if source_count >= 3:
        reasons.append("MULTI_SOURCE")
    if event_count >= 20:
        reasons.append("EVENT_VOLUME_HIGH")
    elif event_count >= 8:
        reasons.append("EVENT_VOLUME_MED")

    if "CAMPAIGN_ENTITY" in risk_flags:
        reasons.append("CAMPAIGN_LINKED")
    if "VPN_CLUSTER_MEMBER" in risk_flags:
        reasons.append("VPN_INFRA_REUSE")
    if "DDOS_CLUSTER_MEMBER" in risk_flags:
        reasons.append("DDOS_INFRA_REUSE")
    if "DDOS_ALERT_SERVICE" in risk_flags or "DDOS_ALERT_ENDPOINT" in risk_flags:
        reasons.append("DDOS_ALERT_ACTIVE")

    if isinstance(event_types, dict):
        ranked = sorted(
            ((str(k), int(v or 0)) for k, v in event_types.items()),
            key=lambda x: x[1],
            reverse=True,
        )
        for name, count in ranked[:2]:
            if count > 0:
                reasons.append(f"TOP_EVENT_{name}")

    reasons.append("RISK_INDICATOR_ONLY_NOT_FINAL_PROOF")
    if is_indicator:
        reasons.append("THRESHOLD_EXCEEDED")
    else:
        reasons.append("THRESHOLD_NOT_EXCEEDED")
    return sorted(set(reasons))


def _persist_artifact(
    *,
    run_id: str,
    model_state,
    artifact_dir: str,
    metadata: Dict[str, object],
) -> Optional[str]:
    try:
        import torch
    except Exception as exc:
        log.warning("gnn_artifact_persist_failed torch_missing error=%s", exc)
        return None

    payload = {
        "model_state": model_state,
        "metadata": metadata,
    }

    def _attempt_save(out_dir: Path) -> Optional[str]:
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{run_id}.pt"
        torch.save(payload, str(out_path))
        return str(out_path)

    try:
        return _attempt_save(Path(artifact_dir))
    except Exception as exc:
        log.warning("gnn_artifact_primary_path_failed dir=%s error=%s", artifact_dir, exc)

    try:
        fallback_root = Path(__file__).resolve().parents[3] / "artifacts" / "gnn"
        return _attempt_save(fallback_root)
    except Exception as exc:
        log.warning("gnn_artifact_fallback_failed error=%s", exc)
        return None


def _upsert_embeddings(
    db: Session,
    *,
    dataset: GNNDataset,
    model_version: str,
    embeddings: List[List[float]],
) -> int:
    if not embeddings:
        return 0

    rows = []
    for i, emb in enumerate(embeddings):
        rows.append(
            {
                "entity_key": dataset.entity_keys[i],
                "entity_type": dataset.entity_types[i],
                "window_key": dataset.window_key,
                "window_end": dataset.window_end,
                "model_version": model_version,
                "embedding": [round(float(v), 6) for v in emb],
            }
        )

    stmt = insert(EntityEmbedding).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["entity_key", "window_key", "window_end", "model_version"],
        set_={"embedding": stmt.excluded.embedding},
    )
    res = db.execute(stmt)
    return int(res.rowcount or 0)


def _lineage_signature(payload: Dict[str, object]) -> str:
    secret = settings.ai_lineage_signing_secret or "local-dev-lineage-secret"
    canonical = stable_json_dumps(payload).encode("utf-8")
    return sha256_hex(secret.encode("utf-8") + b":" + canonical)


def _persist_model_lineage(
    db: Session,
    *,
    run: GNNTrainingRun,
    dataset: GNNDataset,
    params_json: Dict[str, object],
) -> str:
    payload = {
        "model_version": run.model_version,
        "prediction_type": run.prediction_type,
        "window_key": run.window_key,
        "window_end": run.window_end.isoformat(),
        "entity_keys_hash": compute_event_hash({"entity_keys": sorted(dataset.entity_keys)}),
        "feature_dim": len(dataset.feature_matrix[0]) if dataset.feature_matrix else 0,
        "params": params_json,
    }
    dataset_hash = compute_event_hash(
        {
            "entity_keys": sorted(dataset.entity_keys),
            "labels": [int(v) for v in dataset.labels],
            "window_key": dataset.window_key,
            "window_end": dataset.window_end.isoformat(),
        }
    )
    params_hash = compute_event_hash(params_json)
    code_hash = sha256_hex(f"{__name__}:gnn_train_worker:v2".encode("utf-8"))
    signature = _lineage_signature(payload)

    row = (
        db.query(AIModelLineage)
        .filter(AIModelLineage.model_version == run.model_version)
        .filter(AIModelLineage.prediction_type == run.prediction_type)
        .first()
    )
    lineage_id = row.lineage_id if row else str(run.id)
    if row:
        row.training_run_id = run.id
        row.dataset_hash = dataset_hash
        row.params_hash = params_hash
        row.code_hash = code_hash
        row.lineage_signature = signature
        row.metadata_json = payload
    else:
        db.add(
            AIModelLineage(
                lineage_id=lineage_id,
                model_version=run.model_version,
                prediction_type=run.prediction_type,
                training_run_id=run.id,
                dataset_hash=dataset_hash,
                params_hash=params_hash,
                code_hash=code_hash,
                lineage_signature=signature,
                metadata_json=payload,
            )
        )
    return lineage_id


def _upsert_attack_techniques(
    db: Session,
    *,
    dataset: GNNDataset,
    probabilities: Sequence[float],
    prediction_type: str,
) -> int:
    rows: List[Dict[str, object]] = []
    for i, entity_key in enumerate(dataset.entity_keys):
        meta = dataset.node_meta[i] if i < len(dataset.node_meta) else {}
        event_types = dict((meta or {}).get("event_types") or {})
        techniques = event_types_to_attack_techniques(event_types)
        for t in techniques:
            rows.append(
                {
                    "entity_key": entity_key,
                    "prediction_type": prediction_type,
                    "window_key": dataset.window_key,
                    "window_end": dataset.window_end,
                    "technique_id": str(t.get("technique_id") or ""),
                    "tactic": str(t.get("tactic") or "") or None,
                    "confidence": float(t.get("confidence") or float(probabilities[i])),
                    "source_json": {
                        **t,
                        "probability": float(probabilities[i]),
                    },
                }
            )
    if not rows:
        return 0

    stmt = insert(AIAttackTechniqueHit).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=[
            "entity_key",
            "prediction_type",
            "window_key",
            "window_end",
            "technique_id",
        ],
        set_={
            "tactic": stmt.excluded.tactic,
            "confidence": stmt.excluded.confidence,
            "source_json": stmt.excluded.source_json,
            "created_at": stmt.excluded.created_at,
        },
    )
    res = db.execute(stmt)
    return int(res.rowcount or 0)


def _upsert_link_predictions(
    db: Session,
    *,
    dataset: GNNDataset,
    embeddings: Sequence[Sequence[float]],
    model_version: str,
    prediction_type: str,
    max_rows: int = 2000,
) -> int:
    if not embeddings or len(embeddings) != len(dataset.entity_keys):
        return 0

    rows: List[Dict[str, object]] = []
    n = len(dataset.entity_keys)

    def _dot(a: Sequence[float], b: Sequence[float]) -> float:
        return float(sum(float(x) * float(y) for x, y in zip(a, b)))

    for i in range(n):
        for j in range(i + 1, n):
            score = _dot(embeddings[i], embeddings[j])
            if score <= 0:
                continue
            rows.append(
                {
                    "src_entity_key": dataset.entity_keys[i],
                    "dst_entity_key": dataset.entity_keys[j],
                    "prediction_type": prediction_type,
                    "model_version": model_version,
                    "window_key": dataset.window_key,
                    "window_end": dataset.window_end,
                    "score": round(score, 6),
                    "method": "embedding_dot",
                    "details_json": {"feature_dim": len(embeddings[i])},
                }
            )

    if not rows:
        return 0

    rows.sort(key=lambda r: float(r["score"]), reverse=True)
    rows = rows[: max(1, int(max_rows))]
    stmt = insert(AILinkPrediction).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=[
            "src_entity_key",
            "dst_entity_key",
            "prediction_type",
            "model_version",
            "window_key",
            "window_end",
        ],
        set_={
            "score": stmt.excluded.score,
            "method": stmt.excluded.method,
            "details_json": stmt.excluded.details_json,
            "created_at": stmt.excluded.created_at,
        },
    )
    res = db.execute(stmt)
    return int(res.rowcount or 0)


def _compute_fairness_metrics(
    *,
    entity_types: Sequence[str],
    labels: Sequence[int],
    probabilities: Sequence[float],
    threshold: float = 0.5,
    min_group_size: int = 3,
) -> Dict[str, object]:
    """
    Compute per-entity-type fairness metrics (demographic parity + equalized odds).

    Returns a dict suitable for storing in metrics_json["fairness"].
    No new dependencies — pure Python arithmetic only.

    Metrics per entity_type subgroup:
      positive_rate          P(ŷ=1 | type)  — demographic parity check
      actual_positive_rate   P(y=1 | type)  — calibration check
      precision              TP/(TP+FP)     — equalized odds (positive predictive value)
      recall                 TP/(TP+FN)     — equalized odds (true positive rate)
      count / positive_count — sample sizes for context

    Summary scalars:
      max_positive_rate_disparity   max - min positive_rate across evaluated types
      max_recall_disparity          max - min recall across evaluated types
      types_evaluated               groups with >= min_group_size samples
      fairness_flag                 PASS (<0.25 disparity) / WARN (<0.40) / FAIL
    """
    groups: Dict[str, Dict[str, List]] = {}
    for etype, y, prob in zip(entity_types, labels, probabilities):
        g = groups.setdefault(str(etype), {"y": [], "prob": []})
        g["y"].append(int(y))
        g["prob"].append(float(prob))

    per_type: Dict[str, Dict[str, object]] = {}
    positive_rates: List[float] = []
    recalls: List[float] = []

    for etype, g in groups.items():
        n = len(g["y"])
        if n < min_group_size:
            per_type[etype] = {"count": n, "skipped": True, "reason": "too_few_samples"}
            continue

        y_true = g["y"]
        y_pred = [1 if p >= threshold else 0 for p in g["prob"]]

        tp = sum(1 for a, b in zip(y_true, y_pred) if a == 1 and b == 1)
        fp = sum(1 for a, b in zip(y_true, y_pred) if a == 0 and b == 1)
        fn = sum(1 for a, b in zip(y_true, y_pred) if a == 1 and b == 0)

        pos_rate        = sum(y_pred) / n
        actual_pos_rate = sum(y_true) / n
        precision       = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall          = tp / (tp + fn) if (tp + fn) > 0 else 0.0

        per_type[etype] = {
            "count":               n,
            "positive_count":      sum(y_true),
            "positive_rate":       round(pos_rate, 4),
            "actual_positive_rate": round(actual_pos_rate, 4),
            "precision":           round(precision, 4),
            "recall":              round(recall, 4),
        }
        positive_rates.append(pos_rate)
        recalls.append(recall)

    if len(positive_rates) >= 2:
        max_pr_disp = round(max(positive_rates) - min(positive_rates), 4)
        max_rc_disp = round(max(recalls) - min(recalls), 4) if len(recalls) >= 2 else None
    else:
        max_pr_disp = None
        max_rc_disp = None

    if max_pr_disp is None:
        flag = "INSUFFICIENT_DATA"
    elif max_pr_disp < 0.25:
        flag = "PASS"
    elif max_pr_disp < 0.40:
        flag = "WARN"
    else:
        flag = "FAIL"

    return {
        "per_type":                    per_type,
        "max_positive_rate_disparity": max_pr_disp,
        "max_recall_disparity":        max_rc_disp,
        "types_evaluated":             len(positive_rates),
        "fairness_flag":               flag,
        "threshold_used":              threshold,
    }


def _f1_for_threshold(labels: Sequence[int], scores: Sequence[float], thr: float) -> float:
    y_true = [int(v) for v in labels]
    y_pred = [1 if float(s) >= thr else 0 for s in scores]

    tp = sum(1 for yt, yp in zip(y_true, y_pred) if yt == 1 and yp == 1)
    fp = sum(1 for yt, yp in zip(y_true, y_pred) if yt == 0 and yp == 1)
    fn = sum(1 for yt, yp in zip(y_true, y_pred) if yt == 1 and yp == 0)

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    return (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0


def _cost_weight_for_entity_type(entity_type: str) -> float:
    et = (entity_type or "").lower()
    if et in {"service_id", "endpoint", "ip", "domain", "url"}:
        return 1.35
    if et in {"device_id", "account_h", "phone_h"}:
        return 1.15
    return 1.0


def _calibrate_thresholds(
    *,
    dataset: GNNDataset,
    probabilities: List[float],
    min_samples: int,
    model_version: str,
    prediction_type: str,
) -> Dict[str, Dict[str, object]]:
    per_type: Dict[str, List[Tuple[int, float]]] = {}
    for etype, label, prob in zip(dataset.entity_types, dataset.labels, probabilities):
        per_type.setdefault(str(etype), []).append((int(label), float(prob)))

    thresholds: Dict[str, Dict[str, object]] = {}
    candidates = [round(x, 2) for x in [i / 100 for i in range(35, 96, 5)]]

    for etype, vals in per_type.items():
        labels = [v[0] for v in vals]
        probs = [v[1] for v in vals]

        sample_count = len(vals)
        positive_count = int(sum(labels))

        if sample_count < max(3, int(min_samples)):
            thr_score = _default_threshold(etype)
            cost_weight = _cost_weight_for_entity_type(etype)
            thresholds[etype] = {
                "threshold_score": thr_score,
                "method": "default_by_entity_type",
                "sample_count": sample_count,
                "positive_count": positive_count,
                "cost_weight": cost_weight,
                "metrics": {
                    "f1": None,
                    "threshold_probability": thr_score / 100.0,
                    "objective": "cost_weighted_f1",
                },
                "model_version": model_version,
                "prediction_type": prediction_type,
            }
            continue

        best_thr = 0.75
        best_f1 = -1.0
        cost_weight = _cost_weight_for_entity_type(etype)
        best_score = float("-inf")
        for thr in candidates:
            f1 = _f1_for_threshold(labels, probs, thr)
            # Higher weights bias the optimizer toward recall-sensitive thresholds
            # for critical infrastructure entities.
            objective = f1 + (cost_weight - 1.0) * max(0.0, 0.8 - thr)
            if objective > best_score:
                best_score = objective
                best_f1 = f1
                best_thr = thr

        thresholds[etype] = {
            "threshold_score": round(best_thr * 100.0, 4),
            "method": "cost_weighted_f1_weak_label",
            "sample_count": sample_count,
            "positive_count": positive_count,
            "cost_weight": cost_weight,
            "metrics": {
                "f1": round(best_f1, 6),
                "threshold_probability": best_thr,
                "objective": "cost_weighted_f1",
                "objective_score": round(best_score, 6),
            },
            "model_version": model_version,
            "prediction_type": prediction_type,
        }

    return thresholds


def _persist_thresholds(
    db: Session,
    *,
    thresholds: Dict[str, Dict[str, object]],
    model_version: str,
    prediction_type: str,
    window_key: str,
    window_end: datetime,
) -> int:
    if not thresholds:
        return 0

    rows = []
    for etype, cfg in thresholds.items():
        rows.append(
            {
                "model_version": model_version,
                "prediction_type": prediction_type,
                "entity_type": etype,
                "window_key": window_key,
                "window_end": window_end,
                "threshold_score": float(cfg.get("threshold_score") or _default_threshold(etype)),
                "method": str(cfg.get("method") or "default_by_entity_type"),
                "sample_count": int(cfg.get("sample_count") or 0),
                "positive_count": int(cfg.get("positive_count") or 0),
                "cost_weight": float(cfg.get("cost_weight") or 1.0),
                "metrics_json": dict(cfg.get("metrics") or {}),
            }
        )

    stmt = insert(AIRiskThreshold).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=[
            "model_version",
            "prediction_type",
            "entity_type",
            "window_key",
            "window_end",
        ],
        set_={
            "threshold_score": stmt.excluded.threshold_score,
            "method": stmt.excluded.method,
            "sample_count": stmt.excluded.sample_count,
            "positive_count": stmt.excluded.positive_count,
            "cost_weight": stmt.excluded.cost_weight,
            "metrics_json": stmt.excluded.metrics_json,
            "created_at": stmt.excluded.created_at,
        },
    )
    res = db.execute(stmt)
    return int(res.rowcount or 0)


def _component_primary_key(
    *,
    prediction_type: str,
    window_key: str,
    window_end: datetime,
    entity_keys: Sequence[str],
) -> str:
    h = hashlib.sha256()
    h.update(str(prediction_type).encode("utf-8"))
    h.update(b"\n")
    h.update(str(window_key).encode("utf-8"))
    h.update(b"\n")
    h.update(window_end.isoformat().encode("utf-8"))
    h.update(b"\n")
    for k in sorted(set(entity_keys)):
        h.update(str(k).encode("utf-8"))
        h.update(b"\n")
    return f"gnn_component:{h.hexdigest()[:20]}"


def _connected_components(
    *,
    entity_keys: Sequence[str],
    edges: Sequence[Tuple[int, int, float]],
) -> List[List[str]]:
    if not entity_keys:
        return []

    adj: Dict[int, Set[int]] = {i: set() for i in range(len(entity_keys))}
    for i, j, _w in edges:
        if i == j:
            continue
        if i not in adj or j not in adj:
            continue
        adj[i].add(j)
        adj[j].add(i)

    seen: Set[int] = set()
    out: List[List[str]] = []

    for i in range(len(entity_keys)):
        if i in seen:
            continue
        stack = [i]
        seen.add(i)
        comp: List[int] = []
        while stack:
            cur = stack.pop()
            comp.append(cur)
            for nxt in adj.get(cur, set()):
                if nxt in seen:
                    continue
                seen.add(nxt)
                stack.append(nxt)
        out.append([str(entity_keys[idx]) for idx in sorted(comp)])

    out.sort(key=lambda x: (-len(x), x[0] if x else ""))
    return out


def _materialize_component_campaigns(
    db: Session,
    *,
    dataset: GNNDataset,
    prediction_type: str,
    indicators_by_entity: Dict[str, Dict[str, object]],
    enabled: bool,
    min_size: int,
    min_indicator_ratio: float,
) -> Dict[str, int]:
    if not enabled:
        return {"campaigns_created": 0, "campaigns_updated": 0, "entities_upserted": 0, "components_considered": 0}

    comps = _connected_components(entity_keys=dataset.entity_keys, edges=dataset.edges)

    campaigns_created = 0
    campaigns_updated = 0
    entities_upserted = 0
    components_considered = 0

    for comp in comps:
        components_considered += 1
        if len(comp) < max(2, int(min_size)):
            continue

        indicator_keys = [k for k in comp if bool((indicators_by_entity.get(k) or {}).get("risk_indicator"))]
        if not indicator_keys:
            continue

        ratio = len(indicator_keys) / max(1, len(comp))
        if ratio < max(0.0, float(min_indicator_ratio)):
            continue

        primary_key = _component_primary_key(
            prediction_type=prediction_type,
            window_key=dataset.window_key,
            window_end=dataset.window_end,
            entity_keys=comp,
        )

        max_score = max(float((indicators_by_entity.get(k) or {}).get("score") or 0.0) for k in comp)
        avg_score = (
            sum(float((indicators_by_entity.get(k) or {}).get("score") or 0.0) for k in comp)
            / max(1, len(comp))
        )

        campaign = (
            db.query(Campaign)
            .filter(Campaign.type == COMPONENT_CAMPAIGN_TYPE)
            .filter(Campaign.primary_key == primary_key)
            .first()
        )

        stats = {
            "discovery": "graph_connected_component",
            "window_key": dataset.window_key,
            "window_end": dataset.window_end.isoformat(),
            "component_size": len(comp),
            "indicator_count": len(indicator_keys),
            "indicator_ratio": round(ratio, 4),
            "avg_entity_score": round(avg_score, 4),
            "max_entity_score": round(max_score, 4),
            "legal_notice": LEGAL_RISK_NOTICE,
        }

        if campaign:
            campaign.last_seen = dataset.window_end
            campaign.first_seen = min(campaign.first_seen, dataset.window_start)
            campaign.event_count = max(int(campaign.event_count or 0), len(comp))
            campaign.score = max(float(campaign.score or 0.0), max_score / 100.0)
            campaign.status = "active"
            campaign.stats = stats
            campaigns_updated += 1
        else:
            campaign = Campaign(
                type=COMPONENT_CAMPAIGN_TYPE,
                primary_key=primary_key,
                status="active",
                rule_version=COMPONENT_RULE_VERSION,
                first_seen=dataset.window_start,
                last_seen=dataset.window_end,
                event_count=len(comp),
                score=round(max_score / 100.0, 6),
                stats=stats,
            )
            db.add(campaign)
            db.flush()
            campaigns_created += 1

        for entity_key in comp:
            s = indicators_by_entity.get(entity_key) or {}
            role = "indicator" if bool(s.get("risk_indicator")) else "member"
            stmt = insert(CampaignEntity).values(
                campaign_id=campaign.id,
                entity_key=entity_key,
                entity_type=str(s.get("entity_type") or "unknown"),
                role=role,
                last_seen=dataset.window_end,
            ).on_conflict_do_update(
                index_elements=["campaign_id", "entity_key"],
                set_={
                    "entity_type": str(s.get("entity_type") or "unknown"),
                    "role": role,
                    "last_seen": dataset.window_end,
                },
            )
            db.execute(stmt)
            entities_upserted += 1

    return {
        "campaigns_created": campaigns_created,
        "campaigns_updated": campaigns_updated,
        "entities_upserted": entities_upserted,
        "components_considered": components_considered,
    }


def _upsert_campaign_indicators(
    db: Session,
    *,
    model_version: str,
    prediction_type: str,
    window_key: str,
    window_end: datetime,
    thresholds: Dict[str, Dict[str, object]],
) -> Dict[str, int]:
    rows = db.execute(
        text(
            """
            SELECT
                c.id AS campaign_id,
                c.type AS campaign_type,
                c.primary_key AS campaign_key,
                ap.entity_key,
                ap.entity_type,
                ap.score
            FROM campaign c
            JOIN campaign_entity ce ON ce.campaign_id = c.id
            JOIN ai_prediction ap ON ap.entity_key = ce.entity_key
            WHERE ap.prediction_type = :prediction_type
              AND ap.window_key = :window_key
              AND ap.window_end = :window_end
            """
        ),
        {
            "prediction_type": prediction_type,
            "window_key": window_key,
            "window_end": window_end,
        },
    ).fetchall()

    grouped: Dict[str, Dict[str, object]] = {}
    for r in rows:
        cid = str(r[0])
        g = grouped.setdefault(
            cid,
            {
                "campaign_id": r[0],
                "campaign_type": str(r[1] or "unknown"),
                "campaign_key": str(r[2] or ""),
                "entities": [],
            },
        )
        g["entities"].append(
            {
                "entity_key": str(r[3]),
                "entity_type": str(r[4]),
                "score": float(r[5] or 0.0),
            }
        )

    created = 0
    updated = 0
    now = datetime.now(timezone.utc)

    for g in grouped.values():
        entities = list(g["entities"])
        if not entities:
            continue

        scored = sorted(entities, key=lambda x: float(x["score"]), reverse=True)
        total = len(scored)
        max_score = float(scored[0]["score"])
        avg_score = sum(float(x["score"]) for x in scored) / max(1, total)

        flagged = 0
        for x in scored:
            etype = str(x["entity_type"])
            threshold = float((thresholds.get(etype) or {}).get("threshold_score") or _default_threshold(etype))
            if float(x["score"]) >= threshold:
                flagged += 1

        flagged_ratio = flagged / max(1, total)
        score = round(min(100.0, 0.45 * avg_score + 0.35 * max_score + 0.2 * (flagged_ratio * 100.0)), 4)
        severity = _severity_from_score(score)

        reason_codes = [
            "CAMPAIGN_RISK_INDICATOR",
            "RISK_INDICATOR_ONLY_NOT_FINAL_PROOF",
        ]
        if flagged_ratio >= 0.6:
            reason_codes.append("HIGH_FRACTION_FLAGGED")
        if max_score >= 90:
            reason_codes.append("HAS_CRITICAL_ENTITY_SIGNAL")
        if str(g["campaign_type"]) == COMPONENT_CAMPAIGN_TYPE:
            reason_codes.append("DISCOVERED_FROM_GRAPH_COMPONENT")

        details = {
            "campaign_type": g["campaign_type"],
            "campaign_key": g["campaign_key"],
            "avg_entity_score": round(avg_score, 4),
            "max_entity_score": round(max_score, 4),
            "flagged_entity_ratio": round(flagged_ratio, 4),
            "legal_notice": LEGAL_RISK_NOTICE,
        }
        evidence_keys = [str(x["entity_key"]) for x in scored[:10]]

        existing = (
            db.query(AICampaignRiskIndicator)
            .filter(AICampaignRiskIndicator.campaign_id == g["campaign_id"])
            .filter(AICampaignRiskIndicator.prediction_type == prediction_type)
            .filter(AICampaignRiskIndicator.window_key == window_key)
            .filter(AICampaignRiskIndicator.window_end == window_end)
            .first()
        )

        if existing:
            existing.model_version = model_version
            existing.score = score
            existing.severity = severity
            existing.flagged_entity_count = flagged
            existing.total_entity_count = total
            existing.reason_codes = sorted(set(reason_codes))
            existing.details_json = details
            existing.evidence_entity_keys = evidence_keys
            existing.updated_at = now
            updated += 1
        else:
            db.add(
                AICampaignRiskIndicator(
                    campaign_id=g["campaign_id"],
                    prediction_type=prediction_type,
                    model_version=model_version,
                    window_key=window_key,
                    window_end=window_end,
                    score=score,
                    severity=severity,
                    flagged_entity_count=flagged,
                    total_entity_count=total,
                    reason_codes=sorted(set(reason_codes)),
                    details_json=details,
                    evidence_entity_keys=evidence_keys,
                    created_at=now,
                    updated_at=now,
                )
            )
            created += 1

    return {"created": created, "updated": updated}


def run_once(
    *,
    db: Session,
    window_key: str,
    window_end: Optional[datetime] = None,
    edge_backend: str = "hybrid",
    max_entities: int = 3000,
    max_edges: int = 30000,
    min_edge_weight: int = 1,
    negative_multiplier: float = 1.5,
    threshold_min_samples: int = 10,
    component_discovery_enabled: bool = True,
    component_min_size: int = 3,
    component_min_indicator_ratio: float = 0.5,
    epochs: int = 60,
    hidden_dim: int = 64,
    embed_dim: int = 32,
    dropout: float = 0.2,
    learning_rate: float = 0.001,
    weight_decay: float = 0.0001,
    temporal_decay: float = 0.015,
    pretrain_epochs: int = 5,
    seed: int = 7,
    uncertainty_abstain_threshold: float = 0.45,
    model_version: str = "gnn-sage-v1",
    prediction_type: str = "risk_gnn",
    artifact_dir: str = "/app/artifacts/gnn",
) -> Dict[str, object]:
    _ensure_ai_tables()

    try:
        dataset = load_dataset(
            db,
            window_key=window_key,
            window_end=window_end,
            max_entities=max_entities,
            edge_backend=edge_backend,
            min_edge_weight=min_edge_weight,
            max_edges=max_edges,
            negative_multiplier=negative_multiplier,
        )
    except Exception as exc:
        db.rollback()
        return {"status": "error", "stage": "load_dataset", "detail": str(exc)}
    if dataset is None:
        return {"status": "no_data", "created": 0, "updated": 0}
    if not dataset.feature_matrix or not dataset.feature_matrix[0]:
        return {"status": "no_features", "created": 0, "updated": 0}

    try:
        train_result = train_graphsage(
            dataset,
            epochs=epochs,
            hidden_dim=hidden_dim,
            embed_dim=embed_dim,
            dropout=dropout,
            learning_rate=learning_rate,
            weight_decay=weight_decay,
            seed=seed,
            temporal_decay=temporal_decay,
            pretrain_epochs=pretrain_epochs,
        )
    except Exception as exc:
        db.rollback()
        return {"status": "error", "stage": "train_graphsage", "detail": str(exc)}

    try:
        thresholds = _calibrate_thresholds(
            dataset=dataset,
            probabilities=train_result.probabilities,
            min_samples=threshold_min_samples,
            model_version=model_version,
            prediction_type=prediction_type,
        )

        fairness = _compute_fairness_metrics(
            entity_types=dataset.entity_types,
            labels=dataset.labels,
            probabilities=train_result.probabilities,
        )
        if fairness.get("fairness_flag") == "FAIL":
            log.warning(
                "fairness_policy_violation model_version=%s max_positive_rate_disparity=%.3f",
                model_version,
                fairness.get("max_positive_rate_disparity", 0),
            )

        run = GNNTrainingRun(
            model_version=model_version,
            prediction_type=prediction_type,
            source_backend=dataset.source_backend_used,
            window_key=dataset.window_key,
            window_end=dataset.window_end,
            node_count=len(dataset.entity_keys),
            edge_count=len(dataset.edges),
            feature_dim=len(dataset.feature_matrix[0]) if dataset.feature_matrix else 0,
            positive_count=sum(int(v) for v in dataset.labels),
            epochs=int(epochs),
            train_loss=float(train_result.metrics.get("train_loss") or 0.0),
            val_loss=float(train_result.metrics.get("val_loss") or 0.0),
            auc=float(train_result.metrics.get("auc") or 0.0),
            precision=float(train_result.metrics.get("precision") or 0.0),
            recall=float(train_result.metrics.get("recall") or 0.0),
            f1=float(train_result.metrics.get("f1") or 0.0),
            params_json={
                "edge_backend": edge_backend,
                "max_entities": max_entities,
                "max_edges": max_edges,
                "min_edge_weight": min_edge_weight,
                "negative_multiplier": negative_multiplier,
                "threshold_min_samples": threshold_min_samples,
                "component_discovery_enabled": component_discovery_enabled,
                "component_min_size": component_min_size,
                "component_min_indicator_ratio": component_min_indicator_ratio,
                "epochs": epochs,
                "hidden_dim": hidden_dim,
                "embed_dim": embed_dim,
                "dropout": dropout,
                "learning_rate": learning_rate,
                "weight_decay": weight_decay,
                "temporal_decay": temporal_decay,
                "pretrain_epochs": pretrain_epochs,
                "seed": seed,
                "uncertainty_abstain_threshold": uncertainty_abstain_threshold,
            },
            metrics_json={
                **train_result.metrics,
                "edge_source_counts": dataset.edge_source_counts,
                "positive_count": dataset.positive_count,
                "negative_count": dataset.negative_count,
                "benign_negative_count": dataset.benign_negative_count,
                "fairness": fairness,
            },
        )
        db.add(run)
        db.flush()

        artifact_path = _persist_artifact(
            run_id=str(run.id),
            model_state=train_result.model_state,
            artifact_dir=artifact_dir,
            metadata={
                "model_version": model_version,
                "prediction_type": prediction_type,
                "window_key": dataset.window_key,
                "window_end": dataset.window_end.isoformat(),
                "feature_dim": len(dataset.feature_matrix[0]) if dataset.feature_matrix else 0,
                "hidden_dim": hidden_dim,
                "embed_dim": embed_dim,
            },
        )
        run.artifact_path = artifact_path

        threshold_upserts = _persist_thresholds(
            db,
            thresholds=thresholds,
            model_version=model_version,
            prediction_type=prediction_type,
            window_key=dataset.window_key,
            window_end=dataset.window_end,
        )

        embeddings_upserted = _upsert_embeddings(
            db,
            dataset=dataset,
            model_version=model_version,
            embeddings=train_result.embeddings,
        )
        link_predictions_upserted = _upsert_link_predictions(
            db,
            dataset=dataset,
            embeddings=train_result.embeddings,
            model_version=model_version,
            prediction_type=prediction_type,
        )
        techniques_upserted = _upsert_attack_techniques(
            db,
            dataset=dataset,
            probabilities=train_result.probabilities,
            prediction_type=prediction_type,
        )
        lineage_id = _persist_model_lineage(
            db,
            run=run,
            dataset=dataset,
            params_json=dict(run.params_json or {}),
        )

        created = 0
        updated = 0
        indicators_by_entity: Dict[str, Dict[str, object]] = {}

        for i, entity_key in enumerate(dataset.entity_keys):
            prob = float(train_result.probabilities[i])
            score = round(prob * 100.0, 4)
            entity_type = str(dataset.entity_types[i])
            uncertainty = float((train_result.uncertainties or [])[i] if train_result.uncertainties else (1.0 - abs(prob - 0.5) * 2.0))
            confidence = max(0.0, min(1.0, 1.0 - uncertainty))

            threshold_score = float((thresholds.get(entity_type) or {}).get("threshold_score") or _default_threshold(entity_type))
            is_indicator = score >= threshold_score
            abstained = uncertainty >= max(0.0, float(uncertainty_abstain_threshold))

            meta = dataset.node_meta[i]
            reasons = _reason_codes(meta, prob, is_indicator=is_indicator)
            event_types = dict((meta or {}).get("event_types") or {})
            kill_chain_stage = event_types_to_kill_chain_stage(event_types)
            technique_hits = event_types_to_attack_techniques(event_types)
            controls = reason_codes_to_d3fend_controls(reasons)
            top_feature_hint = "event_count"
            if bool((meta or {}).get("risk_flags")):
                top_feature_hint = "risk_flags"
            counterfactual = build_counterfactual(
                probability=prob,
                threshold_score=threshold_score,
                top_feature_hint=top_feature_hint,
            )
            if abstained:
                reasons = sorted(set(reasons + ["UNCERTAIN_REQUIRES_ANALYST_REVIEW"]))

            details = {
                "probability": round(prob, 6),
                "predicted_label": int(train_result.predicted_labels[i]),
                "entity_threshold_score": round(threshold_score, 4),
                "risk_indicator": bool(is_indicator),
                "confidence": round(confidence, 6),
                "uncertainty": round(uncertainty, 6),
                "abstained": bool(abstained),
                "kill_chain_stage": kill_chain_stage,
                "attack_techniques": technique_hits,
                "severity": _severity_from_score(score),
                "model_version": model_version,
                "gnn_run_id": str(run.id),
                "lineage_id": lineage_id,
                "source_backend": dataset.source_backend_used,
                "feature_dim": len(dataset.feature_matrix[i]),
                "legal_notice": LEGAL_RISK_NOTICE,
            }

            pred = (
                db.query(AIPrediction)
                .filter(AIPrediction.entity_key == entity_key)
                .filter(AIPrediction.prediction_type == prediction_type)
                .filter(AIPrediction.window_key == dataset.window_key)
                .filter(AIPrediction.window_end == dataset.window_end)
                .first()
            )

            if pred:
                pred.score = score
                pred.model_version = model_version
                pred.confidence = confidence
                pred.uncertainty = uncertainty
                pred.abstained = bool(abstained)
                pred.kill_chain_stage = kill_chain_stage
                pred.decision_source = "gnn"
                pred.reason_codes = reasons
                pred.details_json = details
                updated += 1
            else:
                pred = AIPrediction(
                    entity_key=entity_key,
                    entity_type=entity_type,
                    prediction_type=prediction_type,
                    window_key=dataset.window_key,
                    window_end=dataset.window_end,
                    model_version=model_version,
                    score=score,
                    confidence=confidence,
                    uncertainty=uncertainty,
                    abstained=bool(abstained),
                    kill_chain_stage=kill_chain_stage,
                    decision_source="gnn",
                    reason_codes=reasons,
                    details_json=details,
                )
                db.add(pred)
                db.flush()
                created += 1

            indicators_by_entity[entity_key] = {
                "entity_type": entity_type,
                "score": score,
                "risk_indicator": bool(is_indicator),
            }

            evidence_hashes: List[str] = []
            if is_indicator:
                evidence_hashes = _event_hashes(
                    db,
                    entity_key=entity_key,
                    window_start=dataset.window_start,
                    window_end=dataset.window_end,
                    limit=20,
                )

            expl = db.query(AIExplanation).filter(AIExplanation.prediction_id == pred.id).first()
            expl_payload = {
                "window_start": dataset.window_start.isoformat(),
                "window_end": dataset.window_end.isoformat(),
                "gnn_run_id": str(run.id),
                "probability": round(prob, 6),
                "entity_threshold_score": round(threshold_score, 4),
                "risk_indicator": bool(is_indicator),
                "confidence": round(confidence, 6),
                "uncertainty": round(uncertainty, 6),
                "abstained": bool(abstained),
                "kill_chain_stage": kill_chain_stage,
                "recommended_controls": controls,
                "counterfactual": counterfactual,
                "legal_notice": LEGAL_RISK_NOTICE,
            }
            if expl:
                expl.reason_codes = reasons
                expl.evidence_hashes = evidence_hashes
                expl.evidence_paths = []
                expl.recommended_controls_json = controls
                expl.counterfactual_json = counterfactual
                expl.details_json = expl_payload
            else:
                db.add(
                    AIExplanation(
                        prediction_id=pred.id,
                        reason_codes=reasons,
                        evidence_hashes=evidence_hashes,
                        evidence_paths=[],
                        recommended_controls_json=controls,
                        counterfactual_json=counterfactual,
                        details_json=expl_payload,
                    )
                )

        component_stats = _materialize_component_campaigns(
            db,
            dataset=dataset,
            prediction_type=prediction_type,
            indicators_by_entity=indicators_by_entity,
            enabled=component_discovery_enabled,
            min_size=component_min_size,
            min_indicator_ratio=component_min_indicator_ratio,
        )

        campaign_indicator_stats = _upsert_campaign_indicators(
            db,
            model_version=model_version,
            prediction_type=prediction_type,
            window_key=dataset.window_key,
            window_end=dataset.window_end,
            thresholds=thresholds,
        )

        db.commit()
    except Exception as exc:
        db.rollback()
        return {"status": "error", "stage": "persist", "detail": str(exc)}

    return {
        "status": "ok",
        "gnn_run_id": str(run.id),
        "window_key": dataset.window_key,
        "window_end": dataset.window_end.isoformat(),
        "nodes": len(dataset.entity_keys),
        "edges": len(dataset.edges),
        "source_backend": dataset.source_backend_used,
        "edge_source_counts": dataset.edge_source_counts,
        "positive_count": dataset.positive_count,
        "negative_count": dataset.negative_count,
        "benign_negative_count": dataset.benign_negative_count,
        "thresholds_upserted": threshold_upserts,
        "embeddings_upserted": embeddings_upserted,
        "link_predictions_upserted": link_predictions_upserted,
        "techniques_upserted": techniques_upserted,
        "lineage_id": lineage_id,
        "predictions_created": created,
        "predictions_updated": updated,
        "component_campaigns_created": component_stats["campaigns_created"],
        "component_campaigns_updated": component_stats["campaigns_updated"],
        "component_entities_upserted": component_stats["entities_upserted"],
        "components_considered": component_stats["components_considered"],
        "campaign_indicators_created": campaign_indicator_stats["created"],
        "campaign_indicators_updated": campaign_indicator_stats["updated"],
        "metrics": train_result.metrics,
        "artifact_path": artifact_path,
        "legal_notice": LEGAL_RISK_NOTICE,
    }


def main() -> None:
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--window-key", default=settings.gnn_window_key)
    p.add_argument("--window-end", default=None, help="ISO timestamp override")
    p.add_argument("--edge-backend", default=settings.gnn_edge_backend, choices=["postgres", "neo4j", "hybrid"])
    p.add_argument("--max-entities", type=int, default=settings.gnn_max_entities)
    p.add_argument("--max-edges", type=int, default=settings.gnn_max_edges)
    p.add_argument("--min-edge-weight", type=int, default=settings.gnn_min_edge_weight)
    p.add_argument("--negative-multiplier", type=float, default=settings.gnn_negative_multiplier)
    p.add_argument("--threshold-min-samples", type=int, default=settings.gnn_threshold_min_samples)
    p.add_argument("--component-discovery-enabled", type=int, default=1 if settings.gnn_component_discovery_enabled else 0)
    p.add_argument("--component-min-size", type=int, default=settings.gnn_component_min_size)
    p.add_argument("--component-min-indicator-ratio", type=float, default=settings.gnn_component_min_indicator_ratio)
    p.add_argument("--epochs", type=int, default=settings.gnn_epochs)
    p.add_argument("--hidden-dim", type=int, default=settings.gnn_hidden_dim)
    p.add_argument("--embed-dim", type=int, default=settings.gnn_embed_dim)
    p.add_argument("--dropout", type=float, default=settings.gnn_dropout)
    p.add_argument("--learning-rate", type=float, default=settings.gnn_learning_rate)
    p.add_argument("--weight-decay", type=float, default=settings.gnn_weight_decay)
    p.add_argument("--temporal-decay", type=float, default=settings.ai_temporal_edge_decay)
    p.add_argument("--pretrain-epochs", type=int, default=5)
    p.add_argument("--seed", type=int, default=settings.gnn_seed)
    p.add_argument("--uncertainty-abstain-threshold", type=float, default=settings.ai_uncertainty_abstain_threshold)
    p.add_argument("--model-version", default=settings.gnn_model_version)
    p.add_argument("--prediction-type", default=settings.gnn_prediction_type)
    p.add_argument("--artifact-dir", default=settings.gnn_artifact_dir)
    args = p.parse_args()

    if not settings.gnn_enabled:
        print(json.dumps({"status": "disabled", "detail": "GNN_ENABLED=false"}))
        return

    window_end = None
    if args.window_end:
        window_end = datetime.fromisoformat(args.window_end.replace("Z", "+00:00"))

    db = SessionLocal()
    try:
        out = run_once(
            db=db,
            window_key=args.window_key,
            window_end=window_end,
            edge_backend=args.edge_backend,
            max_entities=args.max_entities,
            max_edges=args.max_edges,
            min_edge_weight=args.min_edge_weight,
            negative_multiplier=args.negative_multiplier,
            threshold_min_samples=args.threshold_min_samples,
            component_discovery_enabled=bool(args.component_discovery_enabled),
            component_min_size=args.component_min_size,
            component_min_indicator_ratio=args.component_min_indicator_ratio,
            epochs=args.epochs,
            hidden_dim=args.hidden_dim,
            embed_dim=args.embed_dim,
            dropout=args.dropout,
            learning_rate=args.learning_rate,
            weight_decay=args.weight_decay,
            temporal_decay=args.temporal_decay,
            pretrain_epochs=args.pretrain_epochs,
            seed=args.seed,
            uncertainty_abstain_threshold=args.uncertainty_abstain_threshold,
            model_version=args.model_version,
            prediction_type=args.prediction_type,
            artifact_dir=args.artifact_dir,
        )
        print(json.dumps(out))
    finally:
        db.close()


if __name__ == "__main__":
    main()

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean, median
from typing import Any, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_db, pagination_params, require_central_access
from app.core.config import settings
from app.core.rate_limit import limiter
from app.analytics.ai_models import (
    AIExplanation,
    AIAttackPathScore,
    AIAttackTechniqueHit,
    AICampaignRiskIndicator,
    AIDecisionFusion,
    AIDriftReport,
    AIFeedbackLabel,
    AIInputAnomalyAlert,
    AILinkPrediction,
    AIModelRollout,
    AIPrediction,
    AIRiskThreshold,
    EntityRiskBaseline,
    GNNTrainingRun,
    ThreatIntelIndicator,
)
from app.analytics.layer3.forecasting import (
    build_risk_forecast,
    build_signal_forecast,
    summarize_forecast_card,
)
from app.analytics.layer3.local_analyst_query import answer_local_analyst_query
from app.analytics.layer3.threat_intel_worker import export_stix_bundle, import_stix_bundle
from app.analytics.layer3.trust_service import build_entity_trust_summary, build_platform_trust_summary

log = logging.getLogger("sentinel.api.ai")
router = APIRouter(prefix="/v1/ai", tags=["ai"])

SCENARIO_ALIASES: dict[str, str] = {
    "sim_swap": "fraud",
}

SCENARIO_LABELS: dict[str, str] = {
    "ddos": "Kenyan DDoS pressure",
    "vpn": "VPN-style login reuse",
    "fraud": "SIM-swap / mobile-money fraud",
    "ddos_vpn": "DDoS + VPN blended pressure",
    "ddos_vpn_fraud": "Combined DDoS + VPN + SIM-swap pressure",
    "all": "Combined DDoS + VPN + SIM-swap pressure",
}

DOMAIN_PREDICTION_TYPES: tuple[str, ...] = ("risk_gnn", "corruption_risk")
DOMAIN_LABELS: dict[str, str] = {
    "risk_gnn": "Cyber GNN",
    "corruption_risk": "Corruption GNN",
}

BENCHMARK_ARTIFACT_CANDIDATES: dict[str, tuple[Path, ...]] = {
    "paysim_fraud": (
        Path(settings.gnn_artifact_dir).resolve().parent / "paysim_auc.json",
        Path("/app/artifacts/paysim_auc.json"),
    ),
}


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _fairness_blocked(metrics_json: dict[str, Any] | None) -> bool:
    metrics = metrics_json or {}
    fairness = metrics.get("fairness") or {}
    fairness_gate = metrics.get("fairness_gate") or {}
    if "passed" in fairness_gate:
        return (
            not bool(fairness_gate.get("passed"))
            and not bool(fairness_gate.get("override_applied", False))
        )
    gate_metric = str(fairness.get("gate_metric") or "").strip().lower()
    disparity = (
        fairness.get("max_positive_rate_gap")
        if gate_metric == "max_positive_rate_gap"
        else fairness.get("max_positive_rate_disparity")
    )
    try:
        disparity_value = float(disparity) if disparity is not None else 0.0
    except (TypeError, ValueError):
        disparity_value = 0.0
    return (
        disparity_value > settings.fairness_disparity_threshold
        and not bool(fairness_gate.get("override_applied", False))
    )


def _normalize_scenario_name(value: str) -> str:
    raw = str(value or "").strip().lower()
    return SCENARIO_ALIASES.get(raw, raw)


def _scenario_sql_condition(scenario: str) -> str:
    conditions = {
        "ddos": """
            event_type = 'DDOS_SIGNAL_EVENT'
        """,
        "vpn": """
            event_type = 'LOGIN_EVENT'
            AND COALESCE(payload_json->>'provider', '') = 'demo-vpn'
        """,
        "fraud": """
            event_type = 'SIM_SWAP_EVENT'
            OR (
                event_type = 'LOGIN_EVENT'
                AND COALESCE(anchors_json->>'endpoint', '') = 'bank:/login:POST'
            )
            OR (
                event_type = 'TRANSACTION_EVENT'
                AND (
                    COALESCE(payload_json->>'channel', '') IN ('MOBILE', 'AGENT_CASHOUT')
                    OR COALESCE(payload_json->>'agent_id', '') = 'agent-47'
                )
            )
        """,
        "ddos_vpn": """
            event_type = 'DDOS_SIGNAL_EVENT'
            OR (
                event_type = 'LOGIN_EVENT'
                AND COALESCE(payload_json->>'provider', '') = 'demo-vpn'
            )
        """,
        "ddos_vpn_fraud": """
            event_type = 'DDOS_SIGNAL_EVENT'
            OR (
                event_type = 'LOGIN_EVENT'
                AND (
                    COALESCE(payload_json->>'provider', '') = 'demo-vpn'
                    OR COALESCE(anchors_json->>'endpoint', '') = 'bank:/login:POST'
                )
            )
            OR event_type = 'SIM_SWAP_EVENT'
            OR (
                event_type = 'TRANSACTION_EVENT'
                AND (
                    COALESCE(payload_json->>'channel', '') IN ('MOBILE', 'AGENT_CASHOUT')
                    OR COALESCE(payload_json->>'agent_id', '') = 'agent-47'
                )
            )
        """,
        "all": """
            event_type = 'DDOS_SIGNAL_EVENT'
            OR (
                event_type = 'LOGIN_EVENT'
                AND (
                    COALESCE(payload_json->>'provider', '') = 'demo-vpn'
                    OR COALESCE(anchors_json->>'endpoint', '') = 'bank:/login:POST'
                )
            )
            OR event_type = 'SIM_SWAP_EVENT'
            OR (
                event_type = 'TRANSACTION_EVENT'
                AND (
                    COALESCE(payload_json->>'channel', '') IN ('MOBILE', 'AGENT_CASHOUT')
                    OR COALESCE(payload_json->>'agent_id', '') = 'agent-47'
                )
            )
        """,
    }
    if scenario not in conditions:
        raise HTTPException(
            status_code=400,
            detail="invalid_scenario: use ddos, vpn, sim_swap, fraud, ddos_vpn, ddos_vpn_fraud, or all",
        )
    return conditions[scenario]


def _scenario_component_scores(metrics: dict[str, float]) -> tuple[float, float, float]:
    ddos_score = min(
        100.0,
        metrics["ddos_count"] * 1.6
        + metrics["distinct_ips"] * 1.4
        + min(26.0, metrics["avg_req_rate"] * 0.08)
        + min(18.0, metrics["avg_latency_ms"] * 0.09)
        + min(16.0, metrics["avg_error_rate"] * 280.0),
    )
    vpn_score = min(
        100.0,
        metrics["login_count"] * 2.6
        + metrics["distinct_ips"] * 6.0
        + metrics["distinct_devices"] * 5.0,
    )
    fraud_score = min(
        100.0,
        metrics["sim_swap_count"] * 18.0
        + metrics["transaction_count"] * 8.5
        + metrics["login_count"] * 4.5
        + metrics["distinct_accounts"] * 7.0
        + metrics["distinct_devices"] * 4.0,
    )
    return ddos_score, vpn_score, fraud_score


def _scenario_signal_score(scenario: str, metrics: dict[str, float]) -> float:
    ddos_score, vpn_score, fraud_score = _scenario_component_scores(metrics)
    if scenario == "ddos":
        return ddos_score
    if scenario == "vpn":
        return vpn_score
    if scenario == "fraud":
        return fraud_score
    if scenario == "ddos_vpn":
        return min(100.0, ddos_score * 0.58 + vpn_score * 0.42)
    return min(100.0, ddos_score * 0.36 + vpn_score * 0.24 + fraud_score * 0.40)


def _scenario_recommended_posture(level: str, label: str) -> str:
    if level == "CRITICAL":
        return f"{label} is forecast to remain critical over the next 24 hours. Prepare containment, surge analyst coverage, and pre-brief leadership."
    if level == "HIGH":
        return f"{label} is likely to stay elevated over the next 24 hours. Keep the service or fraud queue under active watch and pre-position response actions."
    if level == "ELEVATED":
        return f"{label} remains watch-worthy over the next 24 hours. Continue monitoring and validate whether the scenario is expanding beyond the current entity set."
    return f"{label} is forecast to remain low over the next 24 hours. Monitor only unless other trust signals or campaign indicators rise."


def _scenario_forecast_history(
    db: Session,
    scenario: str,
    lookback_hours: int,
) -> tuple[list[dict[str, object]], dict[str, int]]:
    from sqlalchemy import text as _text

    sql = _text(
        f"""
        SELECT
            date_trunc('hour', occurred_at AT TIME ZONE 'UTC') AS bucket,
            COUNT(*) AS event_count,
            SUM(CASE WHEN event_type = 'DDOS_SIGNAL_EVENT' THEN 1 ELSE 0 END) AS ddos_count,
            SUM(CASE WHEN event_type = 'LOGIN_EVENT' THEN 1 ELSE 0 END) AS login_count,
            SUM(CASE WHEN event_type = 'SIM_SWAP_EVENT' THEN 1 ELSE 0 END) AS sim_swap_count,
            SUM(CASE WHEN event_type = 'TRANSACTION_EVENT' THEN 1 ELSE 0 END) AS transaction_count,
            COUNT(DISTINCT NULLIF(anchors_json->>'ip', '')) AS distinct_ips,
            COUNT(DISTINCT NULLIF(anchors_json->>'device_id', '')) AS distinct_devices,
            COUNT(DISTINCT NULLIF(anchors_json->>'account_h', '')) AS distinct_accounts,
            AVG(CASE WHEN event_type = 'DDOS_SIGNAL_EVENT' THEN NULLIF(payload_json->>'req_rate', '')::double precision END) AS avg_req_rate,
            AVG(CASE WHEN event_type = 'DDOS_SIGNAL_EVENT' THEN NULLIF(payload_json->>'avg_latency_ms', '')::double precision END) AS avg_latency_ms,
            AVG(CASE WHEN event_type = 'DDOS_SIGNAL_EVENT' THEN NULLIF(payload_json->>'error_rate', '')::double precision END) AS avg_error_rate
        FROM event_log
        WHERE occurred_at >= NOW() - INTERVAL '1 hour' * :lookback_hours
          AND ({_scenario_sql_condition(scenario)})
        GROUP BY 1
        ORDER BY 1
        """
    )
    rows = db.execute(sql, {"lookback_hours": lookback_hours}).mappings().all()
    by_bucket: dict[datetime, dict[str, object]] = {}
    for row in rows:
        bucket = row.get("bucket")
        if isinstance(bucket, datetime):
            if bucket.tzinfo is None:
                bucket = bucket.replace(tzinfo=timezone.utc)
            else:
                bucket = bucket.astimezone(timezone.utc)
        else:
            bucket = datetime.now(timezone.utc)
        by_bucket[bucket] = dict(row)

    end_hour = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    start_hour = end_hour - timedelta(hours=max(0, lookback_hours - 1))
    history: list[dict[str, object]] = []
    matching_events = 0
    hours_with_activity = 0
    for idx in range(lookback_hours):
        bucket = start_hour + timedelta(hours=idx)
        row = dict(by_bucket.get(bucket) or {})
        metrics = {
            "event_count": float(row.get("event_count") or 0.0),
            "ddos_count": float(row.get("ddos_count") or 0.0),
            "login_count": float(row.get("login_count") or 0.0),
            "sim_swap_count": float(row.get("sim_swap_count") or 0.0),
            "transaction_count": float(row.get("transaction_count") or 0.0),
            "distinct_ips": float(row.get("distinct_ips") or 0.0),
            "distinct_devices": float(row.get("distinct_devices") or 0.0),
            "distinct_accounts": float(row.get("distinct_accounts") or 0.0),
            "avg_req_rate": float(row.get("avg_req_rate") or 0.0),
            "avg_latency_ms": float(row.get("avg_latency_ms") or 0.0),
            "avg_error_rate": float(row.get("avg_error_rate") or 0.0),
        }
        event_count = int(metrics["event_count"])
        matching_events += event_count
        if event_count > 0:
            hours_with_activity += 1
        history.append(
            {
                "timestamp": bucket.isoformat(),
                "score": round(_scenario_signal_score(scenario, metrics), 2),
                "event_count": event_count,
                "ddos_count": int(metrics["ddos_count"]),
                "login_count": int(metrics["login_count"]),
                "sim_swap_count": int(metrics["sim_swap_count"]),
                "transaction_count": int(metrics["transaction_count"]),
                "distinct_ips": int(metrics["distinct_ips"]),
                "distinct_devices": int(metrics["distinct_devices"]),
                "distinct_accounts": int(metrics["distinct_accounts"]),
            }
        )
    return history, {
        "matching_events": matching_events,
        "hours_with_activity": hours_with_activity,
    }


def _severity_from_score(score: float) -> str:
    s = float(score)
    if s >= 90:
        return "critical"
    if s >= 75:
        return "high"
    if s >= 55:
        return "medium"
    return "low"


def _top_feature(details: dict) -> str | None:
    attributions = details.get("feature_attributions", [])
    if not isinstance(attributions, list) or not attributions:
        return None
    first = attributions[0] if isinstance(attributions[0], dict) else {}
    name = str(first.get("feature") or "").strip()
    return name or None


def _serialize_gnn_run(row: GNNTrainingRun | None) -> dict[str, Any] | None:
    if row is None:
        return None
    metrics_json = dict(row.metrics_json or {})
    real_data_gate = dict(metrics_json.get("real_data_gate") or {})
    return {
        "id": str(row.id),
        "model_version": row.model_version,
        "prediction_type": row.prediction_type,
        "source_backend": row.source_backend,
        "window_key": row.window_key,
        "window_end": row.window_end.isoformat(),
        "node_count": row.node_count,
        "edge_count": row.edge_count,
        "feature_dim": row.feature_dim,
        "positive_count": row.positive_count,
        "epochs": row.epochs,
        "train_loss": row.train_loss,
        "val_loss": row.val_loss,
        "auc": row.auc,
        "precision": row.precision,
        "recall": row.recall,
        "f1": row.f1,
        "artifact_path": row.artifact_path,
        "params": row.params_json,
        "metrics": metrics_json,
        "operating_metrics": dict(metrics_json.get("operating_metrics") or {}),
        "fairness": dict(metrics_json.get("fairness") or {}),
        "fairness_gate": dict(metrics_json.get("fairness_gate") or {}),
        "fairness_blocked": _fairness_blocked(metrics_json),
        "provenance": dict(metrics_json.get("provenance") or {}),
        "real_data_gate": real_data_gate,
        "real_data_gate_passed": bool(real_data_gate.get("passed", False)),
        "created_at": row.created_at.isoformat(),
    }


def _recent_distinct_window_runs(
    db: Session,
    *,
    prediction_type: str,
    limit: int,
    scan_limit: int | None = None,
) -> list[GNNTrainingRun]:
    scan_count = max(limit * 4, scan_limit or (limit * 4))
    rows = (
        db.query(GNNTrainingRun)
        .filter(GNNTrainingRun.prediction_type == prediction_type)
        .order_by(GNNTrainingRun.created_at.desc())
        .limit(scan_count)
        .all()
    )
    seen: set[tuple[str, datetime]] = set()
    distinct: list[GNNTrainingRun] = []
    for row in rows:
        key = (str(row.window_key), row.window_end)
        if key in seen:
            continue
        seen.add(key)
        distinct.append(row)
        if len(distinct) >= limit:
            break
    return distinct


def _build_scientific_evidence(
    db: Session,
    *,
    prediction_type: str,
    limit: int = 5,
) -> dict[str, Any]:
    rows = _recent_distinct_window_runs(db, prediction_type=prediction_type, limit=max(1, limit))
    if not rows:
        return {
            "prediction_type": prediction_type,
            "domain_label": DOMAIN_LABELS.get(prediction_type, prediction_type),
            "status": "missing",
            "headline": "No multi-window scientific evidence is recorded yet.",
            "window_count": 0,
            "eligible_window_count": 0,
            "benchmarkable_window_count": 0,
            "dual_class_holdout_count": 0,
            "class_thin_holdout_count": 0,
            "aggregates": {},
            "windows": [],
        }

    windows: list[dict[str, Any]] = []
    aucs: list[float] = []
    pr_aucs: list[float] = []
    op_f1s: list[float] = []
    op_precisions: list[float] = []
    op_recalls: list[float] = []
    scientific_scores: list[float] = []
    eligible_count = 0
    benchmarkable_count = 0
    dual_class_count = 0
    class_thin_count = 0
    seen_signatures: set[tuple[Any, ...]] = set()

    for row in rows:
        payload = _serialize_gnn_run(row) or {}
        metrics = dict(payload.get("metrics") or {})
        operating = dict(payload.get("operating_metrics") or {})
        evaluation_protocol = dict(metrics.get("evaluation_protocol") or {})
        dataset_selection = dict(metrics.get("dataset_selection") or {})
        holdout_summary = dict(metrics.get("evaluation_summary", {}).get("holdout") or {})

        holdout_positive_count = _safe_int(metrics.get("holdout_manifest_positive_count"))
        holdout_negative_count = _safe_int(metrics.get("holdout_manifest_negative_count"))
        dual_class_holdout = bool(
            (holdout_positive_count or 0) > 0 and (holdout_negative_count or 0) > 0
        )
        class_thin_holdout = bool(
            (holdout_positive_count or 0) < 3 or (holdout_negative_count or 0) < 3
        )
        benchmarkable = bool(evaluation_protocol.get("benchmarkable"))
        fairness_blocked = bool(payload.get("fairness_blocked"))
        real_data_gate_passed = bool(payload.get("real_data_gate_passed"))
        eligible = benchmarkable and not fairness_blocked and real_data_gate_passed

        auc = _safe_float(payload.get("auc"))
        pr_auc = _safe_float(holdout_summary.get("pr_auc") or metrics.get("pr_auc"))
        operating_f1 = _safe_float(operating.get("f1") or payload.get("f1"))
        operating_precision = _safe_float(operating.get("precision") or payload.get("precision"))
        operating_recall = _safe_float(operating.get("recall") or payload.get("recall"))
        scientific_score = _safe_float(dataset_selection.get("selected_scientific_score")) or 0.0
        eval_samples = _safe_int(holdout_summary.get("sample_count") or operating.get("sample_count") or metrics.get("eval_samples"))
        signature = (
            _safe_int(payload.get("node_count")) or 0,
            _safe_int(payload.get("edge_count")) or 0,
            _safe_int(payload.get("positive_count")) or 0,
            holdout_positive_count or 0,
            holdout_negative_count or 0,
            round(scientific_score, 3),
        )
        if signature in seen_signatures:
            continue
        seen_signatures.add(signature)

        benchmarkable_count += int(benchmarkable)
        dual_class_count += int(dual_class_holdout)
        class_thin_count += int(class_thin_holdout)
        eligible_count += int(eligible)

        if dual_class_holdout and auc is not None:
            aucs.append(auc)
        if dual_class_holdout and pr_auc is not None:
            pr_aucs.append(pr_auc)
        if operating_f1 is not None:
            op_f1s.append(operating_f1)
        if operating_precision is not None:
            op_precisions.append(operating_precision)
        if operating_recall is not None:
            op_recalls.append(operating_recall)
        scientific_scores.append(scientific_score)

        windows.append(
            {
                "run_id": payload.get("id"),
                "model_version": payload.get("model_version"),
                "window_key": payload.get("window_key"),
                "window_end": payload.get("window_end"),
                "created_at": payload.get("created_at"),
                "node_count": payload.get("node_count"),
                "edge_count": payload.get("edge_count"),
                "positive_count": payload.get("positive_count"),
                "benchmarkable": benchmarkable,
                "eligible": eligible,
                "fairness_blocked": fairness_blocked,
                "real_data_gate_passed": real_data_gate_passed,
                "dual_class_holdout": dual_class_holdout,
                "class_thin_holdout": class_thin_holdout,
                "holdout_positive_count": holdout_positive_count,
                "holdout_negative_count": holdout_negative_count,
                "eval_samples": eval_samples,
                "auc": auc,
                "pr_auc": pr_auc,
                "operating_f1": operating_f1,
                "operating_precision": operating_precision,
                "operating_recall": operating_recall,
                "scientific_score": round(scientific_score, 3),
            }
        )

    mean_auc = mean(aucs) if aucs else None
    mean_pr_auc = mean(pr_aucs) if pr_aucs else None
    mean_f1 = mean(op_f1s) if op_f1s else None
    mean_precision = mean(op_precisions) if op_precisions else None
    mean_recall = mean(op_recalls) if op_recalls else None

    status = "limited"
    headline = "Recent windows show usable operational evidence, but scientific support is still limited."
    if eligible_count >= 3 and dual_class_count >= 3 and mean_auc is not None and mean_auc >= 0.75:
        status = "strong"
        headline = "Recent benchmarkable windows show consistent scientific support."
    elif eligible_count >= 2 and dual_class_count >= 2 and mean_f1 is not None and mean_f1 >= 0.8:
        status = "moderate"
        headline = "Recent benchmarkable windows show repeatable scientific evidence with some caveats."
    elif dual_class_count == 0 or class_thin_count == len(windows):
        status = "weak"
        headline = "Recent windows remain class-thin, so scientific claims should stay conservative."

    return {
        "prediction_type": prediction_type,
        "domain_label": DOMAIN_LABELS.get(prediction_type, prediction_type),
        "status": status,
        "headline": headline,
        "window_count": len(windows),
        "eligible_window_count": eligible_count,
        "benchmarkable_window_count": benchmarkable_count,
        "dual_class_holdout_count": dual_class_count,
        "class_thin_holdout_count": class_thin_count,
        "aggregates": {
            "mean_auc": round(mean_auc, 6) if mean_auc is not None else None,
            "median_auc": round(median(aucs), 6) if aucs else None,
            "mean_pr_auc": round(mean_pr_auc, 6) if mean_pr_auc is not None else None,
            "mean_operating_f1": round(mean_f1, 6) if mean_f1 is not None else None,
            "mean_operating_precision": round(mean_precision, 6) if mean_precision is not None else None,
            "mean_operating_recall": round(mean_recall, 6) if mean_recall is not None else None,
            "mean_scientific_score": round(mean(scientific_scores), 6) if scientific_scores else None,
        },
        "windows": windows,
    }


def _prediction_window_summary(
    db: Session,
    *,
    prediction_type: str,
    window_key: str | None,
    window_end: datetime | None,
) -> dict[str, Any] | None:
    if not window_key or window_end is None:
        return None
    rows = (
        db.query(AIPrediction)
        .filter(AIPrediction.prediction_type == prediction_type)
        .filter(AIPrediction.window_key == window_key)
        .filter(AIPrediction.window_end == window_end)
        .order_by(AIPrediction.score.desc())
        .all()
    )
    if not rows:
        return None
    deduped_rows: list[AIPrediction] = []
    seen_entities: set[str] = set()
    for row in rows:
        entity_key = str(row.entity_key)
        if entity_key in seen_entities:
            continue
        seen_entities.add(entity_key)
        deduped_rows.append(row)
    rows = deduped_rows

    def _is_above_threshold(row: AIPrediction) -> bool:
        details = dict(row.details_json or {})
        if "above_entity_threshold" in details:
            return bool(details.get("above_entity_threshold"))
        try:
            threshold_score = float(details.get("entity_threshold_score") or 75.0)
        except (TypeError, ValueError):
            threshold_score = 75.0
        return float(row.score or 0.0) >= threshold_score

    scored_rows = [row for row in rows if not bool(row.abstained)]
    latest_created_at = max(
        (row.created_at for row in rows if isinstance(row.created_at, datetime)),
        default=None,
    )
    avg_score = (
        round(sum(float(row.score or 0.0) for row in scored_rows) / len(scored_rows), 4)
        if scored_rows else 0.0
    )
    return {
        "prediction_type": prediction_type,
        "window_key": window_key,
        "window_end": window_end.isoformat(),
        "model_version": rows[0].model_version,
        "prediction_count": len(rows),
        "flagged_count": len(scored_rows),
        "high_risk_count": sum(1 for row in scored_rows if _is_above_threshold(row)),
        "abstained_count": sum(1 for row in rows if bool(row.abstained)),
        "avg_score": avg_score,
        "max_score": round(max(float(row.score or 0.0) for row in rows), 4),
        "latest_created_at": latest_created_at.isoformat() if latest_created_at else None,
    }


def _latest_prediction_window_summary(db: Session, prediction_type: str) -> dict[str, Any] | None:
    latest_prediction = (
        db.query(AIPrediction)
        .filter(AIPrediction.prediction_type == prediction_type)
        .order_by(AIPrediction.window_end.desc(), AIPrediction.created_at.desc())
        .first()
    )
    if latest_prediction is None:
        return None
    return _prediction_window_summary(
        db,
        prediction_type=prediction_type,
        window_key=latest_prediction.window_key,
        window_end=latest_prediction.window_end,
    )


def _build_domain_summary(db: Session, prediction_type: str) -> dict[str, Any]:
    latest_run = (
        db.query(GNNTrainingRun)
        .filter(GNNTrainingRun.prediction_type == prediction_type)
        .order_by(GNNTrainingRun.created_at.desc())
        .first()
    )
    latest_run_payload = _serialize_gnn_run(latest_run)
    latest_available_live_predictions = _latest_prediction_window_summary(db, prediction_type)
    matched_live_predictions = _prediction_window_summary(
        db,
        prediction_type=prediction_type,
        window_key=str(latest_run_payload.get("window_key") or "") or None,
        window_end=latest_run.window_end if latest_run is not None else None,
    )
    live_predictions = matched_live_predictions or latest_available_live_predictions
    windows_match = bool(
        latest_run_payload
        and live_predictions
        and latest_run_payload.get("window_end") == live_predictions.get("window_end")
        and latest_run_payload.get("window_key") == live_predictions.get("window_key")
    )
    model_versions_match = bool(
        latest_run_payload
        and live_predictions
        and latest_run_payload.get("model_version") == live_predictions.get("model_version")
    )
    available = bool(latest_run_payload or live_predictions)
    status = "ok"
    reasons: list[str] = []
    if not available:
        status = "missing"
        reasons.append("no_training_or_predictions")
    else:
        if latest_run_payload is None:
            status = "warn"
            reasons.append("no_training_run")
        if live_predictions is None:
            status = "warn"
            reasons.append("no_live_predictions")
        if latest_run_payload and latest_run_payload.get("fairness_blocked"):
            status = "warn"
            reasons.append("fairness_blocked")
        if latest_run_payload and not latest_run_payload.get("real_data_gate_passed", False):
            status = "warn"
            reasons.append("real_data_gate_failed")
        if latest_run_payload and live_predictions and not windows_match:
            status = "warn"
            reasons.append("run_window_differs_from_live_window")
    return {
        "prediction_type": prediction_type,
        "domain_label": DOMAIN_LABELS.get(prediction_type, prediction_type),
        "available": available,
        "status": status,
        "status_reasons": reasons,
        "latest_run": latest_run_payload,
        "latest_live_predictions": live_predictions,
        "run_prediction_alignment": {
            "window_matches": windows_match,
            "model_version_matches": model_versions_match,
            "matched_run_window_predictions": bool(matched_live_predictions),
            "latest_available_window_key": latest_available_live_predictions.get("window_key") if latest_available_live_predictions else None,
            "latest_available_window_end": latest_available_live_predictions.get("window_end") if latest_available_live_predictions else None,
            "newer_prediction_window_available": bool(
                latest_available_live_predictions
                and live_predictions
                and (
                    latest_available_live_predictions.get("window_key") != live_predictions.get("window_key")
                    or latest_available_live_predictions.get("window_end") != live_predictions.get("window_end")
                )
            ),
        },
    }


def _latest_drift_summary(
    db: Session,
    *,
    prediction_type: str,
    model_version: str | None,
) -> dict[str, Any] | None:
    q = db.query(AIDriftReport).filter(AIDriftReport.prediction_type == prediction_type)
    if model_version:
        q = q.filter(AIDriftReport.model_version == model_version)
    row = q.order_by(AIDriftReport.window_end.desc(), AIDriftReport.created_at.desc()).first()
    if row is None:
        return None
    return {
        "model_version": row.model_version,
        "window_key": row.window_key,
        "window_end": row.window_end.isoformat(),
        "status": row.status,
        "drift_score": float(row.drift_score or 0.0),
        "created_at": row.created_at.isoformat(),
    }


def _latest_rollout_summary(db: Session, *, prediction_type: str) -> dict[str, Any] | None:
    row = (
        db.query(AIModelRollout)
        .filter(AIModelRollout.prediction_type == prediction_type)
        .order_by(AIModelRollout.updated_at.desc(), AIModelRollout.created_at.desc())
        .first()
    )
    if row is None:
        return None
    return {
        "rollout_id": row.rollout_id,
        "active_model_version": row.active_model_version,
        "shadow_model_version": row.shadow_model_version,
        "rollout_mode": row.rollout_mode,
        "status": row.status,
        "canary_ratio": float(row.canary_ratio or 0.0),
        "updated_at": row.updated_at.isoformat(),
    }


def _threshold_pointer_summary(
    db: Session,
    *,
    prediction_type: str,
    model_version: str | None,
    window_key: str | None = None,
    window_end: str | None = None,
) -> dict[str, Any]:
    q = db.query(AIRiskThreshold).filter(AIRiskThreshold.prediction_type == prediction_type)
    if model_version:
        q = q.filter(AIRiskThreshold.model_version == model_version)
    rows = q.order_by(AIRiskThreshold.window_end.desc(), AIRiskThreshold.entity_type.asc()).all()
    path = f"/v1/ai/thresholds?prediction_type={prediction_type}"
    if model_version:
        path = f"{path}&model_version={model_version}"
    if not rows:
        return {
            "path": path,
            "available": False,
            "window_key": None,
            "window_end": None,
            "entity_type_count": 0,
            "items": [],
        }

    latest = rows[0]
    target_rows = latest
    if window_key and window_end:
        matching_rows = [
            row
            for row in rows
            if row.window_key == window_key and row.window_end.isoformat() == window_end
        ]
        if matching_rows:
            target_rows = matching_rows[0]
    latest_rows = [
        row
        for row in rows
        if row.window_key == target_rows.window_key
        and row.window_end == target_rows.window_end
        and row.model_version == target_rows.model_version
    ]
    return {
        "path": path,
        "available": True,
        "window_key": target_rows.window_key,
        "window_end": target_rows.window_end.isoformat(),
        "entity_type_count": len(latest_rows),
        "items": [
            {
                "entity_type": row.entity_type,
                "threshold_score": float(row.threshold_score or 0.0),
                "method": row.method,
                "sample_count": int(row.sample_count or 0),
                "positive_count": int(row.positive_count or 0),
            }
            for row in latest_rows[:5]
        ],
    }


def _baseline_pointer_summary(db: Session, *, window_key: str | None) -> dict[str, Any]:
    path = "/v1/ai/baselines"
    if not window_key:
        return {
            "path": path,
            "available": False,
            "window_key": None,
            "coverage_count": 0,
            "latest_updated_at": None,
        }
    path = f"{path}?window_key={window_key}"
    rows = (
        db.query(EntityRiskBaseline)
        .filter(EntityRiskBaseline.window_key == window_key)
        .order_by(EntityRiskBaseline.updated_at.desc())
        .all()
    )
    latest = rows[0] if rows else None
    return {
        "path": path,
        "available": bool(rows),
        "window_key": window_key,
        "coverage_count": len(rows),
        "latest_updated_at": latest.updated_at.isoformat() if latest else None,
    }


def _judge_lane_caveats(
    *,
    latest_run: dict[str, Any] | None,
    live_predictions: dict[str, Any] | None,
    alignment: dict[str, Any],
    thresholds: dict[str, Any],
    baselines: dict[str, Any],
    drift: dict[str, Any] | None,
    scientific_evidence: dict[str, Any] | None = None,
) -> list[str]:
    caveats: list[str] = []
    if latest_run is None:
        caveats.append("No training run is recorded for this lane yet.")
    if live_predictions is None:
        caveats.append("No live predictions are recorded for this lane yet.")
    if latest_run and live_predictions and not bool(alignment.get("window_matches")):
        caveats.append(
            "Live predictions and the latest recorded run are from different windows."
        )
    if latest_run and live_predictions and not bool(alignment.get("model_version_matches")):
        caveats.append(
            "Live predictions are not aligned to the latest recorded model version."
        )
    if bool(alignment.get("newer_prediction_window_available")):
        caveats.append(
            "A newer live prediction window exists, but this readiness view is anchored to the latest benchmarked run window for like-for-like comparison."
        )
    if latest_run and latest_run.get("fairness_blocked"):
        caveats.append("The latest run is currently blocked by the fairness guard.")
    if latest_run and not latest_run.get("real_data_gate_passed", False):
        caveats.append("The latest run did not pass the real-data gate.")
    evaluation_protocol = dict((latest_run or {}).get("metrics", {}).get("evaluation_protocol") or {})
    if evaluation_protocol and not bool(evaluation_protocol.get("benchmarkable", False)):
        reasons = list(evaluation_protocol.get("benchmark_reasons") or [])
        if reasons:
            caveats.append(
                "Benchmark readiness is not yet met: " + ", ".join(str(reason) for reason in reasons[:3]) + "."
            )
        else:
            caveats.append("Benchmark readiness is not yet met for the latest run.")
    label_caveat = str((latest_run or {}).get("metrics", {}).get("label_strategy", {}).get("eval_caveat") or "").strip()
    if label_caveat:
        caveats.append(label_caveat)
    if drift and str(drift.get("status") or "").lower() not in {"ok", "stable", "unknown"}:
        caveats.append(f"Latest drift status is {drift['status']}.")
    if not thresholds.get("available"):
        caveats.append("No threshold snapshot is recorded for this lane and model yet.")
    if latest_run and not baselines.get("available"):
        caveats.append(f"No entity baselines are recorded for window {latest_run.get('window_key')}.")
    if scientific_evidence:
        scientific_status = str(scientific_evidence.get("status") or "").lower()
        if scientific_status in {"weak", "limited"}:
            caveats.append(str(scientific_evidence.get("headline") or "Scientific support is still limited across recent windows."))
    return list(dict.fromkeys(caveats))


def _build_judge_lane_summary(db: Session, prediction_type: str) -> dict[str, Any]:
    summary = _build_domain_summary(db, prediction_type)
    latest_run = dict(summary.get("latest_run") or {})
    live_predictions = dict(summary.get("latest_live_predictions") or {})
    latest_run_payload = latest_run or None
    live_predictions_payload = live_predictions or None
    drift = _latest_drift_summary(
        db,
        prediction_type=prediction_type,
        model_version=str(latest_run.get("model_version") or "") or None,
    )
    rollout = _latest_rollout_summary(db, prediction_type=prediction_type)
    thresholds = _threshold_pointer_summary(
        db,
        prediction_type=prediction_type,
        model_version=str(latest_run.get("model_version") or "") or None,
        window_key=str(latest_run.get("window_key") or "") or None,
        window_end=str(latest_run.get("window_end") or "") or None,
    )
    baselines = _baseline_pointer_summary(
        db,
        window_key=str(latest_run.get("window_key") or live_predictions.get("window_key") or "") or None,
    )
    fairness = dict(latest_run.get("fairness") or {})
    operating_metrics = dict(latest_run.get("operating_metrics") or {})
    evaluation_protocol = dict(latest_run.get("metrics", {}).get("evaluation_protocol") or {})
    scientific_evidence = _build_scientific_evidence(db, prediction_type=prediction_type, limit=5)
    caveats = _judge_lane_caveats(
        latest_run=latest_run_payload,
        live_predictions=live_predictions_payload,
        alignment=dict(summary.get("run_prediction_alignment") or {}),
        thresholds=thresholds,
        baselines=baselines,
        drift=drift,
        scientific_evidence=scientific_evidence,
    )
    return {
        "prediction_type": prediction_type,
        "domain_label": summary.get("domain_label"),
        "status": summary.get("status"),
        "status_reasons": list(summary.get("status_reasons") or []),
        "latest_run": (
            {
                "id": latest_run.get("id"),
                "model_version": latest_run.get("model_version"),
                "source_backend": latest_run.get("source_backend"),
                "window_key": latest_run.get("window_key"),
                "window_end": latest_run.get("window_end"),
                "created_at": latest_run.get("created_at"),
                "node_count": latest_run.get("node_count"),
                "edge_count": latest_run.get("edge_count"),
                "positive_count": latest_run.get("positive_count"),
                "auc": latest_run.get("auc"),
                "precision": latest_run.get("precision"),
                "recall": latest_run.get("recall"),
                "f1": latest_run.get("f1"),
            }
            if latest_run_payload else None
        ),
        "live_prediction_alignment": {
            "window_matches": bool((summary.get("run_prediction_alignment") or {}).get("window_matches")),
            "model_version_matches": bool((summary.get("run_prediction_alignment") or {}).get("model_version_matches")),
            "latest_window_key": live_predictions.get("window_key"),
            "latest_window_end": live_predictions.get("window_end"),
            "prediction_count": live_predictions.get("prediction_count"),
            "flagged_count": live_predictions.get("flagged_count"),
            "high_risk_count": live_predictions.get("high_risk_count"),
            "abstained_count": live_predictions.get("abstained_count"),
            "avg_score": live_predictions.get("avg_score"),
            "max_score": live_predictions.get("max_score"),
        },
        "kpi_evidence": {
            "training_metrics": {
                "auc": latest_run.get("auc"),
                "precision": latest_run.get("precision"),
                "recall": latest_run.get("recall"),
                "f1": latest_run.get("f1"),
            },
            "operating_metrics": operating_metrics,
            "thresholds": thresholds,
            "baselines": baselines,
        },
        "scientific_evidence": scientific_evidence,
        "robustness_trust_signals": {
            "fairness_blocked": bool(latest_run.get("fairness_blocked", False)),
            "fairness_flag": fairness.get("fairness_flag"),
            "max_positive_rate_disparity": fairness.get("max_positive_rate_disparity"),
            "real_data_gate_passed": bool(latest_run.get("real_data_gate_passed", False)),
            "benchmarkable": bool(evaluation_protocol.get("benchmarkable", False)) if evaluation_protocol else None,
            "benchmark_reasons": list(evaluation_protocol.get("benchmark_reasons") or []) if evaluation_protocol else [],
            "drift_status": drift.get("status") if drift else None,
            "drift_score": drift.get("drift_score") if drift else None,
            "rollout_mode": rollout.get("rollout_mode") if rollout else None,
            "rollout_status": rollout.get("status") if rollout else None,
        },
        "honest_caveats": caveats,
    }


def _load_json_artifact(candidates: tuple[Path, ...]) -> dict[str, Any] | None:
    for candidate in candidates:
        try:
            if candidate.exists() and candidate.is_file():
                return json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
    return None


def _build_benchmark_evidence() -> dict[str, Any]:
    paysim = _load_json_artifact(BENCHMARK_ARTIFACT_CANDIDATES["paysim_fraud"])
    items: list[dict[str, Any]] = []
    if paysim:
        metrics = dict(paysim.get("metrics") or {})
        run_config = dict(paysim.get("run_config") or {})
        auc = _safe_float(metrics.get("auc"))
        pr_auc = _safe_float(metrics.get("pr_auc"))
        f1 = _safe_float(metrics.get("f1"))
        precision = _safe_float(metrics.get("precision"))
        recall = _safe_float(metrics.get("recall"))
        holdout_positive_count = _safe_int(metrics.get("holdout_positive_count"))
        holdout_negative_count = _safe_int(metrics.get("holdout_negative_count"))
        sample_count = _safe_int(metrics.get("eval_samples"))
        items.append(
            {
                "benchmark_id": "paysim_fraud",
                "label": "PaySim fraud benchmark",
                "domain": "fraud",
                "status": "ok",
                "dataset": paysim.get("dataset"),
                "description": paysim.get("description"),
                "model": paysim.get("model"),
                "recorded_at": paysim.get("run_at"),
                "headline": (
                    f"AUC {auc:.4f}, PR-AUC {pr_auc:.4f} on a held-out PaySim window."
                    if auc is not None and pr_auc is not None
                    else "PaySim benchmark artifact is present."
                ),
                "metrics": {
                    "auc": auc,
                    "pr_auc": pr_auc,
                    "f1": f1,
                    "precision": precision,
                    "recall": recall,
                    "sample_count": sample_count,
                    "evaluation_scope": metrics.get("evaluation_scope"),
                    "holdout_positive_count": holdout_positive_count,
                    "holdout_negative_count": holdout_negative_count,
                },
                "run_config": {
                    "window_key": run_config.get("window_key"),
                    "max_rows": run_config.get("max_rows"),
                    "csv_supplied": bool(run_config.get("csv_supplied")),
                    "csv_name": run_config.get("csv_name"),
                    "csv_sha256": run_config.get("csv_sha256"),
                    "snapshot_inserted": _safe_int(
                        dict(run_config.get("snapshot_seed") or {}).get("inserted")
                    ),
                },
                "honest_caveat": (
                    "This is a strong fraud-ranking benchmark, but the current operating threshold is still conservative: recall is high while precision and F1 remain weaker than the AUC."
                ),
                "artifact_path": str(BENCHMARK_ARTIFACT_CANDIDATES["paysim_fraud"][0]),
            }
        )
    else:
        items.append(
            {
                "benchmark_id": "paysim_fraud",
                "label": "PaySim fraud benchmark",
                "domain": "fraud",
                "status": "missing",
                "headline": "Fresh PaySim benchmark artifact is not available yet.",
                "honest_caveat": "Do not quote a PaySim AUC until the artifact is regenerated from a supplied CSV.",
            }
        )
    return {
        "available": any(item.get("status") == "ok" for item in items),
        "items": items,
    }


@router.get("/benchmarks")
def benchmark_evidence_summary():
    return _build_benchmark_evidence()


@router.get("/predictions")
def list_predictions(
    pagination: dict = Depends(pagination_params),
    prediction_type: str | None = Query(default=None),
    window_key: str | None = Query(default=None),
    entity_key: str | None = Query(default=None),
    model_version: str | None = Query(default=None),
    abstained: bool | None = Query(default=None),
    db: Session = Depends(get_db),
):
    q = db.query(AIPrediction)
    if prediction_type:
        q = q.filter(AIPrediction.prediction_type == prediction_type)
    if window_key:
        q = q.filter(AIPrediction.window_key == window_key)
    if entity_key:
        q = q.filter(AIPrediction.entity_key == entity_key)
    if model_version:
        q = q.filter(AIPrediction.model_version == model_version)
    if abstained is not None:
        q = q.filter(AIPrediction.abstained == bool(abstained))

    rows = (
        q.order_by(AIPrediction.window_end.desc(), AIPrediction.score.desc())
        .offset(pagination["offset"])
        .limit(pagination["limit"])
        .all()
    )
    return {
        "limit": pagination["limit"],
        "offset": pagination["offset"],
        "items": [
            {
                "id": str(r.id),
                "entity_key": r.entity_key,
                "entity_type": r.entity_type,
                "prediction_type": r.prediction_type,
                "model_version": r.model_version,
                "window_key": r.window_key,
                "window_end": r.window_end.isoformat(),
                "score": r.score,
                "confidence": r.confidence,
                "uncertainty": r.uncertainty,
                "abstained": r.abstained,
                "kill_chain_stage": r.kill_chain_stage,
                "decision_source": r.decision_source,
                "reason_codes": r.reason_codes,
                "details": r.details_json,
                "explanation_method": (r.details_json or {}).get("explanation_method"),
                "top_feature": _top_feature(dict(r.details_json or {})),
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ],
    }


@router.get("/predictions/{prediction_id}")
def get_prediction(prediction_id: str, db: Session = Depends(get_db)):
    r = db.query(AIPrediction).filter(AIPrediction.id == prediction_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="prediction_not_found")
    return {
        "id": str(r.id),
        "entity_key": r.entity_key,
        "entity_type": r.entity_type,
        "prediction_type": r.prediction_type,
        "model_version": r.model_version,
        "window_key": r.window_key,
        "window_end": r.window_end.isoformat(),
        "score": r.score,
        "confidence": r.confidence,
        "uncertainty": r.uncertainty,
        "abstained": r.abstained,
        "kill_chain_stage": r.kill_chain_stage,
        "decision_source": r.decision_source,
        "reason_codes": r.reason_codes,
        "details": r.details_json,
        "explanation_method": (r.details_json or {}).get("explanation_method"),
        "top_feature": _top_feature(dict(r.details_json or {})),
        "created_at": r.created_at.isoformat(),
    }


@router.get("/explanations/{prediction_id}")
def get_explanation(prediction_id: str, db: Session = Depends(get_db)):
    r = db.query(AIPrediction).filter(AIPrediction.id == prediction_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="prediction_not_found")
    expl = db.query(AIExplanation).filter(AIExplanation.prediction_id == r.id).first()
    if not expl:
        raise HTTPException(status_code=404, detail="explanation_not_found")
    details = dict(expl.details_json or {})
    method = str(details.get("explanation_method") or "unknown")
    top_feature = _top_feature(details)
    return {
        "prediction_id": str(r.id),
        "entity_key": r.entity_key,
        "prediction_type": r.prediction_type,
        "window_key": r.window_key,
        "window_end": r.window_end.isoformat(),
        "score": r.score,
        "reason_codes": expl.reason_codes,
        "evidence_hashes": expl.evidence_hashes,
        "evidence_paths": expl.evidence_paths,
        "recommended_controls": expl.recommended_controls_json,
        "counterfactual": expl.counterfactual_json,
        "explanation_method": method,
        "model_based": method == "gradient_x_input",
        "top_feature": top_feature,
        "feature_attributions": details.get("feature_attributions", []),
        "attribution_group_scores": details.get("attribution_group_scores", []),
        "details": details,
        "created_at": expl.created_at.isoformat(),
    }


@router.get("/gnn/runs")
def list_gnn_runs(
    pagination: dict = Depends(pagination_params),
    model_version: str | None = Query(default=None),
    prediction_type: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    q = db.query(GNNTrainingRun)
    if model_version:
        q = q.filter(GNNTrainingRun.model_version == model_version)
    if prediction_type:
        q = q.filter(GNNTrainingRun.prediction_type == prediction_type)

    rows = (
        q.order_by(GNNTrainingRun.created_at.desc())
        .offset(pagination["offset"])
        .limit(pagination["limit"])
        .all()
    )
    return {
        "limit": pagination["limit"],
        "offset": pagination["offset"],
        "items": [_serialize_gnn_run(r) for r in rows],
    }


@router.get("/gnn/latest-runs")
def latest_gnn_runs(
    prediction_type: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    prediction_types = [prediction_type] if prediction_type else list(DOMAIN_PREDICTION_TYPES)
    items = [_build_domain_summary(db, kind) for kind in prediction_types]
    return {
        "items": items,
    }


@router.get("/gnn/domain-health")
def gnn_domain_health(
    prediction_type: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    prediction_types = [prediction_type] if prediction_type else list(DOMAIN_PREDICTION_TYPES)
    items = []
    for kind in prediction_types:
        summary = _build_domain_summary(db, kind)
        latest_run = dict(summary.get("latest_run") or {})
        latest_live = dict(summary.get("latest_live_predictions") or {})
        items.append(
            {
                "prediction_type": kind,
                "domain_label": summary.get("domain_label"),
                "status": summary.get("status"),
                "status_reasons": summary.get("status_reasons"),
                "latest_run_created_at": latest_run.get("created_at"),
                "latest_run_window_end": latest_run.get("window_end"),
                "latest_prediction_window_end": latest_live.get("window_end"),
                "latest_prediction_count": latest_live.get("prediction_count"),
                "high_risk_count": latest_live.get("high_risk_count"),
                "flagged_count": latest_live.get("flagged_count"),
                "run_prediction_alignment": summary.get("run_prediction_alignment"),
                "fairness_blocked": latest_run.get("fairness_blocked"),
                "real_data_gate_passed": latest_run.get("real_data_gate_passed"),
            }
        )
    return {"items": items}


@router.get("/gnn/scientific-summary")
def gnn_scientific_summary(
    prediction_type: str | None = Query(default=None),
    limit: int = Query(default=5, ge=1, le=12),
    db: Session = Depends(get_db),
):
    prediction_types = [prediction_type] if prediction_type else list(DOMAIN_PREDICTION_TYPES)
    items = [
        _build_scientific_evidence(db, prediction_type=kind, limit=limit)
        for kind in prediction_types
    ]
    return {"items": items}


@router.get("/judge-readiness")
def judge_readiness_summary(
    prediction_type: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    prediction_types = [prediction_type] if prediction_type else list(DOMAIN_PREDICTION_TYPES)
    lanes = [_build_judge_lane_summary(db, kind) for kind in prediction_types]
    benchmark_evidence = _build_benchmark_evidence()
    statuses = [str(item.get("status") or "missing") for item in lanes]
    overall_status = "ok"
    if not lanes or all(status == "missing" for status in statuses):
        overall_status = "missing"
    elif any(status in {"warn", "missing"} for status in statuses):
        overall_status = "warn"
    aggregated_caveats = [
        "This summary shows operational readiness evidence and caveats; it is not a substitute for legal findings or analyst verification.",
    ]
    for lane in lanes:
        for caveat in list(lane.get("honest_caveats") or []):
            aggregated_caveats.append(f"{lane.get('domain_label')}: {caveat}")
    for item in list(benchmark_evidence.get("items") or []):
        caveat = str(item.get("honest_caveat") or "").strip()
        if caveat:
            aggregated_caveats.append(f"{item.get('label')}: {caveat}")
    return {
        "status": overall_status,
        "headline": (
            "Judge-facing readiness evidence is available."
            if overall_status == "ok"
            else (
                "Judge-facing readiness evidence is available with caveats."
                if overall_status == "warn"
                else "Judge-facing readiness evidence is not available yet."
            )
        ),
        "lanes": lanes,
        "benchmark_evidence": benchmark_evidence,
        "honest_caveats": list(dict.fromkeys(aggregated_caveats)),
        "evidence_endpoints": {
            "latest_runs": "/v1/ai/gnn/latest-runs",
            "domain_health": "/v1/ai/gnn/domain-health",
            "scientific_summary": "/v1/ai/gnn/scientific-summary",
            "benchmarks": "/v1/ai/benchmarks",
            "thresholds": "/v1/ai/thresholds",
            "baselines": "/v1/ai/baselines",
            "trust_summary": "/v1/ai/trust/summary",
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


class GNNTrainRequest(BaseModel):
    domain: Literal["cyber", "corruption"] = "cyber"
    epochs: int = 60
    model_version: str | None = None
    wait_for_completion: bool = True
    allow_demo_real_data_override: bool = False
    allow_demo_fairness_override: bool = False


class DriftRunRequest(BaseModel):
    prediction_type: Literal["risk_gnn", "corruption_risk"] = "risk_gnn"
    window_key: str | None = None
    model_version: str | None = None


def _run_cyber_train(
    epochs: int,
    model_version: str,
    *,
    allow_demo_real_data_override: bool = False,
    allow_demo_fairness_override: bool = False,
) -> dict[str, Any]:
    from app.analytics.layer3.gnn_train_worker import run_once
    from app.ledger.db import SessionLocal
    db = SessionLocal()
    try:
        result = run_once(
            db=db,
            window_key="Wmid",
            epochs=epochs,
            model_version=model_version,
            allow_demo_real_data_override=allow_demo_real_data_override,
            allow_demo_fairness_override=allow_demo_fairness_override,
        )
        log.info("gnn_train_cyber_done: %s", result)
        return result
    except Exception as exc:
        log.exception("gnn_train_cyber_failed: %s", exc)
        return {"status": "error", "stage": "api_train", "detail": str(exc)}
    finally:
        db.close()


def _run_corruption_train(
    epochs: int,
    model_version: str,
    *,
    allow_demo_real_data_override: bool = False,
    allow_demo_fairness_override: bool = False,
) -> dict[str, Any]:
    from app.analytics.corruption.train_worker import run_once
    from app.ledger.db import SessionLocal
    db = SessionLocal()
    try:
        result = run_once(
            db=db,
            window_key="Wcorruption",
            epochs=epochs,
            model_version=model_version,
            allow_demo_real_data_override=allow_demo_real_data_override,
            allow_demo_fairness_override=allow_demo_fairness_override,
        )
        log.info("gnn_train_corruption_done: %s", result)
        return result
    except Exception as exc:
        log.exception("gnn_train_corruption_failed: %s", exc)
        return {"status": "error", "stage": "api_train", "detail": str(exc)}
    finally:
        db.close()


@router.post("/gnn/train")
@limiter.limit("5/minute")
def trigger_gnn_train(
    request: Request,
    body: GNNTrainRequest,
    background_tasks: BackgroundTasks,
    _principal=Depends(require_central_access),
):
    """
    Trigger a GNN retraining run.

    domain = "cyber"       → cyber threat GNN (window_key Wmid, feat_dim 44)
    domain = "corruption"  → corruption risk GNN (window_key Wcorruption, feat_dim 42)

    By default this waits for the selected training run to complete and returns
    the actual outcome. Set wait_for_completion=false for fire-and-forget mode.
    """
    default_versions = {"cyber": "gnn-sage-v1", "corruption": "corruption-gnn-v1"}
    mv = body.model_version or default_versions[body.domain]

    if body.wait_for_completion:
        if body.domain == "cyber":
            result = _run_cyber_train(
                body.epochs,
                mv,
                allow_demo_real_data_override=body.allow_demo_real_data_override,
                allow_demo_fairness_override=body.allow_demo_fairness_override,
            )
        else:
            result = _run_corruption_train(
                body.epochs,
                mv,
                allow_demo_real_data_override=body.allow_demo_real_data_override,
                allow_demo_fairness_override=body.allow_demo_fairness_override,
            )

        payload = {
            "accepted": result.get("status") in {"ok", "blocked"},
            "domain": body.domain,
            "model_version": mv,
            "epochs": body.epochs,
            "wait_for_completion": True,
            "demo_real_data_override_requested": bool(body.allow_demo_real_data_override),
            "demo_fairness_override_requested": bool(body.allow_demo_fairness_override),
            **result,
        }
        status_code = 200
        if result.get("status") == "blocked":
            status_code = 409
        elif result.get("status") == "error":
            status_code = 500
        return JSONResponse(status_code=status_code, content=payload)

    if body.domain == "cyber":
        background_tasks.add_task(
            _run_cyber_train,
            body.epochs,
            mv,
            allow_demo_real_data_override=body.allow_demo_real_data_override,
            allow_demo_fairness_override=body.allow_demo_fairness_override,
        )
    else:
        background_tasks.add_task(
            _run_corruption_train,
            body.epochs,
            mv,
            allow_demo_real_data_override=body.allow_demo_real_data_override,
            allow_demo_fairness_override=body.allow_demo_fairness_override,
        )

    return JSONResponse(
        status_code=202,
        content={
            "accepted": True,
            "domain": body.domain,
            "model_version": mv,
            "epochs": body.epochs,
            "wait_for_completion": False,
            "demo_real_data_override_requested": bool(body.allow_demo_real_data_override),
            "demo_fairness_override_requested": bool(body.allow_demo_fairness_override),
            "message": "Training started in background. Poll GET /v1/ai/gnn/runs for results.",
        },
    )


@router.get("/gnn/runs/{run_id}")
def get_gnn_run(run_id: str, db: Session = Depends(get_db)):
    r = db.query(GNNTrainingRun).filter(GNNTrainingRun.id == run_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="gnn_run_not_found")
    return {
        "id": str(r.id),
        "model_version": r.model_version,
        "prediction_type": r.prediction_type,
        "source_backend": r.source_backend,
        "window_key": r.window_key,
        "window_end": r.window_end.isoformat(),
        "node_count": r.node_count,
        "edge_count": r.edge_count,
        "feature_dim": r.feature_dim,
        "positive_count": r.positive_count,
        "epochs": r.epochs,
        "train_loss": r.train_loss,
        "val_loss": r.val_loss,
        "auc": r.auc,
        "precision": r.precision,
        "recall": r.recall,
        "f1": r.f1,
        "artifact_path": r.artifact_path,
        "params": r.params_json,
        "metrics": r.metrics_json,
        "fairness": (r.metrics_json or {}).get("fairness", {}),
        "fairness_gate": (r.metrics_json or {}).get("fairness_gate", {}),
        "fairness_blocked": _fairness_blocked(r.metrics_json),
        "provenance": (r.metrics_json or {}).get("provenance", {}),
        "real_data_gate": (r.metrics_json or {}).get("real_data_gate", {}),
        "real_data_gate_passed": bool(
            ((r.metrics_json or {}).get("real_data_gate") or {}).get("passed", False)
        ),
        "created_at": r.created_at.isoformat(),
    }


@router.get("/thresholds")
def list_thresholds(
    pagination: dict = Depends(pagination_params),
    model_version: str | None = Query(default=None),
    prediction_type: str | None = Query(default=None),
    entity_type: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    q = db.query(AIRiskThreshold)
    if model_version:
        q = q.filter(AIRiskThreshold.model_version == model_version)
    if prediction_type:
        q = q.filter(AIRiskThreshold.prediction_type == prediction_type)
    if entity_type:
        q = q.filter(AIRiskThreshold.entity_type == entity_type)

    rows = (
        q.order_by(AIRiskThreshold.window_end.desc(), AIRiskThreshold.entity_type.asc())
        .offset(pagination["offset"])
        .limit(pagination["limit"])
        .all()
    )
    return {
        "limit": pagination["limit"],
        "offset": pagination["offset"],
        "items": [
            {
                "id": str(r.id),
                "model_version": r.model_version,
                "prediction_type": r.prediction_type,
                "entity_type": r.entity_type,
                "window_key": r.window_key,
                "window_end": r.window_end.isoformat(),
                "threshold_score": r.threshold_score,
                "method": r.method,
                "sample_count": r.sample_count,
                "positive_count": r.positive_count,
                "cost_weight": r.cost_weight,
                "metrics": r.metrics_json,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ],
    }


@router.get("/campaign-indicators")
def list_campaign_indicators(
    pagination: dict = Depends(pagination_params),
    prediction_type: str | None = Query(default=None),
    min_score: float | None = Query(default=None, ge=0.0, le=100.0),
    severity: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    q = db.query(AICampaignRiskIndicator)
    if prediction_type:
        q = q.filter(AICampaignRiskIndicator.prediction_type == prediction_type)
    if min_score is not None:
        q = q.filter(AICampaignRiskIndicator.score >= min_score)
    if severity:
        q = q.filter(AICampaignRiskIndicator.severity == severity)

    rows = (
        q.order_by(AICampaignRiskIndicator.window_end.desc(), AICampaignRiskIndicator.score.desc())
        .offset(pagination["offset"])
        .limit(pagination["limit"])
        .all()
    )
    return {
        "limit": pagination["limit"],
        "offset": pagination["offset"],
        "items": [
            {
                "id": str(r.id),
                "campaign_id": str(r.campaign_id),
                "prediction_type": r.prediction_type,
                "model_version": r.model_version,
                "window_key": r.window_key,
                "window_end": r.window_end.isoformat(),
                "score": r.score,
                "severity": r.severity,
                "flagged_entity_count": r.flagged_entity_count,
                "total_entity_count": r.total_entity_count,
                "reason_codes": r.reason_codes,
                "details": r.details_json,
                "evidence_entity_keys": r.evidence_entity_keys,
                "created_at": r.created_at.isoformat(),
                "updated_at": r.updated_at.isoformat(),
            }
            for r in rows
        ],
    }


@router.get("/techniques")
def list_techniques(
    pagination: dict = Depends(pagination_params),
    prediction_type: str | None = Query(default=None),
    entity_key: str | None = Query(default=None),
    technique_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    q = db.query(AIAttackTechniqueHit)
    if prediction_type:
        q = q.filter(AIAttackTechniqueHit.prediction_type == prediction_type)
    if entity_key:
        q = q.filter(AIAttackTechniqueHit.entity_key == entity_key)
    if technique_id:
        q = q.filter(AIAttackTechniqueHit.technique_id == technique_id)

    rows = (
        q.order_by(AIAttackTechniqueHit.window_end.desc(), AIAttackTechniqueHit.confidence.desc())
        .offset(pagination["offset"])
        .limit(pagination["limit"])
        .all()
    )
    return {
        "limit": pagination["limit"],
        "offset": pagination["offset"],
        "items": [
            {
                "id": str(r.id),
                "entity_key": r.entity_key,
                "prediction_type": r.prediction_type,
                "window_key": r.window_key,
                "window_end": r.window_end.isoformat(),
                "technique_id": r.technique_id,
                "tactic": r.tactic,
                "confidence": r.confidence,
                "source": r.source_json,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ],
    }


@router.get("/path-scores")
def list_path_scores(
    pagination: dict = Depends(pagination_params),
    prediction_type: str | None = Query(default=None),
    entity_key: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    q = db.query(AIAttackPathScore)
    if prediction_type:
        q = q.filter(AIAttackPathScore.prediction_type == prediction_type)
    if entity_key:
        q = q.filter(AIAttackPathScore.entity_key == entity_key)

    rows = (
        q.order_by(AIAttackPathScore.window_end.desc(), AIAttackPathScore.path_score.desc())
        .offset(pagination["offset"])
        .limit(pagination["limit"])
        .all()
    )
    return {
        "limit": pagination["limit"],
        "offset": pagination["offset"],
        "items": [
            {
                "id": str(r.id),
                "entity_key": r.entity_key,
                "prediction_type": r.prediction_type,
                "window_key": r.window_key,
                "window_end": r.window_end.isoformat(),
                "path_score": r.path_score,
                "hop_count": r.hop_count,
                "evidence_entity_keys": r.evidence_entity_keys,
                "details": r.details_json,
            }
            for r in rows
        ],
    }


@router.get("/link-predictions")
def list_link_predictions(
    pagination: dict = Depends(pagination_params),
    model_version: str | None = Query(default=None),
    prediction_type: str | None = Query(default=None),
    min_score: float | None = Query(default=None),
    db: Session = Depends(get_db),
):
    q = db.query(AILinkPrediction)
    if model_version:
        q = q.filter(AILinkPrediction.model_version == model_version)
    if prediction_type:
        q = q.filter(AILinkPrediction.prediction_type == prediction_type)
    if min_score is not None:
        q = q.filter(AILinkPrediction.score >= min_score)

    rows = (
        q.order_by(AILinkPrediction.window_end.desc(), AILinkPrediction.score.desc())
        .offset(pagination["offset"])
        .limit(pagination["limit"])
        .all()
    )
    return {
        "limit": pagination["limit"],
        "offset": pagination["offset"],
        "items": [
            {
                "id": str(r.id),
                "src_entity_key": r.src_entity_key,
                "dst_entity_key": r.dst_entity_key,
                "prediction_type": r.prediction_type,
                "model_version": r.model_version,
                "window_key": r.window_key,
                "window_end": r.window_end.isoformat(),
                "score": r.score,
                "method": r.method,
                "details": r.details_json,
            }
            for r in rows
        ],
    }


@router.get("/decision-fusions")
def list_decision_fusions(
    pagination: dict = Depends(pagination_params),
    prediction_type: str | None = Query(default=None),
    entity_key: str | None = Query(default=None),
    window_key: str | None = Query(default=None),
    decision: str | None = Query(default=None),
    min_score: float | None = Query(default=None),
    db: Session = Depends(get_db),
):
    q = db.query(AIDecisionFusion)
    if prediction_type:
        q = q.filter(AIDecisionFusion.prediction_type == prediction_type)
    if entity_key:
        q = q.filter(AIDecisionFusion.entity_key == entity_key)
    if window_key:
        q = q.filter(AIDecisionFusion.window_key == window_key)
    if decision:
        q = q.filter(AIDecisionFusion.decision == decision)
    if min_score is not None:
        q = q.filter(AIDecisionFusion.fused_score >= min_score)

    rows = (
        q.order_by(AIDecisionFusion.window_end.desc(), AIDecisionFusion.fused_score.desc())
        .offset(pagination["offset"])
        .limit(pagination["limit"])
        .all()
    )
    return {
        "limit": pagination["limit"],
        "offset": pagination["offset"],
        "items": [
            {
                "id": str(r.id),
                "entity_key": r.entity_key,
                "prediction_type": r.prediction_type,
                "window_key": r.window_key,
                "window_end": r.window_end.isoformat(),
                "fused_score": r.fused_score,
                "severity": r.severity,
                "decision": r.decision,
                "selected_model_version": r.selected_model_version,
                "signals": r.signals_json,
            }
            for r in rows
        ],
    }


@router.get("/drift-reports")
def list_drift_reports(
    pagination: dict = Depends(pagination_params),
    prediction_type: str | None = Query(default=None),
    model_version: str | None = Query(default=None),
    status: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    q = db.query(AIDriftReport)
    if prediction_type:
        q = q.filter(AIDriftReport.prediction_type == prediction_type)
    if model_version:
        q = q.filter(AIDriftReport.model_version == model_version)
    if status:
        q = q.filter(AIDriftReport.status == status)

    rows = (
        q.order_by(AIDriftReport.window_end.desc(), AIDriftReport.created_at.desc())
        .offset(pagination["offset"])
        .limit(pagination["limit"])
        .all()
    )
    return {
        "limit": pagination["limit"],
        "offset": pagination["offset"],
        "items": [
            {
                "id": str(r.id),
                "prediction_type": r.prediction_type,
                "model_version": r.model_version,
                "window_key": r.window_key,
                "window_end": r.window_end.isoformat(),
                "drift_score": r.drift_score,
                "status": r.status,
                "metrics": r.metrics_json,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ],
    }


@router.post("/drift-reports/run")
def run_drift_report(
    body: DriftRunRequest,
    _principal=Depends(require_central_access),
    db: Session = Depends(get_db),
):
    latest_run = (
        db.query(GNNTrainingRun)
        .filter(GNNTrainingRun.prediction_type == body.prediction_type)
        .order_by(GNNTrainingRun.window_end.desc(), GNNTrainingRun.created_at.desc())
        .first()
    )
    model_version = body.model_version or (latest_run.model_version if latest_run else None)
    if not model_version:
        raise HTTPException(status_code=404, detail="gnn_run_not_found")

    window_key = body.window_key or (latest_run.window_key if latest_run else None)
    if not window_key:
        window_key = "Wmid" if body.prediction_type == "risk_gnn" else "Wcorruption"

    try:
        from app.analytics.layer3.drift_worker import run_once as run_drift  # noqa: PLC0415

        return run_drift(
            db=db,
            prediction_type=body.prediction_type,
            window_key=window_key,
            model_version=model_version,
        )
    except Exception:
        log.exception("ai_run_drift_report_failed")
        raise HTTPException(status_code=500, detail="internal_error")


@router.get("/input-anomalies")
def list_input_anomalies(
    pagination: dict = Depends(pagination_params),
    entity_key: str | None = Query(default=None),
    anomaly_type: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    q = db.query(AIInputAnomalyAlert)
    if entity_key:
        q = q.filter(AIInputAnomalyAlert.entity_key == entity_key)
    if anomaly_type:
        q = q.filter(AIInputAnomalyAlert.anomaly_type == anomaly_type)
    rows = (
        q.order_by(AIInputAnomalyAlert.window_end.desc(), AIInputAnomalyAlert.score.desc())
        .offset(pagination["offset"])
        .limit(pagination["limit"])
        .all()
    )
    return {
        "limit": pagination["limit"],
        "offset": pagination["offset"],
        "items": [
            {
                "id": str(r.id),
                "entity_key": r.entity_key,
                "window_key": r.window_key,
                "window_end": r.window_end.isoformat(),
                "anomaly_type": r.anomaly_type,
                "score": r.score,
                "details": r.details_json,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ],
    }


@router.get("/baselines")
def list_baselines(
    pagination: dict = Depends(pagination_params),
    window_key: str | None = Query(default=None),
    entity_key: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    q = db.query(EntityRiskBaseline)
    if window_key:
        q = q.filter(EntityRiskBaseline.window_key == window_key)
    if entity_key:
        q = q.filter(EntityRiskBaseline.entity_key == entity_key)
    rows = (
        q.order_by(EntityRiskBaseline.updated_at.desc())
        .offset(pagination["offset"])
        .limit(pagination["limit"])
        .all()
    )
    return {
        "limit": pagination["limit"],
        "offset": pagination["offset"],
        "items": [
            {
                "id": str(r.id),
                "entity_key": r.entity_key,
                "entity_type": r.entity_type,
                "window_key": r.window_key,
                "baseline_score": r.baseline_score,
                "baseline_std": r.baseline_std,
                "sample_count": r.sample_count,
                "last_window_end": r.last_window_end.isoformat() if r.last_window_end else None,
                "updated_at": r.updated_at.isoformat(),
            }
            for r in rows
        ],
    }


@router.post("/feedback")
def create_feedback(
    prediction_id: str,
    feedback_label: int = Query(..., ge=0, le=2),
    analyst_id: str = Query(...),
    notes: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    pred = db.query(AIPrediction).filter(AIPrediction.id == prediction_id).first()
    if not pred:
        raise HTTPException(status_code=404, detail="prediction_not_found")

    row = AIFeedbackLabel(
        id=uuid.uuid4(),
        prediction_id=pred.id,
        entity_key=pred.entity_key,
        feedback_label=int(feedback_label),
        analyst_id=analyst_id,
        notes=notes,
        status="queued",
        used_in_training=False,
    )
    db.add(row)
    db.commit()
    return {
        "id": str(row.id),
        "prediction_id": prediction_id,
        "entity_key": row.entity_key,
        "feedback_label": row.feedback_label,
        "analyst_id": row.analyst_id,
        "status": row.status,
        "created_at": row.created_at.isoformat(),
    }


@router.get("/feedback")
def list_feedback(
    pagination: dict = Depends(pagination_params),
    status: str | None = Query(default=None),
    analyst_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    q = db.query(AIFeedbackLabel)
    if status:
        q = q.filter(AIFeedbackLabel.status == status)
    if analyst_id:
        q = q.filter(AIFeedbackLabel.analyst_id == analyst_id)
    rows = (
        q.order_by(AIFeedbackLabel.created_at.desc())
        .offset(pagination["offset"])
        .limit(pagination["limit"])
        .all()
    )
    return {
        "limit": pagination["limit"],
        "offset": pagination["offset"],
        "items": [
            {
                "id": str(r.id),
                "prediction_id": str(r.prediction_id),
                "entity_key": r.entity_key,
                "feedback_label": r.feedback_label,
                "analyst_id": r.analyst_id,
                "notes": r.notes,
                "status": r.status,
                "used_in_training": r.used_in_training,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ],
    }


@router.get("/rollouts")
def list_rollouts(
    pagination: dict = Depends(pagination_params),
    prediction_type: str | None = Query(default=None),
    status: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    q = db.query(AIModelRollout)
    if prediction_type:
        q = q.filter(AIModelRollout.prediction_type == prediction_type)
    if status:
        q = q.filter(AIModelRollout.status == status)
    rows = (
        q.order_by(AIModelRollout.updated_at.desc())
        .offset(pagination["offset"])
        .limit(pagination["limit"])
        .all()
    )
    return {
        "limit": pagination["limit"],
        "offset": pagination["offset"],
        "items": [
            {
                "rollout_id": r.rollout_id,
                "prediction_type": r.prediction_type,
                "active_model_version": r.active_model_version,
                "shadow_model_version": r.shadow_model_version,
                "rollout_mode": r.rollout_mode,
                "canary_ratio": r.canary_ratio,
                "auto_rollback": r.auto_rollback,
                "min_sample_count": r.min_sample_count,
                "status": r.status,
                "created_by": r.created_by,
                "metadata": r.metadata_json,
                "created_at": r.created_at.isoformat(),
                "updated_at": r.updated_at.isoformat(),
            }
            for r in rows
        ],
    }


@router.post("/rollouts")
def upsert_rollout(
    prediction_type: str,
    active_model_version: str,
    shadow_model_version: str | None = None,
    rollout_mode: str = Query(default="single"),
    canary_ratio: float = Query(default=0.0, ge=0.0, le=1.0),
    auto_rollback: bool = Query(default=True),
    min_sample_count: int = Query(default=500, ge=1),
    created_by: str = Query(default="api"),
    db: Session = Depends(get_db),
):
    row = (
        db.query(AIModelRollout)
        .filter(AIModelRollout.prediction_type == prediction_type)
        .filter(AIModelRollout.status == "active")
        .first()
    )
    now = datetime.utcnow()
    if row:
        row.active_model_version = active_model_version
        row.shadow_model_version = shadow_model_version
        row.rollout_mode = rollout_mode
        row.canary_ratio = canary_ratio
        row.auto_rollback = auto_rollback
        row.min_sample_count = min_sample_count
        row.updated_at = now
    else:
        row = AIModelRollout(
            rollout_id=str(uuid.uuid4()),
            prediction_type=prediction_type,
            active_model_version=active_model_version,
            shadow_model_version=shadow_model_version,
            rollout_mode=rollout_mode,
            canary_ratio=canary_ratio,
            auto_rollback=auto_rollback,
            min_sample_count=min_sample_count,
            status="active",
            created_by=created_by,
            metadata_json={},
            created_at=now,
            updated_at=now,
        )
        db.add(row)
    db.commit()
    return {
        "rollout_id": row.rollout_id,
        "prediction_type": row.prediction_type,
        "active_model_version": row.active_model_version,
        "shadow_model_version": row.shadow_model_version,
        "rollout_mode": row.rollout_mode,
        "canary_ratio": row.canary_ratio,
        "auto_rollback": row.auto_rollback,
        "status": row.status,
    }


@router.get("/threat-intel")
def list_threat_intel(
    pagination: dict = Depends(pagination_params),
    indicator_type: str | None = Query(default=None),
    source: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    q = db.query(ThreatIntelIndicator)
    if indicator_type:
        q = q.filter(ThreatIntelIndicator.indicator_type == indicator_type)
    if source:
        q = q.filter(ThreatIntelIndicator.source == source)

    rows = (
        q.order_by(ThreatIntelIndicator.updated_at.desc())
        .offset(pagination["offset"])
        .limit(pagination["limit"])
        .all()
    )

    return {
        "limit": pagination["limit"],
        "offset": pagination["offset"],
        "items": [
            {
                "indicator_id": r.indicator_id,
                "stix_id": r.stix_id,
                "indicator_type": r.indicator_type,
                "value": r.value,
                "confidence": r.confidence,
                "source": r.source,
                "valid_from": r.valid_from.isoformat() if r.valid_from else None,
                "valid_until": r.valid_until.isoformat() if r.valid_until else None,
                "tags": r.tags_json,
                "metadata": r.metadata_json,
                "created_at": r.created_at.isoformat(),
                "updated_at": r.updated_at.isoformat(),
            }
            for r in rows
        ],
    }


# ── /v1/ai/tool-attribution ───────────────────────────────────────────────────
@router.get("/tool-attribution")
def tool_attribution(
    entity_key: str = Query(..., description="Entity key to look up"),
    db: Session = Depends(get_db),
):
    """
    Enriches entity's ATT&CK technique hits with known attacker tools/malware
    from the curated MITRE ATT&CK Software catalog.
    """
    from app.analytics.ai_models import AIAttackTechniqueHit
    from app.analytics.layer3.ai_intel import techniques_to_tools

    rows = (
        db.query(AIAttackTechniqueHit)
        .filter(AIAttackTechniqueHit.entity_key == entity_key)
        .order_by(AIAttackTechniqueHit.confidence.desc())
        .limit(50)
        .all()
    )
    if not rows:
        return {
            "entity_key": entity_key,
            "techniques": [],
            "tools": [],
            "summary": {"technique_count": 0, "tool_count": 0, "top_tactic": None},
        }
    techniques = [
        {
            "technique_id": r.technique_id,
            "tactic": r.tactic,
            "confidence": float(r.confidence or 0.0),
            "source_event_type": (
                str((r.source_json or {}).get("source_event_type"))
                if (r.source_json or {}).get("source_event_type") is not None
                else None
            ),
        }
        for r in rows
    ]
    technique_ids = [r.technique_id for r in rows]
    tools = techniques_to_tools(technique_ids)
    tactic_counts: Dict[str, int] = {}
    for t in techniques:
        tac = str(t.get("tactic") or "unknown")
        tactic_counts[tac] = tactic_counts.get(tac, 0) + 1
    top_tactic = max(tactic_counts, key=lambda k: tactic_counts[k]) if tactic_counts else None
    return {
        "entity_key": entity_key,
        "techniques": techniques,
        "tools": tools,
        "summary": {
            "technique_count": len(techniques),
            "tool_count": len(tools),
            "top_tactic": top_tactic,
            "tactic_distribution": tactic_counts,
        },
    }


# ── /v1/ai/tools/summary ─────────────────────────────────────────────────────
@router.get("/tools/summary")
def tools_summary(
    min_score: float = Query(default=70.0, ge=0.0, le=100.0),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """
    Top attacker tools inferred from ATT&CK technique hits of all high-risk entities.
    """
    from app.analytics.ai_models import AIAttackTechniqueHit, AIPrediction
    from app.analytics.layer3.ai_intel import techniques_to_tools
    from collections import Counter

    high_risk = (
        db.query(AIPrediction.entity_key)
        .filter(AIPrediction.prediction_type == "risk_gnn")
        .filter(AIPrediction.score >= min_score)
        .order_by(AIPrediction.score.desc())
        .limit(limit)
        .all()
    )
    entity_keys = [str(r[0]) for r in high_risk]
    if not entity_keys:
        return {"tools": [], "techniques": [], "entity_count": 0}
    tech_rows = (
        db.query(AIAttackTechniqueHit)
        .filter(AIAttackTechniqueHit.entity_key.in_(entity_keys))
        .all()
    )
    all_technique_ids = [r.technique_id for r in tech_rows]
    tactic_counter: Counter = Counter(r.tactic for r in tech_rows)
    tool_counter: Counter = Counter()
    for r in tech_rows:
        for sw in techniques_to_tools([r.technique_id]):
            tool_counter[sw["name"]] += 1
    top_tools = [{"name": n, "entity_hits": c} for n, c in tool_counter.most_common(20)]
    tools = techniques_to_tools(all_technique_ids)
    return {
        "entity_count": len(entity_keys),
        "min_score_filter": min_score,
        "top_tools": top_tools,
        "tactic_distribution": dict(tactic_counter.most_common()),
        "unique_tools_inferred": len({sw["name"] for sw in tools}),
        "unique_techniques_observed": len(set(all_technique_ids)),
    }


@router.post("/threat-intel/import-stix")
def import_threat_intel(bundle: dict, source: str = Query(default="stix"), db: Session = Depends(get_db)):
    try:
        return import_stix_bundle(db=db, bundle=bundle, source=source)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"threat_intel_import_failed:{e}")


@router.post("/threat-intel/export-stix")
def export_threat_intel(source: str = Query(default="sentinel"), limit: int = Query(default=200, ge=1, le=5000), db: Session = Depends(get_db)):
    try:
        return export_stix_bundle(db=db, source=source, limit=limit)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"threat_intel_export_failed:{e}")


# ── /v1/ai/indicators/summary ─────────────────────────────────────────────────
# Unified threat-indicator summary for the S2 Timeline / Indicators screen.
# Sources: event_log (all event types) + ai_prediction (risk_gnn) +
#          ai_campaign_risk_indicator.  No OpenSearch dependency.
@router.get("/indicators/summary")
def threat_indicators_summary(
    days: int = Query(default=7, ge=1, le=30),
    db: Session = Depends(get_db),
):
    from sqlalchemy import text as _text
    from datetime import timezone

    # ── 1. Event volume by day + category ───────────────────────────────────
    vol_sql = _text("""
        SELECT
            date_trunc('day', occurred_at AT TIME ZONE 'UTC')::date AS day,
            CASE
                WHEN event_type IN (
                    'TRANSACTION_EVENT','AIRTIME_TRANSFER_EVENT',
                    'PAYMENT_DISBURSEMENT','SIM_SWAP_EVENT'
                ) THEN 'fraud'
                WHEN event_type = 'DDOS_SIGNAL_EVENT'         THEN 'ddos'
                WHEN event_type IN ('DFIR_FINDING_EVENT','DNS_RESOLUTION_EVENT',
                                    'NETWORK_ANOMALY_EVENT')  THEN 'network'
                WHEN event_type = 'VULNERABILITY_EVENT'        THEN 'vulnerability'
                WHEN event_type = 'PHISHING_MESSAGE_EVENT'     THEN 'phishing'
                WHEN event_type IN ('THREAT_INTEL_EVENT','INDICATOR_EVENT') THEN 'threat_intel'
                ELSE 'other'
            END AS category,
            COUNT(*) AS cnt
        FROM event_log
        WHERE occurred_at >= NOW() - INTERVAL '1 day' * :days
        GROUP BY 1, 2
        ORDER BY 1
    """)
    vol_rows = db.execute(vol_sql, {"days": days}).fetchall()

    # Pivot into day → {category: count}
    from collections import defaultdict
    day_vol: dict = defaultdict(lambda: {"fraud": 0, "ddos": 0, "network": 0,
                                          "vulnerability": 0, "phishing": 0,
                                          "threat_intel": 0, "other": 0, "total": 0})
    for row in vol_rows:
        d = str(row[0])
        cat = row[1]
        cnt = int(row[2])
        day_vol[d][cat] = cnt
        day_vol[d]["total"] += cnt

    event_volume_series = [
        {"date": d, **v} for d, v in sorted(day_vol.items())
    ]

    # ── 2. GNN risk trajectory by day ───────────────────────────────────────
    gnn_sql = _text("""
        SELECT
            date_trunc('day', window_end AT TIME ZONE 'UTC')::date AS day,
            COUNT(*)                                                AS prediction_count,
            AVG(score)                                              AS avg_score,
            MAX(score)                                              AS max_score,
            PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY score)     AS p90_score
        FROM ai_prediction
        WHERE prediction_type = 'risk_gnn'
          AND window_end >= NOW() - INTERVAL '1 day' * :days
        GROUP BY 1
        ORDER BY 1
    """)
    gnn_rows = db.execute(gnn_sql, {"days": days}).fetchall()
    gnn_risk_series = [
        {
            "date":             str(r[0]),
            "prediction_count": int(r[1]),
            "avg_score":        round(float(r[2]), 1),
            "max_score":        round(float(r[3]), 1),
            "p90_score":        round(float(r[4]), 1),
        }
        for r in gnn_rows
    ]

    # ── 3. Campaign risk severity breakdown ──────────────────────────────────
    sev_sql = _text("""
        SELECT severity, COUNT(*) AS cnt
        FROM ai_campaign_risk_indicator
        GROUP BY severity
    """)
    sev_rows = db.execute(sev_sql).fetchall()
    campaign_risk: dict = {"critical": 0, "high": 0, "medium": 0, "low": 0, "total": 0}
    for r in sev_rows:
        sev = str(r[0]).lower()
        cnt = int(r[1])
        if sev in campaign_risk:
            campaign_risk[sev] = cnt
        campaign_risk["total"] += cnt

    # ── 4. Top at-risk entities (latest GNN window) ──────────────────────────
    top_sql = _text("""
        SELECT DISTINCT ON (entity_key)
            entity_key,
            entity_type,
            score,
            kill_chain_stage,
            reason_codes,
            window_end
        FROM ai_prediction
        WHERE prediction_type = 'risk_gnn'
        ORDER BY entity_key, window_end DESC, score DESC
    """)
    top_all = db.execute(top_sql).fetchall()
    top_all_sorted = sorted(top_all, key=lambda r: float(r[2]), reverse=True)[:10]
    top_threats = [
        {
            "entity_key":       r[0],
            "entity_type":      r[1],
            "score":            round(float(r[2]), 1),
            "kill_chain_stage": r[3],
            "reason_codes":     r[4] if isinstance(r[4], list) else [],
            "severity":         _severity_from_score(float(r[2])),
        }
        for r in top_all_sorted
    ]

    # ── 5. Kill-chain stage distribution ────────────────────────────────────
    kc_sql = _text("""
        SELECT kill_chain_stage, COUNT(*) AS cnt
        FROM ai_prediction
        WHERE prediction_type = 'risk_gnn'
          AND kill_chain_stage IS NOT NULL
        GROUP BY kill_chain_stage
        ORDER BY cnt DESC
    """)
    kc_rows = db.execute(kc_sql).fetchall()
    kill_chain_distribution = {str(r[0]): int(r[1]) for r in kc_rows}

    # ── 6. Quick event-type totals (for summary cards) ───────────────────────
    totals_sql = _text("""
        SELECT
            SUM(CASE WHEN event_type IN ('TRANSACTION_EVENT','AIRTIME_TRANSFER_EVENT',
                'PAYMENT_DISBURSEMENT','SIM_SWAP_EVENT') THEN 1 ELSE 0 END) AS fraud,
            SUM(CASE WHEN event_type = 'DDOS_SIGNAL_EVENT' THEN 1 ELSE 0 END) AS ddos,
            SUM(CASE WHEN event_type IN ('DFIR_FINDING_EVENT','DNS_RESOLUTION_EVENT',
                'NETWORK_ANOMALY_EVENT') THEN 1 ELSE 0 END)                  AS network,
            SUM(CASE WHEN event_type = 'VULNERABILITY_EVENT' THEN 1 ELSE 0 END)     AS vulnerability,
            SUM(CASE WHEN event_type = 'PHISHING_MESSAGE_EVENT' THEN 1 ELSE 0 END)  AS phishing,
            COUNT(*)                                                                 AS total
        FROM event_log
    """)
    tot = db.execute(totals_sql).fetchone()
    event_totals = {
        "fraud":         int(tot[0] or 0),
        "ddos":          int(tot[1] or 0),
        "network":       int(tot[2] or 0),
        "vulnerability": int(tot[3] or 0),
        "phishing":      int(tot[4] or 0),
        "total":         int(tot[5] or 0),
    }

    # ── 7. Shared limited-data forecast based on daily GNN avg scores ───────
    forecast_detail = build_risk_forecast(history=gnn_risk_series, horizon=7, alpha=0.3, beta=0.1)
    forecast = summarize_forecast_card(forecast_detail, target_day=3)

    return {
        "generated_at":          datetime.now(timezone.utc).isoformat(),
        "window_days":           days,
        "event_volume_series":   event_volume_series,
        "gnn_risk_series":       gnn_risk_series,
        "campaign_risk":         campaign_risk,
        "top_threats":           top_threats,
        "kill_chain_distribution": kill_chain_distribution,
        "event_totals":          event_totals,
        "forecast":              forecast,
        "forecast_detail":       forecast_detail,
    }


# ── /v1/ai/forecast ───────────────────────────────────────────────────────────
@router.get("/forecast")
def ai_risk_forecast(
    days: int = Query(default=14, ge=3, le=60, description="History window in days"),
    horizon: int = Query(default=7, ge=1, le=30, description="Forecast horizon in days"),
    alpha: float = Query(default=0.3, ge=0.05, le=0.95, description="Level smoothing factor"),
    beta: float = Query(default=0.1, ge=0.01, le=0.5, description="Trend smoothing factor"),
    db: Session = Depends(get_db),
):
    from sqlalchemy import text as _text

    hist_sql = _text("""
        SELECT
            date_trunc('day', window_end AT TIME ZONE 'UTC')::date AS day,
            AVG(score)   AS avg_score,
            MAX(score)   AS max_score,
            COUNT(*)     AS n
        FROM ai_prediction
        WHERE prediction_type = 'risk_gnn'
          AND window_end >= NOW() - INTERVAL '1 day' * :days
        GROUP BY 1
        ORDER BY 1
    """)
    rows = db.execute(hist_sql, {"days": days}).fetchall()
    history = [
        {
            "date": str(r[0]),
            "avg_score": round(float(r[1] or 0.0), 2),
            "max_score": round(float(r[2] or 0.0), 2),
            "n": int(r[3] or 0),
        }
        for r in rows
    ]
    return build_risk_forecast(
        history=history,
        horizon=horizon,
        alpha=alpha,
        beta=beta,
    )


@router.get("/forecast/scenario")
def ai_scenario_forecast(
    scenario: str = Query(..., description="ddos, vpn, sim_swap, fraud, ddos_vpn, ddos_vpn_fraud, or all"),
    lookback_hours: int = Query(default=48, ge=6, le=168, description="History window in hours"),
    horizon_hours: int = Query(default=24, ge=1, le=72, description="Forecast horizon in hours"),
    alpha: float = Query(default=0.3, ge=0.05, le=0.95, description="Level smoothing factor"),
    beta: float = Query(default=0.1, ge=0.01, le=0.5, description="Trend smoothing factor"),
    db: Session = Depends(get_db),
):
    raw_scenario = str(scenario or "").strip().lower()
    normalized = _normalize_scenario_name(raw_scenario)
    label = SCENARIO_LABELS.get(normalized)
    if not label:
        raise HTTPException(
            status_code=400,
            detail="invalid_scenario: use ddos, vpn, sim_swap, fraud, ddos_vpn, ddos_vpn_fraud, or all",
        )

    history, source_summary = _scenario_forecast_history(
        db=db,
        scenario=normalized,
        lookback_hours=lookback_hours,
    )
    forecast = build_signal_forecast(
        history=history,
        horizon=horizon_hours,
        alpha=alpha,
        beta=beta,
        season_length=24,
        granularity="hour",
        time_field="timestamp",
        value_field="score",
        signal_name=f"{label} pressure signal",
    )
    forecast["scenario"] = raw_scenario
    forecast["normalized_scenario"] = normalized
    forecast["display_name"] = label
    forecast["lookback_hours"] = lookback_hours
    forecast["source_summary"] = {
        **source_summary,
        "scenario_alias_applied": raw_scenario != normalized,
    }
    if forecast.get("status") == "ok":
        alert = forecast.get("alert_recommendation") or {}
        level = str((alert or {}).get("level") or "NORMAL")
        forecast["recommended_operator_posture"] = _scenario_recommended_posture(level, label)
        forecast["scenario_explanation"] = (
            f"This forecast tracks {label.lower()} using hourly event pressure from scenario-matched ingest data. "
            "It is an operational pressure forecast, not a guarantee that a specific attack will happen."
        )
    else:
        forecast["recommended_operator_posture"] = (
            f"Not enough {label.lower()} history is available yet. Replay the scenario, wait for ingest to settle, then rerun the forecast."
        )
        forecast["scenario_explanation"] = (
            f"This route forecasts hourly {label.lower()} pressure once at least three hourly history points exist."
        )
    return forecast


@router.get("/trust/entity")
def entity_trust_summary(
    entity_key: str = Query(..., description="Entity key to inspect"),
    prediction_type: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    try:
        return build_entity_trust_summary(
            db=db,
            entity_key=entity_key,
            prediction_type=prediction_type,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/trust/summary")
def platform_trust_summary(db: Session = Depends(get_db)):
    return build_platform_trust_summary(db=db)


# ---------------------------------------------------------------------------
# NL Analyst Copilot
# POST /v1/ai/query
# ---------------------------------------------------------------------------

class CopilotQueryRequest(BaseModel):
    question: str
    context: dict[str, Any] | None = None


@router.post("/query", summary="NL analyst copilot — ask Sentinel Copilot a question")
def nl_copilot_query(payload: CopilotQueryRequest, db: Session = Depends(get_db)):
    """
    Local natural-language analyst copilot.
    """
    if not settings.ai_copilot_enabled:
        raise HTTPException(status_code=503, detail="ai_copilot_disabled")
    try:
        result = answer_local_analyst_query(
            db=db,
            question=payload.question.strip(),
            context=payload.context,
        )
    except Exception as exc:
        log.exception("copilot_error: %s", exc)
        raise HTTPException(status_code=500, detail=f"local_copilot_error: {exc}")

    return {
        "answer": result["answer"],
        "model": result["model"],
        "intent": result.get("intent"),
        "sources": result.get("sources", []),
        "question": payload.question,
        "context_provided": payload.context is not None,
    }

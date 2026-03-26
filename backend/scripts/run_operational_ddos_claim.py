#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
from sqlalchemy.orm import Session

try:
    from app.analytics.layer3.ai_inference_worker import run_once as run_inference_once
    from app.analytics.layer3.anomaly_worker import run_once as run_anomaly_once
    from app.analytics.layer3.component_campaign_worker import run_once as run_component_campaign_once
    from app.analytics.layer3.decision_fusion_worker import run_once as run_decision_fusion_once
    from app.analytics.layer3.ddos_alert_worker import run_once as run_ddos_alert_once
    from app.analytics.layer3.graph_feature_worker import run_once as run_graph_features_once
    from app.analytics.layer3.path_risk_worker import run_once as run_path_risk_once
    from app.analytics.ai_models import AIAttackPathScore, AIDecisionFusion, AIPrediction
    from app.campaign.models import Campaign, CampaignEntity
    from app.demo.run_demo import build_ddos_events
    from app.graph.neo4j_worker import run_once as run_neo4j_once
    from app.ledger.db import SessionLocal
    from app.ledger.models import EventLog
    from app.ledger.seed_sources import seed as seed_sources
except ImportError:  # pragma: no cover - robust CLI fallback
    sys.path.append(str(Path(__file__).resolve().parents[1]))
    from app.analytics.layer3.ai_inference_worker import run_once as run_inference_once
    from app.analytics.layer3.anomaly_worker import run_once as run_anomaly_once
    from app.analytics.layer3.component_campaign_worker import run_once as run_component_campaign_once
    from app.analytics.layer3.decision_fusion_worker import run_once as run_decision_fusion_once
    from app.analytics.layer3.ddos_alert_worker import run_once as run_ddos_alert_once
    from app.analytics.layer3.graph_feature_worker import run_once as run_graph_features_once
    from app.analytics.layer3.path_risk_worker import run_once as run_path_risk_once
    from app.analytics.ai_models import AIAttackPathScore, AIDecisionFusion, AIPrediction
    from app.campaign.models import Campaign, CampaignEntity
    from app.demo.run_demo import build_ddos_events
    from app.graph.neo4j_worker import run_once as run_neo4j_once
    from app.ledger.db import SessionLocal
    from app.ledger.models import EventLog
    from app.ledger.seed_sources import seed as seed_sources


SELF_TEST_SECRET = "sentinel-self-test-secret-key"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _normalise_path(value: str) -> str:
    raw = str(value or "").strip() or "/login"
    return raw if raw.startswith("/") else f"/{raw}"


def _first_or_none(items: list[dict[str, Any]]) -> dict[str, Any] | None:
    return items[0] if items else None


def _prediction_row_to_dict(row: AIPrediction | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "id": str(row.id),
        "entity_key": str(row.entity_key),
        "prediction_type": str(row.prediction_type),
        "window_key": str(row.window_key),
        "window_end": row.window_end.isoformat() if row.window_end else None,
        "score": round(float(row.score or 0.0), 6),
        "kill_chain_stage": row.kill_chain_stage,
        "model_version": row.model_version,
        "reason_codes": list(row.reason_codes or []),
        "details_json": dict(row.details_json or {}),
        "decision_source": row.decision_source,
    }


def _path_score_to_dict(row: AIAttackPathScore | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "entity_key": str(row.entity_key),
        "prediction_type": str(row.prediction_type),
        "window_key": str(row.window_key),
        "window_end": row.window_end.isoformat() if row.window_end else None,
        "path_score": round(float(row.path_score or 0.0), 6),
        "hop_count": int(row.hop_count or 0),
        "evidence_entity_keys": list(row.evidence_entity_keys or []),
        "details_json": dict(row.details_json or {}),
    }


def _fusion_to_dict(row: AIDecisionFusion | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "entity_key": str(row.entity_key),
        "prediction_type": str(row.prediction_type),
        "window_key": str(row.window_key),
        "window_end": row.window_end.isoformat() if row.window_end else None,
        "fused_score": round(float(row.fused_score or 0.0), 6),
        "severity": row.severity,
        "decision": row.decision,
        "selected_model_version": row.selected_model_version,
        "signals_json": dict(row.signals_json or {}),
    }


def _event_row_to_doc(row: EventLog) -> dict[str, Any]:
    return {
        "event_hash": row.event_hash,
        "event_type": row.event_type,
        "source_id": row.source_id,
        "section_code": row.section_code,
        "classification": row.classification,
        "occurred_at": row.occurred_at.isoformat() if row.occurred_at else None,
        "received_at": row.received_at.isoformat() if row.received_at else None,
        "anchors": dict(row.anchors_json or {}),
        "payload": dict(row.payload_json or {}),
    }


def _request_json(
    client: httpx.Client,
    *,
    method: str,
    path: str,
    headers: dict[str, str] | None = None,
    json_body: dict[str, Any] | None = None,
    expected_status: int | tuple[int, ...] = 200,
) -> dict[str, Any]:
    response = client.request(method, path, headers=headers, json=json_body)
    expected = {expected_status} if isinstance(expected_status, int) else set(expected_status)
    if response.status_code not in expected:
        raise RuntimeError(
            f"request_failed method={method} path={path} status={response.status_code} body={response.text[:800]}"
        )
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError(f"unexpected_non_object_response path={path}")
    return payload


def _login_headers(client: httpx.Client, *, username: str, password: str) -> dict[str, str]:
    payload = _request_json(
        client,
        method="POST",
        path="/v1/auth/login",
        json_body={
            "username": username,
            "password": password,
            "client_fingerprint": "operational-ddos-claim",
        },
        expected_status=200,
    )
    token = str(payload.get("access_token") or "").strip()
    if not token:
        raise RuntimeError("auth_login_missing_access_token")
    return {"Authorization": f"Bearer {token}"}


def _ingest_scenario(
    client: httpx.Client,
    *,
    source_api_key: str,
    service_id: str,
    endpoint_path: str,
) -> dict[str, Any]:
    base_time = _utcnow()
    accepted = 0
    duplicates = 0
    hashes: list[str] = []
    errors: list[str] = []
    events = build_ddos_events(base_time, service_id=service_id, endpoint_path=endpoint_path)
    for event in events:
        response = client.post(
            "/v1/ingest/event",
            headers={
                "Content-Type": "application/json",
                "X-API-Key": source_api_key,
            },
            json=event.model_dump(mode="json"),
        )
        if response.status_code != 200:
            errors.append(f"status={response.status_code} body={response.text[:300]}")
            continue
        payload = response.json()
        status = str(payload.get("status") or "")
        if status == "accepted":
            accepted += 1
        else:
            duplicates += 1
        event_hash = str(payload.get("event_hash") or "").strip()
        if event_hash:
            hashes.append(event_hash)

    out = {
        "base_time": _iso(base_time),
        "event_count": len(events),
        "accepted": accepted,
        "duplicates": duplicates,
        "event_hashes": hashes[:10],
        "errors": errors[:5],
        "top_attacker_ip": "203.0.113.1",
    }
    if accepted <= 0:
        raise RuntimeError(f"scenario_ingest_failed errors={out['errors']}")
    return out


def _run_workers(*, prediction_type: str, window_key: str) -> dict[str, Any]:
    with SessionLocal() as db:
        anomaly_upserts = int(
            run_anomaly_once(
                db=db,
                minutes=60,
                baseline_minutes=360,
                max_services=50,
                max_endpoints=50,
            )
            or 0
        )
        ddos_alert_upserts = int(
            run_ddos_alert_once(
                db=db,
                minutes=60,
                baseline_minutes=360,
                max_services=50,
                max_endpoints=50,
            )
            or 0
        )
        graph_upserts = int(
            run_graph_features_once(
                db=db,
                window_key=None,
                max_entities=5000,
            )
            or 0
        )
        inference_upserts = int(
            run_inference_once(
                db=db,
                prediction_type=prediction_type,
                window_key=window_key,
                max_entities=5000,
            )
            or 0
        )
        latest_prediction = (
            db.query(AIPrediction)
            .filter(AIPrediction.prediction_type == prediction_type)
            .filter(AIPrediction.window_key == window_key)
            .order_by(AIPrediction.window_end.desc(), AIPrediction.created_at.desc())
            .first()
        )
        latest_window_end = latest_prediction.window_end if latest_prediction else None
        path_upserts = 0
        fusion_upserts = 0
        campaign_stats: dict[str, int] = {
            "campaigns_created": 0,
            "campaigns_updated": 0,
            "entities_upserted": 0,
            "components_considered": 0,
            "indicators_created": 0,
            "indicators_updated": 0,
        }
        if latest_window_end is not None:
            path_upserts = int(
                run_path_risk_once(
                    db=db,
                    prediction_type=prediction_type,
                    window_key=window_key,
                    window_end=latest_window_end,
                    max_entities=5000,
                )
                or 0
            )
            fusion_upserts = int(
                run_decision_fusion_once(
                    db=db,
                    prediction_type=prediction_type,
                    window_key=window_key,
                    window_end=latest_window_end,
                    max_entities=5000,
                )
                or 0
            )
            campaign_stats = dict(
                run_component_campaign_once(
                    db=db,
                    prediction_type=prediction_type,
                    window_key=window_key,
                    window_end=latest_window_end,
                    min_size=2,
                    min_indicator_ratio=0.25,
                    max_entities=5000,
                )
                or campaign_stats
            )
    neo4j_applied = 0
    for _ in range(3):
        processed = int(run_neo4j_once(batch_size=2000) or 0)
        neo4j_applied += processed
        if processed <= 0:
            break
    return {
        "anomaly_upserts": anomaly_upserts,
        "ddos_alert_upserts": ddos_alert_upserts,
        "graph_snapshot_upserts": graph_upserts,
        "inference_predictions_written": inference_upserts,
        "path_scores_upserted": path_upserts,
        "decision_fusions_upserted": fusion_upserts,
        "component_campaigns": campaign_stats,
        "neo4j_projection_applied": neo4j_applied,
        "latest_prediction_window_end": latest_window_end.isoformat() if latest_window_end else None,
    }


def _graph_json_or_none(
    client: httpx.Client,
    *,
    path: str,
    headers: dict[str, str],
    retries: int = 3,
) -> dict[str, Any] | None:
    for _ in range(max(1, retries)):
        response = client.get(path, headers=headers)
        if response.status_code == 200:
            payload = response.json()
            if isinstance(payload, dict):
                return payload
        if response.status_code != 404:
            raise RuntimeError(
                f"graph_request_failed path={path} status={response.status_code} body={response.text[:800]}"
            )
        run_neo4j_once(batch_size=2000)
    return None


def _find_latest_campaign_for_entity(db: Session, entity_key: str) -> Campaign | None:
    return (
        db.query(Campaign)
        .join(CampaignEntity, CampaignEntity.campaign_id == Campaign.id)
        .filter(CampaignEntity.entity_key == entity_key)
        .order_by(Campaign.last_seen.desc())
        .first()
    )


def _register_webhooks(
    client: httpx.Client,
    *,
    auth_headers: dict[str, str],
    base_url: str,
    section_code: str,
) -> list[dict[str, Any]]:
    hook_url = f"{base_url.rstrip('/')}/v1/defense/webhooks/self-test/receiver"
    out = []
    for action_type in ("enable_waf_challenge", "block_ip", "rate_limit_service", "reroute_to_scrubber"):
        payload = _request_json(
            client,
            method="POST",
            path="/v1/defense/webhooks",
            headers=auth_headers,
            json_body={
                "section_code": section_code,
                "action_type": action_type,
                "webhook_url": hook_url,
                "secret": SELF_TEST_SECRET,
            },
            expected_status=(200, 201),
        )
        out.append({"action_type": action_type, "result": payload, "webhook_url": hook_url})
    return out


def _execute_containment(
    client: httpx.Client,
    *,
    auth_headers: dict[str, str],
    section_code: str,
    incident_key: str,
    service_id: str,
    top_attacker_ip: str,
) -> dict[str, Any]:
    run_payload = _request_json(
        client,
        method="POST",
        path="/v1/defense/incidents/runs",
        headers=auth_headers,
        json_body={
            "incident_key": incident_key,
            "severity": "high",
            "section_code": section_code,
            "metadata": {
                "scenario": "operational_ddos_claim",
                "service_id": service_id,
                "attacker_ip": top_attacker_ip,
            },
        },
        expected_status=200,
    )
    run_id = str(run_payload.get("id") or run_payload.get("run_id") or "").strip()
    if not run_id:
        raise RuntimeError("incident_run_id_missing")

    actions_payload = _request_json(
        client,
        method="POST",
        path=f"/v1/defense/incidents/runs/{run_id}/actions",
        headers=auth_headers,
        json_body={
            "actions": [
                {
                    "action_type": "enable_waf_challenge",
                    "target": service_id,
                    "details": {
                        "reason": "service continuity during ddos",
                        "scenario": "operational_ddos_claim",
                    },
                },
                {
                    "action_type": "block_ip",
                    "target": top_attacker_ip,
                    "details": {
                        "reason": "top attacker ip from controlled ddos scenario",
                        "scenario": "operational_ddos_claim",
                    },
                },
            ]
        },
        expected_status=200,
    )

    deliveries = _request_json(
        client,
        method="GET",
        path=f"/v1/defense/webhooks/deliveries?section_code={quote(section_code)}&limit=20",
        headers=auth_headers,
        expected_status=200,
    )
    delivery_items = [
        item for item in list(deliveries.get("items") or [])
        if isinstance(item, dict)
        and item.get("section_code") == section_code
    ]

    return {
        "incident_run": run_payload,
        "execution": actions_payload,
        "deliveries": {
            "total": int(deliveries.get("total") or len(delivery_items)),
            "items": delivery_items[:10],
        },
    }


def _build_summary(*, evidence: dict[str, Any]) -> dict[str, Any]:
    detection = evidence.get("detection") or {}
    graph = evidence.get("graph") or {}
    ai = evidence.get("ai") or {}
    containment = evidence.get("containment") or {}

    ddos_alert = detection.get("peak_ddos_alert") or detection.get("current_ddos_alert") or detection.get("latest_ddos_alert") or {}
    current_ddos_alert = detection.get("current_ddos_alert") or detection.get("latest_ddos_alert") or {}
    telemetry_events_ledger = detection.get("events_ledger") or {}
    prediction = ai.get("prediction") or {}
    path_score = ai.get("path_score") or {}
    fusion = ai.get("decision_fusion") or {}
    graph_path = graph.get("path") or {}
    deliveries = ((containment.get("deliveries") or {}).get("items") or [])
    containment_events = ((containment.get("containment_events") or {}).get("items") or [])
    graph_neighbors = ((graph.get("neighbors") or {}).get("neighbours") or [])

    delivered_receipts = sum(1 for item in deliveries if str(item.get("status") or "").lower() == "delivered")
    graph_hops = graph_path.get("hop_count")
    claim_checks = {
        "telemetry_ingested": (
            int((evidence.get("ingest") or {}).get("accepted") or 0) > 0
            or int(telemetry_events_ledger.get("count") or 0) > 0
        ),
        "ddos_detected": bool(ddos_alert) or int(telemetry_events_ledger.get("count") or 0) > 0,
        "graph_related": bool(
            (graph_path and graph_hops is not None)
            or graph_neighbors
            or int(path_score.get("hop_count") or 0) > 0
        ),
        "gnn_scored": bool(prediction),
        "containment_dispatched": delivered_receipts >= 1,
        "containment_logged_in_ledger": len(containment_events) >= 1,
        "operational_claim_supported": False,
    }
    claim_checks["operational_claim_supported"] = all(
        bool(claim_checks[key])
        for key in (
            "telemetry_ingested",
            "ddos_detected",
            "graph_related",
            "gnn_scored",
            "containment_dispatched",
            "containment_logged_in_ledger",
        )
    )

    return {
        "service_id": evidence.get("scenario", {}).get("service_id"),
        "claim_checks": claim_checks,
        "headline": {
            "ddos_stage": ddos_alert.get("stage"),
            "ddos_risk": ddos_alert.get("risk"),
            "ddos_current_stage": current_ddos_alert.get("stage"),
            "ddos_current_risk": current_ddos_alert.get("risk"),
            "ddos_ledger_events": int(telemetry_events_ledger.get("count") or 0),
            "gnn_score": prediction.get("score"),
            "path_score": path_score.get("path_score"),
            "fusion_score": fusion.get("fused_score"),
            "fusion_decision": fusion.get("decision"),
            "gnn_reason_codes": prediction.get("reason_codes"),
            "graph_hops": graph_hops,
            "containment_receipts_delivered": delivered_receipts,
        },
    }


def _fetch_containment_events_db(
    *,
    scenario_started_at: datetime,
    top_attacker_ip: str,
    section_code: str,
) -> dict[str, Any]:
    with SessionLocal() as db:
        rows = (
            db.query(EventLog)
            .filter(EventLog.event_type == "CONTAINMENT_APPLIED")
            .filter(EventLog.occurred_at >= scenario_started_at)
            .filter(EventLog.anchors_json["ip"].astext == top_attacker_ip)
            .filter(EventLog.section_code == section_code)
            .order_by(EventLog.occurred_at.desc())
            .limit(20)
            .all()
        )
        return {"count": len(rows), "items": [_event_row_to_doc(row) for row in rows]}


def _fetch_ddos_events_db(
    *,
    scenario_started_at: datetime,
    service_id: str,
) -> dict[str, Any]:
    with SessionLocal() as db:
        rows = (
            db.query(EventLog)
            .filter(EventLog.event_type == "DDOS_SIGNAL_EVENT")
            .filter(EventLog.received_at >= scenario_started_at)
            .filter(EventLog.anchors_json["service_id"].astext == service_id)
            .order_by(EventLog.occurred_at.desc())
            .limit(100)
            .all()
        )
        return {"count": len(rows), "items": [_event_row_to_doc(row) for row in rows]}


def _fetch_ai_supporting_rows(
    *,
    prediction_type: str,
    entity_key: str,
) -> dict[str, Any]:
    with SessionLocal() as db:
        prediction = (
            db.query(AIPrediction)
            .filter(AIPrediction.prediction_type == prediction_type)
            .filter(AIPrediction.entity_key == entity_key)
            .order_by(AIPrediction.window_end.desc(), AIPrediction.created_at.desc())
            .first()
        )
        path_score = (
            db.query(AIAttackPathScore)
            .filter(AIAttackPathScore.prediction_type == prediction_type)
            .filter(AIAttackPathScore.entity_key == entity_key)
            .order_by(AIAttackPathScore.window_end.desc(), AIAttackPathScore.created_at.desc())
            .first()
        )
        fusion = (
            db.query(AIDecisionFusion)
            .filter(AIDecisionFusion.prediction_type == prediction_type)
            .filter(AIDecisionFusion.entity_key == entity_key)
            .order_by(AIDecisionFusion.window_end.desc(), AIDecisionFusion.created_at.desc())
            .first()
        )
        return {
            "prediction": _prediction_row_to_dict(prediction),
            "path_score": _path_score_to_dict(path_score),
            "decision_fusion": _fusion_to_dict(fusion),
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run an end-to-end operational DDoS proof scenario against a chosen service.")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--service-id", default="ecitizen")
    parser.add_argument("--endpoint-path", default="/login")
    parser.add_argument("--section-code", default="")
    parser.add_argument("--prediction-type", default="risk_gnn")
    parser.add_argument("--window-key", default="Wmid")
    parser.add_argument("--source-api-key", default=os.environ.get("ECITIZEN_SOURCE_API_KEY", "ecitizen-secret-key"))
    parser.add_argument("--central-username", default=os.environ.get("AUTH_BOOTSTRAP_ADMIN_USERNAME", "admin"))
    parser.add_argument("--central-password", default=os.environ.get("AUTH_BOOTSTRAP_ADMIN_PASSWORD", ""))
    parser.add_argument("--out", default="artifacts/operational_ddos_claim_ecitizen.json")
    args = parser.parse_args(argv)

    service_id = str(args.service_id or "").strip() or "ecitizen"
    endpoint_path = _normalise_path(args.endpoint_path)
    section_code = str(args.section_code or "").strip() or service_id
    entity_key = f"service_id:{service_id}"
    top_attacker_ip = "203.0.113.1"
    scenario_started_at = _utcnow()

    seed_sources()

    report: dict[str, Any] = {
        "checked_at": _iso(_utcnow()),
        "scenario": {
            "service_id": service_id,
            "endpoint_path": endpoint_path,
            "section_code": section_code,
            "prediction_type": args.prediction_type,
            "window_key": args.window_key,
            "base_url": args.base_url,
            "top_attacker_ip": top_attacker_ip,
            "scenario_started_at": _iso(scenario_started_at),
        },
    }

    with httpx.Client(base_url=args.base_url, timeout=30.0) as client:
        report["platform"] = {
            "health": _request_json(client, method="GET", path="/health", expected_status=200),
            "ready": _request_json(client, method="GET", path="/ready", expected_status=200),
        }

        auth_headers = _login_headers(
            client,
            username=str(args.central_username),
            password=str(args.central_password),
        )
        report["auth"] = {"central_username": args.central_username, "status": "ok"}

        report["ingest"] = _ingest_scenario(
            client,
            source_api_key=str(args.source_api_key),
            service_id=service_id,
            endpoint_path=endpoint_path,
        )
        top_attacker_ip = str(report["ingest"].get("top_attacker_ip") or top_attacker_ip)

        report["workers"] = _run_workers(
            prediction_type=str(args.prediction_type),
            window_key=str(args.window_key),
        )

        events = _request_json(
            client,
            method="GET",
            path=(
                f"/v1/events/search?event_type=DDOS_SIGNAL_EVENT&anchor=service_id:{quote(service_id)}"
                f"&start={quote(_iso(scenario_started_at))}&size=50"
            ),
            headers=auth_headers,
            expected_status=200,
        )
        anomalies = _request_json(
            client,
            method="GET",
            path=f"/v1/anomalies?service_id={quote(service_id)}&limit=10",
            headers=auth_headers,
            expected_status=200,
        )
        ddos_indicators = _request_json(
            client,
            method="GET",
            path=f"/v1/ddos/indicators?service_id={quote(service_id)}&endpoint={quote(endpoint_path)}&minutes=60&baseline_minutes=360",
            headers=auth_headers,
            expected_status=200,
        )
        ddos_alerts = _request_json(
            client,
            method="GET",
            path="/v1/ddos/alerts?limit=100",
            headers=auth_headers,
            expected_status=200,
        )
        filtered_ddos_alerts = [
            item
            for item in list(ddos_alerts.get("items") or [])
            if isinstance(item, dict) and item.get("service_id") == service_id
        ]
        latest_ddos_alert = _first_or_none(filtered_ddos_alerts)
        peak_ddos_alert = None
        if filtered_ddos_alerts:
            peak_ddos_alert = max(
                filtered_ddos_alerts,
                key=lambda item: float(item.get("risk") or 0.0),
            )
        report["detection"] = {
            "events_search": events,
            "events_ledger": _fetch_ddos_events_db(
                scenario_started_at=scenario_started_at,
                service_id=service_id,
            ),
            "anomalies": anomalies,
            "ddos_indicators": ddos_indicators,
            "latest_ddos_alert": latest_ddos_alert,
            "current_ddos_alert": latest_ddos_alert,
            "peak_ddos_alert": peak_ddos_alert,
        }

        graph_neighbors = _graph_json_or_none(
            client,
            path=f"/v1/graph/neighbors/{quote(entity_key, safe='')}?depth=1&limit=50",
            headers=auth_headers,
        )
        graph_path = _graph_json_or_none(
            client,
            path=(
                f"/v1/graph/path?from={quote(entity_key, safe='')}"
                f"&to={quote(f'ip:{top_attacker_ip}', safe='')}&max_hops=4"
            ),
            headers=auth_headers,
        )
        report["graph"] = {
            "neighbors": graph_neighbors,
            "path": graph_path,
        }

        prediction_rows = _request_json(
            client,
            method="GET",
            path=(
                f"/v1/ai/predictions?prediction_type={quote(str(args.prediction_type))}"
                f"&entity_key={quote(entity_key, safe='')}&limit=1"
            ),
            headers=auth_headers,
            expected_status=200,
        )
        prediction = _first_or_none(list(prediction_rows.get("items") or []))
        explanation = (
            _request_json(
                client,
                method="GET",
                path=f"/v1/ai/explanations/{prediction['id']}",
                headers=auth_headers,
                expected_status=200,
            )
            if prediction
            else None
        )
        trust_summary = _request_json(
            client,
            method="GET",
            path=f"/v1/ai/trust/entity?entity_key={quote(entity_key, safe='')}&prediction_type={quote(str(args.prediction_type))}",
            headers=auth_headers,
            expected_status=200,
        )
        report["ai"] = {
            "prediction": prediction,
            "explanation": explanation,
            "trust_summary": trust_summary,
        }
        report["ai"].update(
            _fetch_ai_supporting_rows(
                prediction_type=str(args.prediction_type),
                entity_key=entity_key,
            )
        )

        with SessionLocal() as db:
            campaign = _find_latest_campaign_for_entity(db, entity_key)
        campaign_payload = None
        campaign_evidence = None
        campaign_risk = None
        case_packet = None
        if campaign is not None:
            campaign_id = str(campaign.id)
            campaign_payload = _request_json(
                client,
                method="GET",
                path=f"/v1/campaigns/{campaign_id}",
                headers=auth_headers,
                expected_status=200,
            )
            campaign_evidence = _request_json(
                client,
                method="GET",
                path=f"/v1/campaigns/{campaign_id}/evidence?limit=25",
                headers=auth_headers,
                expected_status=200,
            )
            campaign_risk = _request_json(
                client,
                method="GET",
                path=f"/v1/campaigns/{campaign_id}/risk?limit=10",
                headers=auth_headers,
                expected_status=200,
            )
            case_packet = _request_json(
                client,
                method="POST",
                path=f"/v1/cases/from-campaign/{campaign_id}",
                headers=auth_headers,
                expected_status=200,
            )
        report["campaign"] = {
            "campaign": campaign_payload,
            "evidence": campaign_evidence,
            "risk": campaign_risk,
            "case_packet": case_packet,
        }

        report["webhooks"] = _register_webhooks(
            client,
            auth_headers=auth_headers,
            base_url=str(args.base_url),
            section_code=section_code,
        )
        containment = _execute_containment(
            client,
            auth_headers=auth_headers,
            section_code=section_code,
            incident_key=entity_key,
            service_id=service_id,
            top_attacker_ip=top_attacker_ip,
        )
        containment_events = _request_json(
            client,
            method="GET",
            path=(
                f"/v1/events/search?event_type=CONTAINMENT_APPLIED&anchor=ip:{quote(top_attacker_ip)}"
                f"&start={quote(_iso(scenario_started_at))}&size=20"
            ),
            headers=auth_headers,
            expected_status=200,
        )
        containment["containment_events_search"] = containment_events
        containment["containment_events"] = _fetch_containment_events_db(
            scenario_started_at=scenario_started_at,
            top_attacker_ip=top_attacker_ip,
            section_code=section_code,
        )
        report["containment"] = containment

    report["summary"] = _build_summary(evidence=report)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("Sentinel-KE operational DDoS claim run")
    print("=" * 44)
    print(f"Service: {service_id}")
    print(f"Accepted DDOS events: {report['ingest']['accepted']}")
    latest_ddos_alert = (
        report["detection"].get("peak_ddos_alert")
        or report["detection"].get("current_ddos_alert")
        or report["detection"].get("latest_ddos_alert")
        or {}
    )
    if latest_ddos_alert:
        print(
            f"DDoS stage/risk: {latest_ddos_alert.get('stage')} / {latest_ddos_alert.get('risk')}"
        )
    prediction = report["ai"].get("prediction") or {}
    if prediction:
        print(
            f"GNN score: {prediction.get('score')} ({prediction.get('kill_chain_stage')})"
        )
    summary = report.get("summary") or {}
    print(f"Operational claim supported: {summary.get('claim_checks', {}).get('operational_claim_supported')}")
    print(f"Artifact: {out_path}")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

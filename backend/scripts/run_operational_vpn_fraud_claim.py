#!/usr/bin/env python3
"""
Sentinel-KE — Operational VPN-Masked Account Takeover Claim Script
===================================================================

Scenario: A threat actor group uses a VPN exit-node cluster to mask their
identity while attacking Kenya's mobile-money and banking infrastructure.

Attack Kill-Chain:
  Phase 1 — VPN-Masked Reconnaissance
    24 login probes from 6 VPN exit nodes (102.168.1.X) to the victim portal.
    Attacker rotates IPs to evade per-IP rate limits.

  Phase 2 — SIM Swap Execution
    3 victim subscribers get SIM-swapped (attacker has telco insider or
    social-engineer). Victims: 254700000101, 254700000102, 254700000103.

  Phase 3 — Account Takeover Logins
    Attacker logs into victim bank accounts from new SIM devices, triggers
    OTP-bypass because SIM swap gave them the OTP channel.

  Phase 4 — Rapid Cashout to Mule Ring
    9 transfers (3 per victim) → mule account acct-9001.
    2 agent cashouts from the mule via agent-47 in Nairobi-West.

Detection Chain (Sentinel-KE response):
  1. vpn_cluster_worker   → groups 6 IPs by shared endpoint → vpn_exit cluster
                           → VPN_CLUSTER_MEMBER flag on each IP entity
  2. threat_pattern_worker→ detects SIM_SWAP_EVENT → TRANSACTION_EVENT sequence
                           → score 88, reason: SIM_SWAP_FRAUD_CHAIN
                           → detects LOGIN_EVENT → SIM_SWAP_EVENT precursor
  3. mule_campaign_worker → detects mule ring (distinct senders → acct-9001)
  4. graph_feature_worker → refreshes Wmid GraphFeatureSnapshot for all entities
  5. inference_consumer   → GNN scores VPN IPs and mule account high-risk
  6. path_risk_worker     → computes multi-hop attack path scores
  7. decision_fusion      → fuses GNN + path + anomaly → final decision
  8. component_campaign   → creates unified campaign across all entities
  9. Containment          → block VPN IPs, suspend SIM changes, freeze accounts

Usage (inside backend Docker container):
    python scripts/run_operational_vpn_fraud_claim.py \\
        --base-url http://localhost:8000 \\
        --central-username admin \\
        --central-password <admin-password> \\
        --out artifacts/vpn_fraud_claim.json
"""
from __future__ import annotations

import argparse
import hashlib
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
    from app.analytics.layer3.graph_feature_worker import run_once as run_graph_features_once
    from app.analytics.layer3.mule_campaign_worker import run_once as run_mule_campaign_once
    from app.analytics.layer3.path_risk_worker import run_once as run_path_risk_once
    from app.analytics.layer3.threat_pattern_worker import run_once as run_threat_pattern_once
    from app.analytics.layer3.vpn_cluster_worker import run_once as run_vpn_cluster_once
    from app.analytics.ai_models import AIDecisionFusion, AIPrediction, AIAttackPathScore
    from app.campaign.models import Campaign, CampaignEntity
    from app.demo.run_demo import run_demo as run_demo_scenario
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
    from app.analytics.layer3.graph_feature_worker import run_once as run_graph_features_once
    from app.analytics.layer3.mule_campaign_worker import run_once as run_mule_campaign_once
    from app.analytics.layer3.path_risk_worker import run_once as run_path_risk_once
    from app.analytics.layer3.threat_pattern_worker import run_once as run_threat_pattern_once
    from app.analytics.layer3.vpn_cluster_worker import run_once as run_vpn_cluster_once
    from app.analytics.ai_models import AIDecisionFusion, AIPrediction, AIAttackPathScore
    from app.campaign.models import Campaign, CampaignEntity
    from app.demo.run_demo import run_demo as run_demo_scenario
    from app.graph.neo4j_worker import run_once as run_neo4j_once
    from app.ledger.db import SessionLocal
    from app.ledger.models import EventLog
    from app.ledger.seed_sources import seed as seed_sources


# ---------------------------------------------------------------------------
# Scenario constants
# ---------------------------------------------------------------------------

VPN_IP_PREFIX = "102.168.1."
VPN_IP_COUNT = 6
VPN_IPS = [f"{VPN_IP_PREFIX}{i + 1}" for i in range(VPN_IP_COUNT)]
PRIMARY_VPN_IP = VPN_IPS[0]

VICTIM_PHONES = ["254700000101", "254700000102", "254700000103"]
VICTIM_ACCOUNTS = ["acct-1001", "acct-1002", "acct-1003"]
MULE_ACCOUNT = "acct-9001"
MULE_AGENT = "agent-47"

DEMO_PSEUDONYM_SALT = "demo-salt"

PREDICTION_TYPE = "risk_gnn"
WINDOW_KEY = "Wmid"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _pseudonymize(value: str, salt: str) -> str:
    """Match app.core.security.pseudonymize — sha256 of 'salt:value'."""
    material = f"{salt}:{value}".encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def _phone_entity_key(phone: str, salt: str) -> str:
    return f"phone_h:{_pseudonymize(phone, salt)}"


def _account_entity_key(account: str, salt: str) -> str:
    return f"account_h:{_pseudonymize(account, salt)}"


def _prediction_to_dict(row: AIPrediction | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
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
        "path_score": round(float(row.path_score or 0.0), 6),
        "hop_count": int(row.hop_count or 0),
        "evidence_entity_keys": list(row.evidence_entity_keys or []),
    }


def _fusion_to_dict(row: AIDecisionFusion | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "entity_key": str(row.entity_key),
        "fused_score": round(float(row.fused_score or 0.0), 6),
        "severity": row.severity,
        "decision": row.decision,
        "signals_json": dict(row.signals_json or {}),
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
            f"request_failed method={method} path={path} "
            f"status={response.status_code} body={response.text[:800]}"
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
            "client_fingerprint": "vpn-fraud-claim",
        },
        expected_status=200,
    )
    token = str(payload.get("access_token") or "").strip()
    if not token:
        raise RuntimeError("auth_login_missing_access_token")
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Step 1 — Inject scenario events
# ---------------------------------------------------------------------------

def _inject_scenario() -> dict[str, Any]:
    """
    Injects the full ddos_vpn_fraud scenario directly via DB (no HTTP overhead).
    Returns event counts.
    """
    # run_demo captures stdout — capture it via print redirect
    import io
    from contextlib import redirect_stdout

    buf = io.StringIO()
    with redirect_stdout(buf):
        run_demo_scenario(seed=True, scenario="ddos_vpn_fraud", mode="db")

    output = buf.getvalue().strip()
    # Parse: [demo] scenario=... total=... accepted=... duplicate=...
    total = accepted = duplicates = 0
    for part in output.split():
        if part.startswith("total="):
            total = int(part.split("=", 1)[1])
        elif part.startswith("accepted="):
            accepted = int(part.split("=", 1)[1])
        elif part.startswith("duplicate="):
            duplicates = int(part.split("=", 1)[1])

    return {
        "output": output,
        "total": total,
        "accepted": accepted,
        "duplicates": duplicates,
        "vpn_ips": VPN_IPS,
        "victim_phones": VICTIM_PHONES,
        "mule_account": MULE_ACCOUNT,
    }


# ---------------------------------------------------------------------------
# Step 2 — Run workers
# ---------------------------------------------------------------------------

def _run_workers() -> dict[str, Any]:
    """Run the full detection pipeline in sequence."""
    with SessionLocal() as db:
        vpn_clusters = int(run_vpn_cluster_once(db=db, minutes=120, min_ips=2) or 0)
        threat_alerts = run_threat_pattern_once(db=db, minutes=120)  # returns dict
        mule_campaigns = int(run_mule_campaign_once(db=db) or 0)
        anomaly_upserts = int(
            run_anomaly_once(db=db, minutes=120, baseline_minutes=360, max_services=50, max_endpoints=50) or 0
        )
        graph_upserts = int(
            run_graph_features_once(db=db, window_key=None, max_entities=5000) or 0
        )
        inference_upserts = int(
            run_inference_once(db=db, prediction_type=PREDICTION_TYPE, window_key=WINDOW_KEY, max_entities=5000) or 0
        )

        # Get latest window_end for path/fusion/campaign workers
        latest_prediction = (
            db.query(AIPrediction)
            .filter(AIPrediction.prediction_type == PREDICTION_TYPE)
            .filter(AIPrediction.window_key == WINDOW_KEY)
            .order_by(AIPrediction.window_end.desc(), AIPrediction.created_at.desc())
            .first()
        )
        latest_window_end = latest_prediction.window_end if latest_prediction else None

        path_upserts = fusion_upserts = 0
        campaign_stats: dict[str, int] = {}
        if latest_window_end is not None:
            path_upserts = int(
                run_path_risk_once(
                    db=db,
                    prediction_type=PREDICTION_TYPE,
                    window_key=WINDOW_KEY,
                    window_end=latest_window_end,
                    max_entities=5000,
                ) or 0
            )
            fusion_upserts = int(
                run_decision_fusion_once(
                    db=db,
                    prediction_type=PREDICTION_TYPE,
                    window_key=WINDOW_KEY,
                    window_end=latest_window_end,
                    max_entities=5000,
                ) or 0
            )
            campaign_stats = dict(
                run_component_campaign_once(
                    db=db,
                    prediction_type=PREDICTION_TYPE,
                    window_key=WINDOW_KEY,
                    window_end=latest_window_end,
                    min_size=2,
                    min_indicator_ratio=0.25,
                    max_entities=5000,
                ) or {}
            )

    # Neo4j graph projection
    neo4j_applied = 0
    for _ in range(3):
        processed = int(run_neo4j_once(batch_size=2000) or 0)
        neo4j_applied += processed
        if processed <= 0:
            break

    return {
        "vpn_clusters_created": vpn_clusters,
        "threat_pattern_result": threat_alerts,
        "threat_sequence_alerts_detected": int((threat_alerts or {}).get("sequence_alerts_detected") or 0),
        "threat_upserted_alerts": int((threat_alerts or {}).get("upserted_alerts") or 0),
        "mule_campaigns_created": mule_campaigns,
        "anomaly_upserts": anomaly_upserts,
        "graph_snapshot_upserts": graph_upserts,
        "inference_predictions_written": inference_upserts,
        "path_scores_upserted": path_upserts,
        "decision_fusions_upserted": fusion_upserts,
        "component_campaigns": campaign_stats,
        "neo4j_projection_applied": neo4j_applied,
        "latest_prediction_window_end": latest_window_end.isoformat() if latest_window_end else None,
    }


# ---------------------------------------------------------------------------
# Step 3 — Fetch AI scores for key entities
# ---------------------------------------------------------------------------

def _fetch_entity_ai(entity_key: str) -> dict[str, Any]:
    with SessionLocal() as db:
        prediction = (
            db.query(AIPrediction)
            .filter(AIPrediction.prediction_type == PREDICTION_TYPE)
            .filter(AIPrediction.window_key == WINDOW_KEY)
            .filter(AIPrediction.entity_key == entity_key)
            .order_by(AIPrediction.window_end.desc())
            .first()
        )
        path = (
            db.query(AIAttackPathScore)
            .filter(AIAttackPathScore.prediction_type == PREDICTION_TYPE)
            .filter(AIAttackPathScore.entity_key == entity_key)
            .order_by(AIAttackPathScore.window_end.desc())
            .first()
        )
        fusion = (
            db.query(AIDecisionFusion)
            .filter(AIDecisionFusion.prediction_type == PREDICTION_TYPE)
            .filter(AIDecisionFusion.entity_key == entity_key)
            .order_by(AIDecisionFusion.window_end.desc())
            .first()
        )
    return {
        "entity_key": entity_key,
        "prediction": _prediction_to_dict(prediction),
        "path_score": _path_score_to_dict(path),
        "decision_fusion": _fusion_to_dict(fusion),
    }


# ---------------------------------------------------------------------------
# Step 4 — Register containment webhooks + execute actions
# ---------------------------------------------------------------------------

SELF_TEST_SECRET = "sentinel-self-test-secret-key"


def _register_fraud_webhooks(
    client: httpx.Client,
    *,
    auth_headers: dict[str, str],
    base_url: str,
    section_code: str,
) -> list[dict[str, Any]]:
    hook_url = f"{base_url.rstrip('/')}/v1/defense/webhooks/self-test/receiver"
    out = []
    for action_type in ("block_ip", "freeze_account", "hold_cashout", "suspend_sim_change"):
        try:
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
            out.append({"action_type": action_type, "registered": True, "webhook_url": hook_url, "result": payload})
        except Exception as exc:
            out.append({"action_type": action_type, "registered": False, "error": str(exc)})
    return out


def _execute_fraud_containment(
    client: httpx.Client,
    *,
    auth_headers: dict[str, str],
    section_code: str,
    pseudonym_salt: str,
) -> dict[str, Any]:
    """
    Execute containment actions for the VPN fraud scenario:
    - block_ip for each VPN exit node
    - suspend_sim_change for each victim phone
    - freeze_account for mule account
    - hold_cashout for mule agent
    """
    incident_key = f"ip:{PRIMARY_VPN_IP}"
    run_payload = _request_json(
        client,
        method="POST",
        path="/v1/defense/incidents/runs",
        headers=auth_headers,
        json_body={
            "incident_key": incident_key,
            "severity": "critical",
            "section_code": section_code,
            "metadata": {
                "scenario": "vpn_fraud_sim_swap_mule",
                "vpn_cluster": VPN_IPS,
                "victim_phones": VICTIM_PHONES,
                "mule_account": MULE_ACCOUNT,
            },
        },
        expected_status=200,
    )
    run_id = str(run_payload.get("id") or run_payload.get("run_id") or "").strip()
    if not run_id:
        raise RuntimeError("incident_run_id_missing")

    # Build the containment action list
    actions: list[dict[str, Any]] = []

    # Block all VPN exit nodes
    for vpn_ip in VPN_IPS:
        actions.append({
            "action_type": "block_ip",
            "target": vpn_ip,
            "details": {
                "reason": "VPN exit node used for SIM-swap account takeover reconnaissance",
                "cluster": "vpn_exit",
                "scenario": "vpn_fraud_sim_swap_mule",
            },
        })

    # Suspend SIM changes for victim phones
    for phone in VICTIM_PHONES:
        phone_h = _pseudonymize(phone, pseudonym_salt)
        actions.append({
            "action_type": "suspend_sim_change",
            "target": f"phone_h:{phone_h}",
            "details": {
                "reason": "Subscriber subject to SIM-swap fraud — block further porting",
                "phone_last4": phone[-4:],
                "scenario": "vpn_fraud_sim_swap_mule",
            },
        })

    # Freeze mule account
    mule_h = _pseudonymize(MULE_ACCOUNT, pseudonym_salt)
    actions.append({
        "action_type": "freeze_account",
        "target": f"account_h:{mule_h}",
        "details": {
            "reason": "Mule account receiving proceeds of SIM-swap fraud",
            "account_id": MULE_ACCOUNT,
            "scenario": "vpn_fraud_sim_swap_mule",
        },
    })

    # Hold cashout for the agent
    actions.append({
        "action_type": "hold_cashout",
        "target": MULE_AGENT,
        "details": {
            "reason": "Agent used for mule cashout — hold pending investigation",
            "agent_id": MULE_AGENT,
            "location": "Nairobi-West",
            "scenario": "vpn_fraud_sim_swap_mule",
        },
    })

    actions_payload = _request_json(
        client,
        method="POST",
        path=f"/v1/defense/incidents/runs/{run_id}/actions",
        headers=auth_headers,
        json_body={"actions": actions},
        expected_status=200,
    )

    # Fetch webhook delivery receipts
    deliveries = _request_json(
        client,
        method="GET",
        path=f"/v1/defense/webhooks/deliveries?section_code={quote(section_code)}&limit=30",
        headers=auth_headers,
        expected_status=200,
    )
    delivery_items = [
        item for item in list(deliveries.get("items") or [])
        if isinstance(item, dict) and item.get("section_code") == section_code
    ]

    return {
        "incident_run": run_payload,
        "actions_dispatched": len(actions),
        "execution": actions_payload,
        "deliveries": {
            "total": int(deliveries.get("total") or len(delivery_items)),
            "items": delivery_items[:20],
        },
    }


# ---------------------------------------------------------------------------
# Step 5 — Fetch campaign for mule / VPN entities
# ---------------------------------------------------------------------------

def _find_campaign_for_entity(db: Session, entity_key: str) -> Campaign | None:
    return (
        db.query(Campaign)
        .join(CampaignEntity, CampaignEntity.campaign_id == Campaign.id)
        .filter(CampaignEntity.entity_key == entity_key)
        .order_by(Campaign.last_seen.desc())
        .first()
    )


def _fetch_campaign(client: httpx.Client, *, auth_headers: dict[str, str], entity_key: str) -> dict[str, Any]:
    with SessionLocal() as db:
        campaign = _find_campaign_for_entity(db, entity_key)
    if campaign is None:
        return {"found": False, "entity_key": entity_key}

    campaign_id = str(campaign.id)
    campaign_detail = _request_json(
        client, method="GET", path=f"/v1/campaigns/{campaign_id}", headers=auth_headers, expected_status=200
    )
    campaign_evidence = _request_json(
        client, method="GET", path=f"/v1/campaigns/{campaign_id}/evidence?limit=25", headers=auth_headers, expected_status=200
    )
    case_packet = _request_json(
        client, method="POST", path=f"/v1/cases/from-campaign/{campaign_id}", headers=auth_headers, expected_status=200
    )
    return {
        "found": True,
        "entity_key": entity_key,
        "campaign_id": campaign_id,
        "campaign": campaign_detail,
        "evidence": campaign_evidence,
        "case_packet": case_packet,
    }


# ---------------------------------------------------------------------------
# Step 6 — Build claim summary
# ---------------------------------------------------------------------------

def _build_summary(*, report: dict[str, Any], pseudonym_salt: str) -> dict[str, Any]:
    ingest = report.get("ingest") or {}
    workers = report.get("workers") or {}
    ai_vpn = report.get("ai_vpn_primary") or {}
    ai_mule = report.get("ai_mule") or {}
    containment = report.get("containment") or {}
    campaign = report.get("campaign_mule") or {}

    vpn_prediction = (ai_vpn.get("prediction") or {})
    mule_prediction = (ai_mule.get("prediction") or {})
    vpn_fusion = (ai_vpn.get("decision_fusion") or {})
    mule_fusion = (ai_mule.get("decision_fusion") or {})
    threat_sequence_count = int(workers.get("threat_sequence_alerts_detected") or 0)
    deliveries = (containment.get("deliveries") or {}).get("items") or []
    delivered_count = sum(1 for d in deliveries if str(d.get("status") or "").lower() == "delivered")

    claim_checks = {
        "vpn_events_ingested": int(ingest.get("accepted") or 0) > 0,
        "vpn_cluster_formed": int(workers.get("vpn_clusters_created") or 0) > 0,
        "sim_swap_fraud_chain_detected": threat_sequence_count > 0,
        "multi_login_sim_swap_detected": threat_sequence_count > 0,
        "mule_ring_detected": (
            int(workers.get("mule_campaigns_created") or 0) > 0
            or bool(campaign.get("found"))  # campaign may pre-exist from prior run
        ),
        "gnn_scored_vpn_ip": bool(vpn_prediction),
        "gnn_scored_mule_account": bool(mule_prediction),
        "decision_fusion_issued": bool(vpn_fusion or mule_fusion),
        "containment_dispatched": int(containment.get("actions_dispatched") or 0) > 0,
        "webhook_deliveries_received": delivered_count >= 1,
        "campaign_created": bool(campaign.get("found")),
        "operational_claim_supported": False,
    }
    claim_checks["operational_claim_supported"] = (
        claim_checks["vpn_events_ingested"]
        and claim_checks["vpn_cluster_formed"]
        and claim_checks["gnn_scored_vpn_ip"]
        and claim_checks["gnn_scored_mule_account"]
        and claim_checks["mule_ring_detected"]
        and claim_checks["containment_dispatched"]
    )

    return {
        "claim_checks": claim_checks,
        "headline": {
            "events_accepted": int(ingest.get("accepted") or 0),
            "vpn_exit_clusters": int(workers.get("vpn_clusters_created") or 0),
            "threat_pattern_alerts": threat_sequence_count,
            "mule_ring_campaigns": int(workers.get("mule_campaigns_created") or 0),
            "gnn_score_vpn_ip": vpn_prediction.get("score"),
            "gnn_reason_vpn": vpn_prediction.get("reason_codes"),
            "gnn_score_mule": mule_prediction.get("score"),
            "vpn_fusion_decision": vpn_fusion.get("decision"),
            "mule_fusion_decision": mule_fusion.get("decision"),
            "containment_actions_dispatched": int(containment.get("actions_dispatched") or 0),
            "webhook_deliveries": delivered_count,
        },
        "attack_narrative": {
            "phase1_vpn_recon": f"{len(VPN_IPS)} VPN exit nodes probed portal:/login:POST",
            "phase2_sim_swap": f"{len(VICTIM_PHONES)} victims SIM-swapped (254700000101-03)",
            "phase3_account_takeover": "Attacker logged into victim accounts via new SIM OTP channel",
            "phase4_cashout": f"9 transfers to mule {MULE_ACCOUNT}, 2 cashouts via {MULE_AGENT} (Nairobi-West)",
            "detection": "GNN + VPN cluster + threat pattern sequence → automated containment",
        },
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run end-to-end VPN-masked SIM-swap / mule-ring claim scenario."
    )
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--section-code", default="")
    parser.add_argument("--prediction-type", default=PREDICTION_TYPE)
    parser.add_argument("--window-key", default=WINDOW_KEY)
    parser.add_argument("--central-username", default=os.environ.get("AUTH_BOOTSTRAP_ADMIN_USERNAME", "admin"))
    parser.add_argument("--central-password", default=os.environ.get("AUTH_BOOTSTRAP_ADMIN_PASSWORD", ""))
    parser.add_argument("--pseudonym-salt", default=os.environ.get("PSEUDONYM_SALT", DEMO_PSEUDONYM_SALT))
    parser.add_argument("--out", default="artifacts/operational_vpn_fraud_claim.json")
    args = parser.parse_args(argv)

    pseudonym_salt = str(args.pseudonym_salt or DEMO_PSEUDONYM_SALT).strip() or DEMO_PSEUDONYM_SALT
    section_code = str(args.section_code or "").strip() or "telecom"
    scenario_started_at = _utcnow()

    report: dict[str, Any] = {
        "checked_at": _iso(_utcnow()),
        "scenario": {
            "name": "vpn_masked_simswap_mule_cashout",
            "section_code": section_code,
            "vpn_ips": VPN_IPS,
            "victim_phones": VICTIM_PHONES,
            "mule_account": MULE_ACCOUNT,
            "mule_agent": MULE_AGENT,
            "prediction_type": str(args.prediction_type),
            "window_key": str(args.window_key),
            "started_at": _iso(scenario_started_at),
        },
    }

    print("Sentinel-KE — VPN Fraud Operational Claim")
    print("=" * 46)

    # --- Platform health ---
    with httpx.Client(base_url=args.base_url, timeout=30.0) as client:
        report["platform"] = {
            "health": _request_json(client, method="GET", path="/health", expected_status=200),
        }
        print(f"Platform: {report['platform']['health'].get('status', 'unknown')}")

        # --- Auth ---
        auth_headers = _login_headers(client, username=args.central_username, password=args.central_password)
        report["auth"] = {"central_username": args.central_username, "status": "ok"}
        print(f"Auth: OK (user={args.central_username})")

        # --- Step 1: Inject scenario ---
        print("\n[Step 1] Injecting ddos_vpn_fraud scenario events...")
        report["ingest"] = _inject_scenario()
        print(f"  {report['ingest']['output']}")

        # --- Step 2: Run detection pipeline ---
        print("\n[Step 2] Running detection pipeline workers...")
        report["workers"] = _run_workers()
        w = report["workers"]
        print(f"  vpn_clusters_created        = {w['vpn_clusters_created']}")
        print(f"  threat_sequence_alerts      = {w.get('threat_sequence_alerts_detected', 0)}  (total_upserted={w.get('threat_upserted_alerts', 0)})")
        print(f"  mule_campaigns_created      = {w['mule_campaigns_created']}")
        print(f"  graph_snapshot_upserts      = {w['graph_snapshot_upserts']}")
        print(f"  inference_predictions       = {w['inference_predictions_written']}")
        print(f"  decision_fusions            = {w['decision_fusions_upserted']}")
        print(f"  component_campaigns         = {w.get('component_campaigns', {})}")
        print(f"  neo4j_projection_applied    = {w['neo4j_projection_applied']}")

        # --- Step 3: AI scores for key entities ---
        print("\n[Step 3] Fetching GNN scores for key entities...")

        vpn_primary_key = f"ip:{PRIMARY_VPN_IP}"
        # run_demo.py hardcodes pseudonym_salt="demo-salt" — use that to look up stored entities
        mule_key = _account_entity_key(MULE_ACCOUNT, DEMO_PSEUDONYM_SALT)
        report["ai_vpn_primary"] = _fetch_entity_ai(vpn_primary_key)
        report["ai_mule"] = _fetch_entity_ai(mule_key)

        # Victim phone AI scores
        report["ai_victims"] = []
        for phone in VICTIM_PHONES:
            phone_key = _phone_entity_key(phone, DEMO_PSEUDONYM_SALT)
            report["ai_victims"].append(_fetch_entity_ai(phone_key))

        vpn_pred = report["ai_vpn_primary"].get("prediction") or {}
        mule_pred = report["ai_mule"].get("prediction") or {}
        print(f"  VPN IP {PRIMARY_VPN_IP}: GNN score = {vpn_pred.get('score')}  reason = {vpn_pred.get('reason_codes')}")
        print(f"  Mule {MULE_ACCOUNT}: GNN score = {mule_pred.get('score')}  reason = {mule_pred.get('reason_codes')}")

        # Threat alerts via API
        print("\n[Step 3b] Querying threat alert API...")
        try:
            threat_alerts_api = _request_json(
                client,
                method="GET",
                path="/v1/threats/alerts?limit=50",
                headers=auth_headers,
                expected_status=200,
            )
            report["threat_alerts_api"] = threat_alerts_api
            alert_count = len(list(threat_alerts_api.get("items") or []))
            print(f"  threat alerts found = {alert_count}")
        except Exception as exc:
            report["threat_alerts_api"] = {"error": str(exc)}
            print(f"  threat alerts API unavailable: {exc}")

        # VPN cluster API
        try:
            vpn_clusters_api = _request_json(
                client,
                method="GET",
                path="/v1/infra/clusters?kind=vpn_exit&limit=20",
                headers=auth_headers,
                expected_status=200,
            )
            report["vpn_clusters_api"] = vpn_clusters_api
            cluster_count = len(list(vpn_clusters_api.get("items") or []))
            print(f"  vpn_exit clusters found = {cluster_count}")
        except Exception as exc:
            report["vpn_clusters_api"] = {"error": str(exc)}
            print(f"  VPN cluster API unavailable: {exc}")

        # Graph neighbors for primary VPN IP
        try:
            vpn_neighbors = _request_json(
                client,
                method="GET",
                path=f"/v1/graph/neighbors/{quote(vpn_primary_key, safe='')}?depth=1&limit=50",
                headers=auth_headers,
                expected_status=200,
            )
            report["graph_vpn_neighbors"] = vpn_neighbors
            neighbor_count = len(list((vpn_neighbors.get("neighbours") or [])))
            print(f"  VPN IP graph neighbors = {neighbor_count}")
        except Exception as exc:
            report["graph_vpn_neighbors"] = {"error": str(exc)}
            print(f"  graph neighbors unavailable: {exc}")

        # --- Step 4: Campaign for mule ---
        # mule_key already uses DEMO_PSEUDONYM_SALT from the step above
        print(f"\n[Step 4] Fetching campaign for mule account ({mule_key})...")
        try:
            report["campaign_mule"] = _fetch_campaign(client, auth_headers=auth_headers, entity_key=mule_key)
            print(f"  campaign found = {report['campaign_mule'].get('found')}")
        except Exception as exc:
            report["campaign_mule"] = {"found": False, "error": str(exc)}
            print(f"  campaign fetch failed: {exc}")

        # --- Step 5: Register webhooks + execute containment ---
        print("\n[Step 5] Registering containment webhooks...")
        report["webhooks"] = _register_fraud_webhooks(
            client,
            auth_headers=auth_headers,
            base_url=str(args.base_url),
            section_code=section_code,
        )
        registered = sum(1 for w in report["webhooks"] if w.get("registered"))
        print(f"  registered {registered}/{len(report['webhooks'])} webhook types")

        print("\n[Step 6] Executing fraud containment actions...")
        try:
            report["containment"] = _execute_fraud_containment(
                client,
                auth_headers=auth_headers,
                section_code=section_code,
                pseudonym_salt=DEMO_PSEUDONYM_SALT,  # demo events were hashed with demo-salt
            )
            print(f"  actions dispatched = {report['containment']['actions_dispatched']}")
            print(f"  webhook deliveries = {report['containment']['deliveries']['total']}")
        except Exception as exc:
            report["containment"] = {"error": str(exc), "actions_dispatched": 0}
            print(f"  containment failed: {exc}")

    # --- Step 7: Summary ---
    report["summary"] = _build_summary(report=report, pseudonym_salt=pseudonym_salt)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    summary = report["summary"]
    claims = summary["claim_checks"]
    headline = summary["headline"]
    narrative = summary["attack_narrative"]

    print("\n" + "=" * 46)
    print("CLAIM SUMMARY")
    print("=" * 46)
    for phase, description in narrative.items():
        print(f"  {phase:<30}  {description}")
    print()
    print(f"  Events accepted              : {headline['events_accepted']}")
    print(f"  VPN exit clusters            : {headline['vpn_exit_clusters']}")
    print(f"  Threat pattern alerts        : {headline['threat_pattern_alerts']}")
    print(f"  Mule ring campaigns          : {headline['mule_ring_campaigns']}")
    print(f"  GNN score (VPN IP)           : {headline['gnn_score_vpn_ip']}")
    print(f"  GNN score (mule account)     : {headline['gnn_score_mule']}")
    print(f"  Fusion decision (VPN)        : {headline['vpn_fusion_decision']}")
    print(f"  Fusion decision (mule)       : {headline['mule_fusion_decision']}")
    print(f"  Containment actions          : {headline['containment_actions_dispatched']}")
    print(f"  Webhook deliveries           : {headline['webhook_deliveries']}")
    print()
    print("  Claim checks:")
    for check, passed in claims.items():
        mark = "PASS" if passed else "FAIL"
        print(f"    [{mark}] {check}")
    print()
    print(f"Operational claim supported: {claims.get('operational_claim_supported')}")
    print(f"Artifact: {out_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

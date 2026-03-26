#!/usr/bin/env python3
"""
collect_operational_proof.py -- lightweight live proof package
===============================================================

Collects conservative evidence from the running Sentinel-KE backend.
The helper only summarizes what it can observe from live endpoints; it does
not claim production readiness on its own.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

try:  # Prefer sibling import when the script is run from backend/scripts.
    from verify_operational_scalability import (  # type: ignore[import-not-found]
        login_for_token,
        probe_endpoint,
        summarize_latencies,
    )
except ImportError:  # pragma: no cover - fallback for package-style execution
    from scripts.verify_operational_scalability import (  # type: ignore[import-not-found]
        login_for_token,
        probe_endpoint,
        summarize_latencies,
    )


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _count_by(values: list[Any]) -> dict[str, int]:
    return dict(Counter(str(value) for value in values if value is not None))


def _probe(
    client: httpx.Client,
    *,
    name: str,
    path: str,
    category: str,
    api_key: str | None = None,
    headers: dict[str, str] | None = None,
    method: str = "GET",
    json_body: dict[str, Any] | None = None,
    repeats: int = 1,
    expected_statuses: set[int] | None = None,
) -> dict[str, Any]:
    result = probe_endpoint(
        client,
        path=path,
        api_key=api_key,
        repeats=repeats,
        method=method,
        headers=headers,
        json_body=json_body,
        expected_statuses=expected_statuses,
    )
    result["name"] = name
    result["category"] = category
    return result


def _summarize_health(payload: Any) -> dict[str, Any]:
    data = _as_dict(payload)
    workers = [item for item in _as_list(data.get("worker_freshness")) if isinstance(item, dict)]
    return {
        "status": data.get("status"),
        "schema_contract_ok": bool(data.get("schema_contract_ok")),
        "schema_missing_count": int(data.get("schema_missing_count") or 0),
        "gnn_loaded": bool(data.get("gnn_loaded")),
        "federation_partners": int(data.get("federation_partners") or 0),
        "federation_signed_requests_required": bool(data.get("federation_signed_requests_required")),
        "legal_anchor_integrity": data.get("legal_anchor_integrity"),
        "capabilities": list(data.get("capabilities") or [])[:8],
        "worker_freshness": {
            "count": len(workers),
            "status_counts": _count_by([w.get("freshness") for w in workers]),
            "stale_workers": [
                str(w.get("worker_name"))
                for w in workers
                if str(w.get("freshness") or "") != "pass"
            ][:5],
        },
    }


def _summarize_ready(payload: Any) -> dict[str, Any]:
    data = _as_dict(payload)
    components = _as_dict(data.get("components"))
    return {
        "status": data.get("status"),
        "components": components,
    }


def _summarize_metrics(payload: Any) -> dict[str, Any]:
    data = _as_dict(payload)
    return {
        "events": data.get("events"),
        "graph_deltas": data.get("graph_deltas"),
        "anomalies": data.get("anomalies"),
        "mitigations": data.get("mitigations"),
        "ai_drift_reports": data.get("ai_drift_reports"),
        "ai_feedback_labels": data.get("ai_feedback_labels"),
        "ai_rollouts": data.get("ai_rollouts"),
        "ai_decision_fusions": data.get("ai_decision_fusions"),
        "request_count": data.get("request_count"),
        "error_count": data.get("error_count"),
        "latency_p50_ms": data.get("latency_p50_ms"),
        "latency_p95_ms": data.get("latency_p95_ms"),
        "latency_p99_ms": data.get("latency_p99_ms"),
        "uptime_seconds": data.get("uptime_seconds"),
    }


def _summarize_trust_summary(payload: Any) -> dict[str, Any]:
    data = _as_dict(payload)
    checks = [item for item in _as_list(data.get("checks")) if isinstance(item, dict)]
    models = [item for item in _as_list(data.get("model_summaries")) if isinstance(item, dict)]
    return {
        "overall_status": data.get("overall_status"),
        "headline": data.get("headline"),
        "check_count": len(checks),
        "check_status_counts": _count_by([item.get("status") for item in checks]),
        "model_count": len(models),
        "model_status_counts": _count_by([item.get("status") for item in models]),
        "recommended_action_count": len(_as_list(data.get("recommended_actions"))),
    }


def _summarize_auth_me(payload: Any) -> dict[str, Any]:
    data = _as_dict(payload)
    return {
        "principal_type": data.get("principal_type"),
        "role": data.get("role"),
        "access_level": data.get("access_level"),
        "section_code": data.get("section_code"),
        "username": data.get("username"),
        "scopes_count": len(_as_list(data.get("scopes"))),
        "mfa_authenticated": bool(data.get("mfa_authenticated")),
    }


def _summarize_auth_users(payload: Any) -> dict[str, Any]:
    data = _as_dict(payload)
    items = [item for item in _as_list(data.get("items")) if isinstance(item, dict)]
    return {
        "count": int(data.get("total") or data.get("count") or len(items)),
        "limit": data.get("limit"),
        "offset": data.get("offset"),
        "access_levels": sorted({str(item.get("access_level")) for item in items if item.get("access_level")})[:5],
        "section_codes": sorted({str(item.get("section_code")) for item in items if item.get("section_code")})[:5],
    }


def _summarize_federation_partners(payload: Any) -> dict[str, Any]:
    items = [item for item in _as_list(payload) if isinstance(item, dict)]
    return {
        "count": len(items),
        "status_counts": _count_by([item.get("status") for item in items]),
        "partner_types": _count_by([item.get("partner_type") for item in items]),
        "active_count": sum(1 for item in items if item.get("is_active") is True),
    }


def _summarize_federation_correlations(payload: Any) -> dict[str, Any]:
    data = _as_dict(payload)
    correlations = [item for item in _as_list(data.get("correlations")) if isinstance(item, dict)]
    partner_counts = [int(item.get("partner_count") or 0) for item in correlations]
    return {
        "window_hours": data.get("window_hours"),
        "total_found": int(data.get("total_found") or len(correlations)),
        "correlation_count": len(correlations),
        "partner_count_max": max(partner_counts, default=0),
        "threat_levels": _count_by([item.get("threat_level") for item in correlations]),
    }


def _summarize_campaigns(payload: Any) -> dict[str, Any]:
    data = _as_dict(payload)
    items = [item for item in _as_list(data.get("items")) if isinstance(item, dict)]
    preview = [
        {
            "campaign_id": item.get("campaign_id"),
            "type": item.get("type"),
            "status": item.get("status"),
            "score": item.get("score"),
            "event_count": item.get("event_count"),
            "last_seen": item.get("last_seen"),
        }
        for item in items[:3]
    ]
    return {
        "count": int(data.get("count") or len(items)),
        "limit": data.get("limit"),
        "offset": data.get("offset"),
        "preview": preview,
    }


def _summarize_campaign_detail(payload: Any) -> dict[str, Any]:
    data = _as_dict(payload)
    entities = [item for item in _as_list(data.get("entities")) if isinstance(item, dict)]
    return {
        "campaign_id": data.get("campaign_id"),
        "type": data.get("type"),
        "status": data.get("status"),
        "score": data.get("score"),
        "event_count": data.get("event_count"),
        "entity_count": len(entities),
        "entity_type_count": len(_as_dict(data.get("entity_counts"))),
    }


def _summarize_campaign_events(payload: Any) -> dict[str, Any]:
    data = _as_dict(payload)
    items = [item for item in _as_list(data.get("items")) if isinstance(item, dict)]
    return {
        "count": int(data.get("count") or len(items)),
        "first_event_hashes": [str(item.get("event_hash")) for item in items[:5] if item.get("event_hash")],
    }


def _summarize_campaign_evidence(payload: Any) -> dict[str, Any]:
    data = _as_dict(payload)
    evidence = [item for item in _as_list(data.get("evidence")) if isinstance(item, dict)]
    campaign = _as_dict(data.get("campaign"))
    return {
        "campaign_id": campaign.get("id"),
        "campaign_type": campaign.get("type"),
        "count": int(data.get("count") or len(evidence)),
        "evidence_count": len(evidence),
        "first_event_hashes": [str(item.get("event_hash")) for item in evidence[:5] if item.get("event_hash")],
    }


def _summarize_campaign_risk(payload: Any) -> dict[str, Any]:
    data = _as_dict(payload)
    items = [item for item in _as_list(data.get("items")) if isinstance(item, dict)]
    scores = [float(item.get("score") or 0.0) for item in items]
    return {
        "count": int(data.get("count") or len(items)),
        "top_score": max(scores, default=0.0),
        "reason_code_counts": _count_by(
            reason
            for item in items
            for reason in _as_list(item.get("reason_codes"))
        ),
    }


def _summarize_case_packet(payload: Any) -> dict[str, Any]:
    data = _as_dict(payload)
    campaign = _as_dict(data.get("campaign"))
    summary = _as_dict(data.get("summary"))
    graph = _as_dict(data.get("graph"))
    return {
        "case_id": data.get("case_id"),
        "campaign_id": campaign.get("id"),
        "campaign_type": campaign.get("type"),
        "event_count": summary.get("event_count"),
        "distinct_entities": summary.get("distinct_entities"),
        "stage": summary.get("stage"),
        "graph_nodes": len(_as_list(graph.get("nodes"))),
        "graph_edges": len(_as_list(graph.get("edges"))),
        "integrity_present": bool(_as_dict(data.get("integrity"))),
    }


def _summarize_graph_evidence(payload: Any) -> dict[str, Any]:
    data = _as_dict(payload)
    keys = sorted(data.keys())[:12]
    return {
        "keys": keys,
        "has_evidence": "evidence" in data or "nodes" in data or "edges" in data,
    }


def _summarize_leakage_summary(payload: Any) -> dict[str, Any]:
    data = _as_dict(payload)
    top_vendors = [item for item in _as_list(data.get("top_vendors_by_suspected_amount")) if isinstance(item, dict)]
    return {
        "window_days": data.get("window_days"),
        "total_alerts": data.get("total_alerts"),
        "suspected_amount_total": data.get("suspected_amount_total"),
        "by_detector": _as_dict(data.get("by_detector")),
        "by_severity": _as_dict(data.get("by_severity")),
        "top_vendor_count": len(top_vendors),
    }


def _summarize_guardrail_decisions(payload: Any) -> dict[str, Any]:
    data = _as_dict(payload)
    items = [item for item in _as_list(data.get("items")) if isinstance(item, dict)]
    return {
        "count": len(items),
        "decision_counts": _count_by([item.get("decision") for item in items]),
        "sector_counts": _count_by([item.get("sector") for item in items]),
    }


def _summarize_check(check: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": check.get("name"),
        "category": check.get("category"),
        "method": check.get("method"),
        "path": check.get("path"),
        "status_code": check.get("status_code"),
        "ok": bool(check.get("ok")),
        "latency": check.get("latency"),
        "summary": check.get("summary"),
    }


def _section_status(checks: list[dict[str, Any]]) -> str:
    if any(check.get("required") and not check.get("ok") for check in checks if not check.get("skipped")):
        return "degraded"
    if any(check.get("skipped") for check in checks):
        return "partial"
    return "healthy"


def _find_check(checks: list[dict[str, Any]], prefix: str) -> dict[str, Any] | None:
    for check in checks:
        name = str(check.get("name") or "")
        if name.startswith(prefix):
            return check
    return None


def _collect_integrations(
    client: httpx.Client,
    *,
    api_key: str | None,
    primary_headers: dict[str, str] | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    signals: dict[str, Any] = {}

    campaigns = _probe(
        client,
        name="/v1/campaigns?limit=5",
        path="/v1/campaigns?limit=5",
        api_key=api_key,
        headers=primary_headers,
        expected_statuses={200},
        category="integration",
    )
    campaigns["summary"] = _summarize_campaigns(campaigns.get("sample"))
    checks.append(campaigns)

    campaign_items = _as_list(_as_dict(campaigns.get("sample")).get("items"))
    if campaign_items:
        campaign_id = str(campaign_items[0].get("campaign_id") or "")
        if campaign_id:
            signals["latest_campaign_id"] = campaign_id
            campaign_detail = _probe(
                client,
                name=f"/v1/campaigns/{campaign_id}",
                path=f"/v1/campaigns/{campaign_id}",
                api_key=api_key,
                headers=primary_headers,
                expected_statuses={200},
                category="integration",
            )
            campaign_detail["summary"] = _summarize_campaign_detail(campaign_detail.get("sample"))
            checks.append(campaign_detail)

            campaign_events = _probe(
                client,
                name=f"/v1/campaigns/{campaign_id}/events?limit=5",
                path=f"/v1/campaigns/{campaign_id}/events?limit=5",
                api_key=api_key,
                headers=primary_headers,
                expected_statuses={200},
                category="integration",
            )
            campaign_events["summary"] = _summarize_campaign_events(campaign_events.get("sample"))
            checks.append(campaign_events)

            campaign_evidence = _probe(
                client,
                name=f"/v1/campaigns/{campaign_id}/evidence?limit=25",
                path=f"/v1/campaigns/{campaign_id}/evidence?limit=25",
                api_key=api_key,
                headers=primary_headers,
                expected_statuses={200},
                category="integration",
            )
            campaign_evidence["summary"] = _summarize_campaign_evidence(campaign_evidence.get("sample"))
            checks.append(campaign_evidence)

            campaign_risk = _probe(
                client,
                name=f"/v1/campaigns/{campaign_id}/risk?limit=5",
                path=f"/v1/campaigns/{campaign_id}/risk?limit=5",
                api_key=api_key,
                headers=primary_headers,
                expected_statuses={200},
                category="integration",
            )
            campaign_risk["summary"] = _summarize_campaign_risk(campaign_risk.get("sample"))
            checks.append(campaign_risk)

            case_packet = _probe(
                client,
                name=f"POST /v1/cases/from-campaign/{campaign_id}",
                path=f"/v1/cases/from-campaign/{campaign_id}",
                api_key=api_key,
                headers=primary_headers,
                method="POST",
                expected_statuses={200},
                category="integration",
            )
            case_packet["summary"] = _summarize_case_packet(case_packet.get("sample"))
            checks.append(case_packet)

            events_payload = _as_dict(campaign_events.get("sample"))
            event_items = [item for item in _as_list(events_payload.get("items")) if isinstance(item, dict)]
            if event_items:
                event_hash = str(event_items[0].get("event_hash") or "")
                if event_hash:
                    signals["latest_event_hash"] = event_hash
                    graph_evidence = _probe(
                        client,
                        name=f"/v1/graph/evidence/{event_hash}",
                        path=f"/v1/graph/evidence/{event_hash}",
                        api_key=api_key,
                        headers=primary_headers,
                        expected_statuses={200},
                        category="integration",
                    )
                    graph_evidence["summary"] = _summarize_graph_evidence(graph_evidence.get("sample"))
                    checks.append(graph_evidence)

    leakage_summary = _probe(
        client,
        name="/v1/economy/leakage/summary",
        path="/v1/economy/leakage/summary?window_days=30",
        api_key=api_key,
        headers=primary_headers,
        expected_statuses={200, 403},
        category="integration",
    )
    leakage_summary["summary"] = _summarize_leakage_summary(leakage_summary.get("sample"))
    if leakage_summary.get("status_code") == 403:
        leakage_summary["summary"]["note"] = "access controlled for this principal; 403 is expected evidence of gating"
    else:
        leakage_summary["summary"]["note"] = "surface reachable"
    checks.append(leakage_summary)

    guardrail_decisions = _probe(
        client,
        name="/v1/economy/guardrail/decisions?limit=5",
        path="/v1/economy/guardrail/decisions?limit=5",
        api_key=api_key,
        headers=primary_headers,
        expected_statuses={200, 403},
        category="integration",
    )
    guardrail_decisions["summary"] = _summarize_guardrail_decisions(guardrail_decisions.get("sample"))
    if guardrail_decisions.get("status_code") == 403:
        guardrail_decisions["summary"]["note"] = "access controlled for this principal; 403 is expected evidence of gating"
    else:
        guardrail_decisions["summary"]["note"] = "surface reachable"
    checks.append(guardrail_decisions)

    if section_headers:
        partners = _probe(
            client,
            name="/v1/federation/partners?limit=10",
            path="/v1/federation/partners?limit=10",
            headers=primary_headers,
            expected_statuses={200},
            category="integration",
        )
        partners["summary"] = _summarize_federation_partners(partners.get("sample"))
        checks.append(partners)

        correlations = _probe(
            client,
            name="/v1/federation/correlations?limit=10",
            path="/v1/federation/correlations?limit=10",
            headers=primary_headers,
            expected_statuses={200},
            category="integration",
        )
        correlations["summary"] = _summarize_federation_correlations(correlations.get("sample"))
        checks.append(correlations)

    return checks, signals


def _build_report(
    *,
    base_url: str,
    robustness: list[dict[str, Any]],
    trust: list[dict[str, Any]],
    integration: list[dict[str, Any]],
    signals: dict[str, Any],
) -> dict[str, Any]:
    all_checks = robustness + trust + integration
    passed = sum(1 for check in all_checks if check.get("ok"))
    failed = sum(1 for check in all_checks if check.get("required") and not check.get("ok") and not check.get("skipped"))
    skipped = sum(1 for check in all_checks if check.get("skipped"))
    semantic_flags: list[str] = []
    health_summary = (_find_check(robustness, "health") or {}).get("summary", {})
    trust_summary = (_find_check(trust, "/v1/ai/trust/summary") or {}).get("summary", {})
    worker_freshness = _as_dict(health_summary).get("worker_freshness") or {}
    worker_status_counts = _as_dict(worker_freshness).get("status_counts") or {}
    if str(trust_summary.get("overall_status") or "") == "fail":
        semantic_flags.append("ai_trust_summary_fail")
    if int(_as_dict(worker_status_counts).get("fail") or 0) > 0:
        semantic_flags.append("worker_freshness_fail")
    if str(health_summary.get("schema_contract_ok")) == "False":
        semantic_flags.append("schema_contract_failed")
    required_failures = any(
        check.get("required") and not check.get("ok") and not check.get("skipped")
        for check in all_checks
    )
    if required_failures:
        overall_status = "degraded"
    elif skipped or semantic_flags:
        overall_status = "partial"
    else:
        overall_status = "healthy"

    core_latencies = [
        float(check["latency"]["p95_ms"])
        for check in all_checks
        if isinstance(check.get("latency"), dict) and check["latency"].get("p95_ms") is not None
    ]

    return {
        "checked_at": _utcnow(),
        "base_url": base_url,
        "overall_status": overall_status,
        "sections": {
            "robustness": {
                "status": _section_status(robustness),
                "signals": {
                    "health": robustness[0].get("summary") if robustness else {},
                    "ready": robustness[1].get("summary") if len(robustness) > 1 else {},
                    "metrics": robustness[2].get("summary") if len(robustness) > 2 else {},
                    "platform_trust": robustness[3].get("summary") if len(robustness) > 3 else {},
                },
                "checks": [_summarize_check(check) for check in robustness],
            },
            "trust": {
                "status": _section_status(trust),
                "signals": {
                    "platform_trust_summary": (_find_check(trust, "/v1/ai/trust/summary") or {}).get("summary", {}),
                    "section_login": (_find_check(trust, "section login") or {}).get("summary", {}),
                    "section_auth": (_find_check(trust, "/v1/auth/me (section)") or {}).get("summary", {}),
                    "section_rbac": (_find_check(trust, "/v1/auth/users?limit=1 (section)") or {}).get("summary", {}),
                    "central_login": (_find_check(trust, "central login") or {}).get("summary", {}),
                    "central_auth": (_find_check(trust, "/v1/auth/me (central)") or {}).get("summary", {}),
                    "central_rbac": (_find_check(trust, "/v1/auth/users?limit=1 (central)") or {}).get("summary", {}),
                },
                "checks": [_summarize_check(check) for check in trust],
            },
            "integration": {
                "status": _section_status(integration),
                "signals": signals,
                "checks": [_summarize_check(check) for check in integration],
            },
        },
        "summary": {
            "passed_checks": passed,
            "failed_checks": failed,
            "skipped_checks": skipped,
            "semantic_flags": semantic_flags,
            "observed_signals": signals,
            "latency": summarize_latencies(core_latencies),
        },
        "checks": [_summarize_check(check) for check in all_checks],
    }


def _print_report(report: dict[str, Any]) -> None:
    sections = _as_dict(report.get("sections"))
    print("Sentinel-KE operational proof")
    print("=" * 40)
    print(f"Overall: {report.get('overall_status')}")
    for key in ("robustness", "trust", "integration"):
        section = _as_dict(sections.get(key))
        print(f"{key.title()}: {section.get('status')}")
    summary = _as_dict(report.get("summary"))
    latency = _as_dict(summary.get("latency"))
    if latency:
        print(
            "Latency p95 ms: "
            f"{latency.get('p95_ms')} across {latency.get('count')} measured requests"
        )
    signals = _as_dict(summary.get("observed_signals"))
    if signals:
        if signals.get("latest_campaign_id"):
            print(f"Latest campaign observed: {signals.get('latest_campaign_id')}")
        if signals.get("latest_event_hash"):
            print(f"Latest event observed: {signals.get('latest_event_hash')}")
    print(f"Passed: {summary.get('passed_checks')}  Failed: {summary.get('failed_checks')}  Skipped: {summary.get('skipped_checks')}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect lightweight operational proof from a live backend")
    parser.add_argument("--base-url", default="http://localhost:8000", help="Backend base URL")
    parser.add_argument("--api-key", default="", help="Optional service API key")
    parser.add_argument("--repeats", type=int, default=2, help="Repeated requests for core robustness probes")
    parser.add_argument("--section-username", default="", help="Optional section user for trust/RBAC proof")
    parser.add_argument("--section-password", default="", help="Password for the section user")
    parser.add_argument("--central-username", default="", help="Optional central user for trust/RBAC proof")
    parser.add_argument("--central-password", default="", help="Password for the central user")
    parser.add_argument(
        "--out",
        default="artifacts/operational_proof_report.json",
        help="Where to write the JSON artifact",
    )
    args = parser.parse_args(argv)

    section_headers: dict[str, str] | None = None
    central_headers: dict[str, str] | None = None
    trust_checks: list[dict[str, Any]] = []
    trust_signals: dict[str, Any] = {}
    with httpx.Client(base_url=args.base_url, timeout=15.0) as client:
        robustness = []
        for name, path in (
            ("health", "/health"),
            ("ready", "/ready"),
            ("metrics", "/v1/metrics"),
            ("prometheus metrics", "/metrics"),
        ):
            probe = _probe(
                client,
                name=name,
                path=path,
                api_key=args.api_key or None,
                repeats=args.repeats if name in {"health", "ready", "metrics"} else 1,
                expected_statuses={200},
                category="robustness",
            )
            if path == "/health":
                probe["summary"] = _summarize_health(probe.get("sample"))
            elif path == "/ready":
                probe["summary"] = _summarize_ready(probe.get("sample"))
            elif path == "/v1/metrics":
                probe["summary"] = _summarize_metrics(probe.get("sample"))
            else:
                probe["summary"] = {"status_code": probe.get("status_code")}
            robustness.append(probe)

        trust_summary = _probe(
            client,
            name="/v1/ai/trust/summary",
            path="/v1/ai/trust/summary",
            api_key=args.api_key or None,
            expected_statuses={200},
            category="trust",
        )
        trust_summary["summary"] = _summarize_trust_summary(trust_summary.get("sample"))
        trust_checks.append(trust_summary)

        if args.section_username and args.section_password:
            try:
                token_payload = login_for_token(
                    client,
                    username=args.section_username,
                    password=args.section_password,
                )
            except Exception as exc:  # noqa: BLE001
                trust_checks.append(
                    {
                        "name": "section login",
                        "category": "trust",
                        "required": True,
                        "skipped": False,
                        "ok": False,
                        "method": "POST",
                        "path": "/v1/auth/login",
                        "status_code": None,
                        "latency": None,
                        "summary": {"error": str(exc)},
                    }
                )
            else:
                section_headers = {"Authorization": f"Bearer {str(token_payload['access_token'])}"}
                section_login = {
                    "name": "section login",
                    "category": "trust",
                    "required": True,
                    "skipped": False,
                    "ok": True,
                    "method": "POST",
                    "path": "/v1/auth/login",
                    "status_code": 200,
                    "latency": None,
                    "summary": {"principal": _summarize_auth_me(token_payload.get("principal"))},
                }
                trust_checks.append(section_login)

                section_auth = _probe(
                    client,
                    name="/v1/auth/me (section)",
                    path="/v1/auth/me",
                    headers=section_headers,
                    expected_statuses={200},
                    category="trust",
                )
                section_auth["summary"] = _summarize_auth_me(section_auth.get("sample"))
                trust_checks.append(section_auth)

                section_users = _probe(
                    client,
                    name="/v1/auth/users?limit=1 (section)",
                    path="/v1/auth/users?limit=1",
                    headers=section_headers,
                    expected_statuses={403},
                    category="trust",
                )
                section_users["summary"] = _summarize_auth_users(section_users.get("sample"))
                trust_checks.append(section_users)
        else:
            trust_checks.append(
                {
                    "name": "section auth",
                    "category": "trust",
                    "required": False,
                    "skipped": True,
                    "ok": False,
                    "method": "GET",
                    "path": "/v1/auth/me",
                    "status_code": None,
                    "latency": None,
                    "summary": {"note": "section credentials not provided"},
                }
            )
            trust_checks.append(
                {
                    "name": "section RBAC",
                    "category": "trust",
                    "required": False,
                    "skipped": True,
                    "ok": False,
                    "method": "GET",
                    "path": "/v1/auth/users?limit=1",
                    "status_code": None,
                    "latency": None,
                    "summary": {"note": "section credentials not provided"},
                }
            )

        if args.central_username and args.central_password:
            try:
                token_payload = login_for_token(
                    client,
                    username=args.central_username,
                    password=args.central_password,
                )
            except Exception as exc:  # noqa: BLE001
                trust_checks.append(
                    {
                        "name": "central login",
                        "category": "trust",
                        "required": True,
                        "skipped": False,
                        "ok": False,
                        "method": "POST",
                        "path": "/v1/auth/login",
                        "status_code": None,
                        "latency": None,
                        "summary": {"error": str(exc)},
                    }
                )
            else:
                central_headers = {"Authorization": f"Bearer {str(token_payload['access_token'])}"}
                central_login = {
                    "name": "central login",
                    "category": "trust",
                    "required": True,
                    "skipped": False,
                    "ok": True,
                    "method": "POST",
                    "path": "/v1/auth/login",
                    "status_code": 200,
                    "latency": None,
                    "summary": {"principal": _summarize_auth_me(token_payload.get("principal"))},
                }
                trust_checks.append(central_login)

                central_auth = _probe(
                    client,
                    name="/v1/auth/me (central)",
                    path="/v1/auth/me",
                    headers=central_headers,
                    expected_statuses={200},
                    category="trust",
                )
                central_auth["summary"] = _summarize_auth_me(central_auth.get("sample"))
                trust_checks.append(central_auth)

                central_users = _probe(
                    client,
                    name="/v1/auth/users?limit=1 (central)",
                    path="/v1/auth/users?limit=1",
                    headers=central_headers,
                    expected_statuses={200},
                    category="trust",
                )
                central_users["summary"] = _summarize_auth_users(central_users.get("sample"))
                trust_checks.append(central_users)
        else:
            trust_checks.append(
                {
                    "name": "central auth",
                    "category": "trust",
                    "required": False,
                    "skipped": True,
                    "ok": False,
                    "method": "GET",
                    "path": "/v1/auth/me",
                    "status_code": None,
                    "latency": None,
                    "summary": {"note": "central credentials not provided"},
                }
            )
            trust_checks.append(
                {
                    "name": "central RBAC",
                    "category": "trust",
                    "required": False,
                    "skipped": True,
                    "ok": False,
                    "method": "GET",
                    "path": "/v1/auth/users?limit=1",
                    "status_code": None,
                    "latency": None,
                    "summary": {"note": "central credentials not provided"},
                }
            )

        integration_checks, signals = _collect_integrations(
            client,
            api_key=args.api_key or None,
            primary_headers=central_headers or section_headers,
        )

    report = _build_report(
        base_url=args.base_url,
        robustness=robustness,
        trust=trust_checks,
        integration=integration_checks,
        signals=signals,
    )

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True))

    _print_report(report)
    print(f"JSON artifact: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

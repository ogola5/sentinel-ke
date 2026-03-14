from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import Depends
from fastapi.routing import APIRouter

from app.api.ai import router as ai_router
from app.api.demo import router as demo_router
from app.api.anomalies import router as anomalies_router
from app.api.auth import router as auth_router
from app.api.crypto_posture import router as crypto_posture_router
from app.api.campaign_evidence import router as campaign_evidence_router
from app.api.campaigns import router as campaigns_router
from app.api.ddos import router as ddos_router
from app.api.defense import router as defense_router
from app.api.deps import (
    require_api_key,
    require_central_access,
    require_scope,
    require_section_access,
    require_step_up,
)
from app.api.economy import router as economy_router
from app.api.economy_coverup import router as economy_coverup_router
from app.api.economy_guardrail import router as economy_guardrail_router
from app.api.economy_leakage import router as economy_leakage_router
from app.api.events import router as events_router
from app.api.graph import router as graph_router
from app.api.infra_clusters import router as infra_clusters_router
from app.api.infra_graph import router as infra_graph_router
from app.api.integrations import router as integrations_router
from app.api.legal import router as legal_router
from app.api.metrics import router as metrics_router
from app.api.mitigations import router as mitigations_router
from app.api.reports import router as reports_router
from app.api.stix import router as stix_router
from app.api.federation import router as federation_router
from app.api.stream import router as stream_router
from app.cases.api import router as cases_router
from app.ingestion.router import router as ingest_router


@dataclass(frozen=True)
class RouterMount:
    router: APIRouter
    dependencies: tuple[Any, ...]


def build_tags_metadata(*, ai_enabled: bool) -> list[dict[str, str]]:
    tags = [
        {"name": "auth", "description": "User authentication and RBAC"},
        {"name": "ops", "description": "Service liveness and readiness endpoints"},
        {"name": "ingest", "description": "Evidence-grade ingestion"},
        {"name": "events", "description": "Event search and timeline"},
        {"name": "campaigns", "description": "Campaigns and risk"},
        {"name": "infra-clusters", "description": "Infrastructure clusters and graph"},
        {"name": "ddos", "description": "DDoS indicators and alerts"},
        {"name": "anomalies", "description": "Anomaly scores"},
        {"name": "mitigations", "description": "IOC and mitigation bundles"},
        {"name": "reports", "description": "Downloadable operational, legal, and AI explainability reports"},
        {"name": "integrations", "description": "External connector ingestion bridge"},
        {"name": "legal", "description": "Court-order authorization and legal controls"},
        {"name": "metrics", "description": "Operational metrics"},
        {"name": "economy", "description": "Economic integrity and procurement anomalies"},
        {"name": "defense", "description": "Vulnerability, incident response, backup resilience, and crypto posture"},
        {"name": "crypto-posture", "description": "Post-quantum cryptographic posture — FIPS 203/204/197 compliance and algorithm status"},
        {"name": "federation", "description": "Federated intelligence network — edge-agent pattern ingestion and cross-partner threat correlations"},
        {"name": "stream", "description": "Server-Sent Events real-time threat event stream"},
    ]
    if ai_enabled:
        tags.append({"name": "ai", "description": "AI predictions and explanations"})
    return tags


def build_router_mounts(*, ai_enabled: bool) -> list[RouterMount]:
    mounts = [
        RouterMount(auth_router, ()),
        RouterMount(crypto_posture_router, ()),  # public — no auth on /posture; self-test requires section access
        RouterMount(stream_router, ()),           # SSE stream — auth handled internally via ?token= param
        RouterMount(ingest_router, (Depends(require_api_key),)),
        RouterMount(events_router, (Depends(require_section_access), Depends(require_scope("events.read")))),
        RouterMount(graph_router, (Depends(require_central_access), Depends(require_scope("graph.read")))),
        RouterMount(campaigns_router, (Depends(require_section_access), Depends(require_scope("campaigns.read")))),
        RouterMount(infra_clusters_router, (Depends(require_section_access), Depends(require_scope("infra.read")))),
        RouterMount(ddos_router, (Depends(require_section_access), Depends(require_scope("ddos.read")))),
        RouterMount(campaign_evidence_router, (Depends(require_section_access), Depends(require_scope("campaigns.read")))),
        RouterMount(cases_router, (Depends(require_section_access), Depends(require_scope("cases.read")))),
        RouterMount(stix_router, (Depends(require_section_access), Depends(require_scope("intel.read")))),
        RouterMount(infra_graph_router, (Depends(require_central_access), Depends(require_scope("infra.read")))),
        RouterMount(anomalies_router, (Depends(require_section_access), Depends(require_scope("anomalies.read")))),
        RouterMount(mitigations_router, (Depends(require_section_access), Depends(require_scope("mitigations.read")))),
        RouterMount(reports_router, (Depends(require_section_access), Depends(require_scope("ai.read")))),
        RouterMount(metrics_router, (Depends(require_section_access), Depends(require_scope("metrics.read")))),
        RouterMount(integrations_router, (Depends(require_section_access), Depends(require_scope("integrations.write")))),
        RouterMount(
            legal_router,
            (
                Depends(require_central_access),
                Depends(require_scope("legal.write")),
                Depends(require_step_up()),
            ),
        ),
        RouterMount(
            economy_router,
            (
                Depends(require_central_access),
                Depends(require_scope("economy.write")),
                Depends(require_step_up()),
            ),
        ),
        RouterMount(
            economy_guardrail_router,
            (
                Depends(require_central_access),
                Depends(require_scope("economy.write")),
                Depends(require_step_up()),
            ),
        ),
        RouterMount(
            economy_leakage_router,
            (
                Depends(require_central_access),
                Depends(require_scope("economy.write")),
                Depends(require_step_up()),
            ),
        ),
        RouterMount(
            economy_coverup_router,
            (
                Depends(require_central_access),
                Depends(require_scope("economy.write")),
                Depends(require_step_up()),
            ),
        ),
        RouterMount(defense_router, ()),
        # Federation router manages its own per-endpoint auth:
        #   POST /patterns  → partner API key (edge agents)
        #   GET  /partners, /stream, /correlations → section access (analysts)
        #   POST /register  → central access + integrations.write (admin)
        RouterMount(federation_router, ()),
        # Demo/seed endpoints — central access only; gated by DEMO_ENDPOINTS_ENABLED
        RouterMount(demo_router, ()),
    ]

    if ai_enabled:
        mounts.append(RouterMount(ai_router, (Depends(require_section_access), Depends(require_scope("ai.read")))))

    return mounts

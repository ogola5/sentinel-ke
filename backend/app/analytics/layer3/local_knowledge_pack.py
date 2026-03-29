from __future__ import annotations

from typing import Any, Dict, List


DOCS = {
    "three_lane": "docs/THREE_LANE_AI_STORY.md",
    "benchmark": "docs/BENCHMARK_SUMMARY.md",
    "legacy": "docs/LEGACY_CONNECTOR_BLUEPRINT.md",
    "demo": "docs/DEMO_10MIN_RUNBOOK.md",
    "qa": "docs/JUDGE_QA_BANK.md",
    "presentation": "docs/PRESENTATION_10_SLIDE_CLAUDE_PACK.md",
    "external_containment": "docs/EXTERNAL_CONTAINMENT_DEMO.md",
}


def _infer_lane(question: str) -> str:
    q = str(question or "").lower()
    if any(token in q for token in ("fraud", "paysim", "mule", "sim swap", "simswap", "vpn")):
        return "fraud"
    if any(token in q for token in ("corruption", "procurement", "ppra", "eacc", "kenya law")):
        return "corruption"
    if any(token in q for token in ("cyber", "ddos", "malware", "threatfox", "malwarebazaar", "urlhaus", "feodo")):
        return "cyber"
    return "system"


def _training_knowledge(lane: str) -> dict[str, Any]:
    if lane == "cyber":
        return {
            "summary": (
                "Cyber training uses real ingested cyber events such as URLhaus malicious URLs, Feodo botnet C2 infrastructure, "
                "ThreatFox IOCs, MalwareBazaar malware intelligence, and operational OSINT telemetry. The graph connects IPs, domains, "
                "services, and accounts, and evaluation uses a temporal holdout on recent windows. The honest claim is live cyber evidence "
                "with strong recent scientific support, not fully adjudicated national ground truth."
            ),
            "sources": [DOCS["three_lane"], DOCS["benchmark"]],
        }
    if lane == "fraud":
        return {
            "summary": (
                "Fraud training is currently benchmarked on PaySim, a 6.3 million transaction M-Pesa-style corpus used for mobile-money fraud research. "
                "It models transaction graphs between accounts and supports SIM-swap, mule-ring, and VPN-style correlation logic in the platform. "
                "The honest claim is a fresh fraud benchmark artifact, not live sovereign partner fraud telemetry."
            ),
            "sources": [DOCS["three_lane"], DOCS["benchmark"], DOCS["qa"]],
        }
    if lane == "corruption":
        return {
            "summary": (
                "Corruption training uses PPRA procurement awards, Kenya Law judgments, and EACC case outcomes. The graph links suppliers, officials, tenders, "
                "contracts, and payment relationships. It is a mixed-supervision ranking lane designed for investigation support, not legal adjudication."
            ),
            "sources": [DOCS["three_lane"], DOCS["benchmark"]],
        }
    return {
        "summary": (
            "Sentinel-KE has three separate intelligence lanes: cyber, fraud, and corruption. They share the GraphSAGE backbone and feature discipline, "
            "but they train on different data, evaluate on different holdouts, and support different claims."
        ),
        "sources": [DOCS["three_lane"], DOCS["benchmark"]],
    }


def _graph_knowledge(question: str) -> dict[str, Any]:
    q = str(question or "").lower()
    if "edge" in q or "line" in q or "relationship" in q:
        return {
            "summary": (
                "In the Threat Graph, an edge means an observed relationship in the current attack snapshot. It is evidence of linkage, not proof by itself. "
                "The edge count shows how many supporting observations tied the two nodes together, and the sources show where that linkage came from."
            ),
            "sources": [DOCS["demo"], DOCS["qa"]],
        }
    if "campaign" in q:
        return {
            "summary": (
                "Campaign grouping nodes are operational clusters that tie multiple observations together. They help answer whether separate attacker IPs, endpoints, "
                "or incidents belong to one broader operation. They are grouping aids, not direct attacker identity proof."
            ),
            "sources": [DOCS["demo"], DOCS["qa"]],
        }
    return {
        "summary": (
            "Read the graph left to right. Target-side nodes are the services and endpoints under pressure. Attacker infrastructure nodes are the IPs, clusters, "
            "and providers being used. Campaign groupings help show whether multiple signals belong to one operation. Hover tells you what a node or edge represents; "
            "clicking moves from overview into investigation."
        ),
        "sources": [DOCS["demo"], DOCS["presentation"]],
    }


def _connectors_knowledge() -> dict[str, Any]:
    return {
        "summary": (
            "Legacy systems connect through the connector seam: GET /v1/integrations/connectors, then POST /v1/integrations/{connector_key}/event or /batch. "
            "The practical bridge is legacy export or relay to connector API to canonical event ledger to graph, GNN, explanation, containment, and reporting. "
            "This avoids forcing agencies to replace existing SIEMs, WAFs, telco systems, or banking exports."
        ),
        "sources": [DOCS["legacy"], DOCS["qa"]],
    }


def _deployment_knowledge() -> dict[str, Any]:
    return {
        "summary": (
            "The system is designed for sovereign deployment with hub-and-edge federation. Sensitive data can stay local while risk signals and signed evidence move outward. "
            "The architecture is practical for agencies because it enhances existing systems through connectors and bridges instead of requiring rip-and-replace."
        ),
        "sources": [DOCS["legacy"], DOCS["presentation"], DOCS["qa"]],
    }


def _containment_knowledge() -> dict[str, Any]:
    return {
        "summary": (
            "Containment in Sentinel-KE is deliberately bounded. The correct ladder is observe, then challenge or rate-limit, then isolate a specific asset or account path, "
            "then upstream block or scrub only when evidence and operational impact justify it. The judge-safe claim is signed, auditable cross-system workflow, not blanket shutdown."
        ),
        "sources": [DOCS["external_containment"], DOCS["qa"], DOCS["demo"]],
    }


def _claims_knowledge() -> dict[str, Any]:
    return {
        "summary": (
            "Safe claims are: cyber is live and strongest today, PaySim is a separate fraud benchmark lane, corruption is investigative risk intelligence not legal proof, "
            "and containment is bounded, signed, and auditable. Avoid saying the GNN alone detects everything or that any single lane proves another."
        ),
        "sources": [DOCS["presentation"], DOCS["qa"], DOCS["benchmark"]],
    }


def _system_knowledge() -> dict[str, Any]:
    return {
        "summary": (
            "Sentinel-KE is one operating loop: ingest signals, build graph relationships, prioritize with GNNs and ML, explain with evidence and trust checks, "
            "then contain and report. The product should be explained as a workflow for operators, not as one model or one dashboard."
        ),
        "sources": [DOCS["presentation"], DOCS["demo"], DOCS["qa"]],
    }


def get_local_knowledge(topic: str, question: str = "") -> dict[str, Any]:
    lane = _infer_lane(question)
    if topic == "training":
        return _training_knowledge(lane)
    if topic == "graph":
        return _graph_knowledge(question)
    if topic == "connectors":
        return _connectors_knowledge()
    if topic == "deployment":
        return _deployment_knowledge()
    if topic == "containment":
        return _containment_knowledge()
    if topic == "claims":
        return _claims_knowledge()
    return _system_knowledge()


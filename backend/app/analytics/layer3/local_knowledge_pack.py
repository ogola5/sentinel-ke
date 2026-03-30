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

CODE = {
    "pipeline": "backend/app/integrations/real_data_pipeline.py",
    "connectors": "backend/app/integrations/connectors.py",
    "cyber_backbone": "backend/app/analytics/layer3/gnn_backbone.py",
    "cyber_model": "backend/app/analytics/layer3/gnn_model.py",
    "cyber_inference": "backend/app/analytics/layer3/ai_inference_worker.py",
    "mule": "backend/app/analytics/layer3/mule_campaign_worker.py",
    "corruption_features": "backend/app/analytics/corruption/feature_builder.py",
    "corruption_train": "backend/app/analytics/corruption/train_worker.py",
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


def _ml_terms_knowledge(question: str) -> dict[str, Any]:
    q = str(question or "").lower()
    if "false positive" in q or "false alarm" in q:
        return {
            "summary": (
                "A false positive is a safe item the model flagged as risky by mistake. In operations, that is a false alarm. "
                "Precision is the metric that tells you how well the system controls false positives."
            ),
            "sources": [DOCS["benchmark"], CODE["cyber_model"]],
        }
    if "false negative" in q or "miss" in q:
        return {
            "summary": (
                "A false negative is a risky item the model missed. In operations, that is a miss. "
                "Recall is the metric that tells you how well the system avoids false negatives."
            ),
            "sources": [DOCS["benchmark"], CODE["cyber_model"]],
        }
    if "auc" in q or "pr-auc" in q:
        return {
            "summary": (
                "AUC measures ranking quality across thresholds. PR-AUC is especially important when positives are rare, as in fraud and security. "
                "A model can have high AUC but weaker operating precision if the current threshold is still conservative."
            ),
            "sources": [DOCS["benchmark"], CODE["cyber_model"]],
        }
    if "precision" in q or "recall" in q or "f1" in q:
        return {
            "summary": (
                "Precision tells you how many flagged items were truly risky. Recall tells you how many truly risky items were caught. "
                "F1 balances the two. In Sentinel-KE, ranking quality and operating-threshold quality are presented separately on purpose."
            ),
            "sources": [DOCS["benchmark"], CODE["cyber_model"]],
        }
    if "holdout" in q or "temporal" in q or "leak" in q or "overfit" in q:
        return {
            "summary": (
                "Sentinel-KE uses temporal holdout thinking: train on earlier windows, evaluate on later unseen windows. "
                "That is how the platform reduces leakage and overfitting risk instead of rewarding memorization."
            ),
            "sources": [DOCS["benchmark"], CODE["cyber_backbone"], CODE["corruption_train"]],
        }
    if "weak label" in q or "ground truth" in q or "label" in q:
        return {
            "summary": (
                "A weak label is an imperfect but useful learning signal derived from structured risk flags or known outcomes. "
                "Ground truth is the strongest confirmed answer available. Sentinel-KE is explicit when a lane is mixed-supervision rather than perfect ground truth."
            ),
            "sources": [DOCS["benchmark"], CODE["cyber_backbone"], CODE["corruption_features"]],
        }
    if "uncertainty" in q or "confidence" in q or "calibration" in q:
        return {
            "summary": (
                "The model reports both a risk score and uncertainty. Sentinel-KE uses MC Dropout to estimate uncertainty so operators can separate strong signals "
                "from borderline ones. High uncertainty is a cue for review, not overclaiming."
            ),
            "sources": [DOCS["benchmark"], CODE["cyber_model"], CODE["cyber_inference"]],
        }
    return {
        "summary": (
            "The key ML terms judges will probe are AUC, PR-AUC, precision, recall, F1, threshold, holdout, weak labels, false positives, false negatives, "
            "confidence, and uncertainty. The safe explanation is that AUC measures ranking strength, while precision, recall, and F1 measure how the chosen "
            "operating threshold behaves in practice."
        ),
        "sources": [DOCS["benchmark"], CODE["cyber_model"]],
    }


def _onboarding_knowledge(question: str) -> dict[str, Any]:
    q = str(question or "").lower()
    if "integrity" in q or "provenance" in q or "quality" in q:
        return {
            "summary": (
                "Data integrity is preserved through canonical mapping, schema validation, provenance tagging, pseudonymisation where appropriate, and evidence lineage "
                "into predictions and explanations. The system should not silently accept malformed or source-ambiguous data."
            ),
            "sources": [DOCS["legacy"], CODE["pipeline"], CODE["connectors"], CODE["cyber_inference"]],
        }
    return {
        "summary": (
            "Agencies onboard through the connector seam, not by replacing their systems. Modern systems can post direct events or batches to the integration API, "
            "while older systems can export CSV, JSONL, or database extracts through a bridge. Sentinel-KE normalizes those records into one canonical event ledger "
            "before graphing, scoring, explanation, and reporting."
        ),
        "sources": [DOCS["legacy"], DOCS["qa"], CODE["pipeline"], CODE["connectors"]],
    }


def _competition_knowledge() -> dict[str, Any]:
    return {
        "summary": (
            "The closest competitors are Microsoft Sentinel and Defender, CrowdStrike Falcon and Threat Graph, Google Security Operations, Palo Alto Cortex XSIAM, "
            "and Splunk Enterprise Security. They already prove the value of graph analytics, ML, and security automation. Sentinel-KE's gap is sovereign Kenyan fit, "
            "multi-agency federation, bounded cross-domain response, and a workflow that spans cyber, fraud, and integrity risk instead of a generic global SOC tool."
        ),
        "sources": [DOCS["presentation"], DOCS["qa"], DOCS["legacy"]],
    }


def _judge_qa_knowledge(question: str) -> dict[str, Any]:
    q = str(question or "").lower()
    lane = _infer_lane(question)
    if lane == "corruption":
        return {
            "summary": (
                "The corruption lane uses a separate 42-dimensional corruption feature vector over officials, companies, contracts, payments, projects, accounts, "
                "departments, tenders, suppliers, and directors. Positive signals come from independent procurement and integrity cues such as audit findings, "
                "debarment, director conflicts, recovery orders, shell-company indicators, related-party patterns, and payment-delivery mismatches. "
                "It is an investigative risk-ranking lane under mixed supervision, not legal proof."
            ),
            "sources": [DOCS["benchmark"], DOCS["qa"], CODE["corruption_features"], CODE["corruption_train"]],
        }
    if lane == "fraud":
        if "mule" in q:
            return {
                "summary": (
                    "Mule-ring campaign creation is structural and rule-driven before any GNN narrative is added. The worker scans recent transaction events, groups "
                    "inbound transfers by receiving account, requires minimum sender diversity and transaction count, then boosts the score if rapid cashout follows. "
                    "It writes a MULE_RING campaign with mule, victim, and cashout-agent roles and then projects that campaign into the graph."
                ),
                "sources": [DOCS["qa"], CODE["mule"]],
            }
        if "sim" in q or "swap" in q:
            return {
                "summary": (
                    "The SIM-swap story in Sentinel-KE is a fraud-chain reasoning path: SIM swap event to login event to transfer to cashout. The graph helps connect "
                    "those stages across accounts, phones, devices, and agents. The safe claim is that the platform can model and prioritize that chain; the public "
                    "benchmark evidence for fraud remains PaySim."
                ),
                "sources": [DOCS["three_lane"], DOCS["benchmark"], DOCS["qa"]],
            }
        if "vpn" in q:
            return {
                "summary": (
                    "VPN-style abuse is treated as infrastructure-reuse risk, not as proof that all VPN use is malicious. In the cyber feature space, VPN cluster "
                    "membership can contribute to risk flags and graph structure, then the model and campaign logic help decide whether the shared infrastructure "
                    "looks operationally suspicious."
                ),
                "sources": [DOCS["qa"], CODE["cyber_backbone"]],
            }
        return {
            "summary": (
                "The fraud lane combines graph reasoning for SIM swap, mule movement, and infrastructure reuse with a separate PaySim benchmark artifact. "
                "The safe line is that the platform supports fraud-chain reasoning today, while the strongest public fraud metric evidence is still the fresh PaySim evaluation."
            ),
            "sources": [DOCS["three_lane"], DOCS["benchmark"], DOCS["qa"]],
        }
    if lane == "cyber":
        return {
            "summary": (
                "The cyber lane ingests real threat-intel and telemetry feeds, normalizes them into canonical events, builds entity-level graph snapshots, and learns "
                "on a 44-dimensional cyber feature space covering entity type, volume, temporal behavior, risk flags, event-type counts, and behavioral ratios. "
                "The GNN is the correlation and prioritization layer, while inference can still fall back to heuristics if no clean artifact is active."
            ),
            "sources": [DOCS["three_lane"], DOCS["benchmark"], CODE["pipeline"], CODE["cyber_backbone"], CODE["cyber_inference"]],
        }
    return {
        "summary": (
            "The safest judge explanation is that Sentinel-KE is an operating loop: ingest signals, normalize them, build entity relationships in a graph, rank with "
            "GNNs and ML, explain with evidence and caveats, then route bounded containment and reporting. The lanes share architecture discipline, not identical data or claims."
        ),
        "sources": [DOCS["presentation"], DOCS["qa"], CODE["pipeline"], CODE["cyber_backbone"]],
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
    if topic == "ml_terms":
        return _ml_terms_knowledge(question)
    if topic == "graph":
        return _graph_knowledge(question)
    if topic == "onboarding":
        return _onboarding_knowledge(question)
    if topic == "competition":
        return _competition_knowledge()
    if topic == "judge_qa":
        return _judge_qa_knowledge(question)
    if topic == "connectors":
        return _connectors_knowledge()
    if topic == "deployment":
        return _deployment_knowledge()
    if topic == "containment":
        return _containment_knowledge()
    if topic == "claims":
        return _claims_knowledge()
    return _system_knowledge()

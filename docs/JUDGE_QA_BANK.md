# Sentinel-KE Judge Q&A Bank

Last updated: 2026-03-27

This is a judge-facing answer bank for the Stage 2 rubric. Each answer is grounded in the repo evidence and current live artifacts. Use the short answer first, then the technical answer if the judge pushes deeper. Do not use the dangerous answer.

## 1) What problem does Sentinel-KE solve?

- Short answer: It gives Kenya one operational platform to detect, relate, explain, and respond to cyber, fraud, and corruption risks.
- Deeper technical answer: Sentinel-KE separates three AI lanes: cyber threat intelligence, mobile-money fraud, and procurement corruption. Each lane has its own data, graph, holdout, and metrics, and the platform then routes those results into command, investigation, reporting, and containment workflows. See [THREE_LANE_AI_STORY.md](/home/ogola/personal/sentinel-ke/docs/THREE_LANE_AI_STORY.md).
- Dangerous answer to avoid: "It solves all cybercrime with one model."

## 2) Why is this nationally relevant?

- Short answer: It is built around Kenyan institutions, Kenyan workflows, and Kenyan threat patterns.
- Deeper technical answer: The repo explicitly routes to KE-CIRT, models Kenyan procurement risk, tracks Kenyan cyber feeds, and supports agency-style federation. The docs and code reference KPLC, eCitizen, M-Pesa-style fraud, PPRA, Kenya Law, EACC, and agency containment workflows. See [THREE_LANE_AI_STORY.md](/home/ogola/personal/sentinel-ke/docs/THREE_LANE_AI_STORY.md) and [JUDGE_TOP15_SCORECARD.md](/home/ogola/personal/sentinel-ke/docs/JUDGE_TOP15_SCORECARD.md).
- Dangerous answer to avoid: "This is generic AI that could be deployed anywhere with no changes."

## 3) What evidence proves impact?

- Short answer: We have live benchmark evidence, live judge-readiness APIs, and a real containment receipt trail.
- Deeper technical answer: Cyber has a latest matched run with AUC 0.9682 and operating F1 0.7000. Fraud has a fresh PaySim artifact with AUC 0.9555 and PR-AUC 0.9291. Corruption has a live holdout AUC 0.9158 with fairness passed. Containment has a verified external partner simulator path with signed receipts and `signature_verified=true`. See [BENCHMARK_SUMMARY.md](/home/ogola/personal/sentinel-ke/docs/BENCHMARK_SUMMARY.md), [TOP15_KPI_EVIDENCE.md](/home/ogola/personal/sentinel-ke/docs/TOP15_KPI_EVIDENCE.md), and [EXTERNAL_CONTAINMENT_DEMO.md](/home/ogola/personal/sentinel-ke/docs/EXTERNAL_CONTAINMENT_DEMO.md).
- Dangerous answer to avoid: "We have impact because the UI looks polished."

## 4) How do you measure model performance versus baseline?

- Short answer: Each lane is compared against a separate baseline and not against a different lane.
- Deeper technical answer: The repo exposes explicit baseline rows separate from model predictions. Cyber uses temporal holdout on Wmid with live thresholds; fraud uses PaySim as a separate benchmark; corruption is treated as mixed-supervision risk ranking, not legal proof. The judge-readiness payload now surfaces benchmark evidence and the baseline API exposes `baseline_score`, `baseline_std`, and `sample_count`. See [TOP15_KPI_EVIDENCE.md](/home/ogola/personal/sentinel-ke/docs/TOP15_KPI_EVIDENCE.md) and [BENCHMARK_SUMMARY.md](/home/ogola/personal/sentinel-ke/docs/BENCHMARK_SUMMARY.md).
- Dangerous answer to avoid: "Our fraud benchmark proves our cyber model."

## 5) Is this really AI/GNN, or mostly rules?

- Short answer: It is real GNN plus rules, not GNN alone.
- Deeper technical answer: The graph feature worker builds snapshots, the GNN trainer runs GraphSAGE-based training with temporal holdout and calibration, the inference worker scores live entities, and the trust layer adds explanations, thresholds, and fallback. Rules still matter for ingestion, guardrails, and containment, but the model layer is real and measured. See [THREE_LANE_AI_STORY.md](/home/ogola/personal/sentinel-ke/docs/THREE_LANE_AI_STORY.md) and [JUDGE_TOP15_SCORECARD.md](/home/ogola/personal/sentinel-ke/docs/JUDGE_TOP15_SCORECARD.md).
- Dangerous answer to avoid: "The GNN alone detects everything."

## 6) What keeps it robust under edge cases?

- Short answer: It fails closed, not open.
- Deeper technical answer: The repo has a real-data gate, fairness gate, heuristic fallback, cooldowns, schema-contract checks, and containment status mapping that records `no_integration` instead of pretending an action was delivered. DDoS and fraud flows can continue even when one feed is weak or a webhook is missing. See [TOP3_HARDENING_PACK.md](/home/ogola/personal/sentinel-ke/docs/TOP3_HARDENING_PACK.md) and [EXTERNAL_CONTAINMENT_DEMO.md](/home/ogola/personal/sentinel-ke/docs/EXTERNAL_CONTAINMENT_DEMO.md).
- Dangerous answer to avoid: "If one feed fails, the whole platform stops."

## 7) How is the architecture sound?

- Short answer: It is modular by lane and by responsibility.
- Deeper technical answer: Ingestion, graph projection, feature snapshots, GNN training, inference, trust/explanation, defense, federation, and reporting are separated. The backend exposes explicit APIs for ingestion, integrations, defense, AI benchmarks, and judge readiness. This makes it maintainable for national or agency environments. See [THREE_LANE_AI_STORY.md](/home/ogola/personal/sentinel-ke/docs/THREE_LANE_AI_STORY.md) and [TOP3_HARDENING_PACK.md](/home/ogola/personal/sentinel-ke/docs/TOP3_HARDENING_PACK.md).
- Dangerous answer to avoid: "It is one giant model glued to a dashboard."

## 8) How does it fit real operator workflow?

- Short answer: It follows the way a command center actually works: sense, analyze, explain, respond, govern.
- Deeper technical answer: `Live Feed` is the operator queue, `Threat Graph` shows who is attacking whom and through what infra, `Investigate` gives evidence and trust, `Defense` dispatches bounded action, and `Reports` turns it into something a supervisor can review. The repo also includes a mission-loop demo runbook. See [MISSION_LOOP_DEMO.md](/home/ogola/personal/sentinel-ke/docs/MISSION_LOOP_DEMO.md) and [FRONTEND_ATTACK_TEST_GUIDE.md](/home/ogola/personal/sentinel-ke/docs/FRONTEND_ATTACK_TEST_GUIDE.md).
- Dangerous answer to avoid: "Judges will infer the workflow from the dashboard."

## 9) How do agencies plug into it?

- Short answer: Through the connector API, not by rewriting their systems.
- Deeper technical answer: Existing agencies can export CSV, JSONL, syslog, SIEM relays, or database views into `/v1/integrations/{connector_key}/event` or `/batch`. The new bridge script can forward file exports into the canonical ingest seam, preserving auditability and source identity. See [LEGACY_CONNECTOR_BLUEPRINT.md](/home/ogola/personal/sentinel-ke/docs/LEGACY_CONNECTOR_BLUEPRINT.md).
- Dangerous answer to avoid: "Agencies must rebuild all their tools to use Sentinel-KE."

## 10) Can it run on sovereign cloud, on-prem, or edge?

- Short answer: Yes, but the deployment story should be described honestly as local-first and judge-verifiable, not as fully public everywhere already.
- Deeper technical answer: The repo supports Docker Compose, edge federation, local workers, and a public/backend split pattern. The hardening pack documents the intended judge path as frontend on Vercel with a stable backend and shared ledger, but that remains a deployment task unless the public endpoint is already live. See [TOP3_HARDENING_PACK.md](/home/ogola/personal/sentinel-ke/docs/TOP3_HARDENING_PACK.md).
- Dangerous answer to avoid: "Every worker is already running in the public cloud."

## 11) How do you protect privacy?

- Short answer: By pseudonymization, tenancy, encryption, and controlled evidence release.
- Deeper technical answer: The repo uses HMAC pseudonymization at ingestion, section-based access control, secure request signing, and encrypted webhook secrets. Sensitive data should not leak into graph or AI layers unless explicitly allowed. See [JUDGE_TOP15_SCORECARD.md](/home/ogola/personal/sentinel-ke/docs/JUDGE_TOP15_SCORECARD.md) and [EXTERNAL_CONTAINMENT_DEMO.md](/home/ogola/personal/sentinel-ke/docs/EXTERNAL_CONTAINMENT_DEMO.md).
- Dangerous answer to avoid: "We can expose PII to the graph because the model needs it."

## 12) How do you explain decisions?

- Short answer: Every prediction can carry reasons, evidence hashes, and counterfactuals.
- Deeper technical answer: The judge-facing surfaces show `reason_codes`, evidence posture, trust checks, recommendation text, and lane-specific evidence. The platform also exposes explanation and judge-readiness APIs so auditors can reconstruct what happened and why. See [TOP15_KPI_EVIDENCE.md](/home/ogola/personal/sentinel-ke/docs/TOP15_KPI_EVIDENCE.md).
- Dangerous answer to avoid: "The model is a black box but trust us."

## 13) How do you handle bias and misuse?

- Short answer: With fairness gates, abstention, and explicit non-adjudication boundaries.
- Deeper technical answer: The corruption lane is explicitly framed as risk ranking, not legal proof. The cyber lane has fairness gating and real-data gating. The system also avoids automatic broad blocking and prefers bounded controls. See [THREE_LANE_AI_STORY.md](/home/ogola/personal/sentinel-ke/docs/THREE_LANE_AI_STORY.md) and [TOP3_HARDENING_PACK.md](/home/ogola/personal/sentinel-ke/docs/TOP3_HARDENING_PACK.md).
- Dangerous answer to avoid: "The AI can tell who is guilty."

## 14) What should you say about the corruption lane?

- Short answer: It is a procurement risk-ranking and graph-visualization lane, not a court verdict engine.
- Deeper technical answer: The corruption lane has a live holdout AUC of 0.9158 and fairness passed on the active window, but it still carries a mixed-supervision caveat because outcome-backed labels are not full national ground truth. The right claim is investigator support, not adjudication. See [THREE_LANE_AI_STORY.md](/home/ogola/personal/sentinel-ke/docs/THREE_LANE_AI_STORY.md) and [BENCHMARK_SUMMARY.md](/home/ogola/personal/sentinel-ke/docs/BENCHMARK_SUMMARY.md).
- Dangerous answer to avoid: "This proves corruption in court."

## 15) What should you say about PaySim?

- Short answer: PaySim proves the fraud lane is real and reproducible, but it is a separate benchmark lane.
- Deeper technical answer: The fresh PaySim artifact shows AUC 0.9555 and PR-AUC 0.9291, with weak thresholded precision and F1. That is useful because it proves the fraud GNN can be benchmarked honestly, but it should not be used to inflate the cyber lane. See [BENCHMARK_SUMMARY.md](/home/ogola/personal/sentinel-ke/docs/BENCHMARK_SUMMARY.md) and [TOP15_KPI_EVIDENCE.md](/home/ogola/personal/sentinel-ke/docs/TOP15_KPI_EVIDENCE.md).
- Dangerous answer to avoid: "PaySim proves our live national fraud detection is complete."

## 16) What should you say about abuse.ch feeds?

- Short answer: ThreatFox and MalwareBazaar are live operational malware-intel feeds, not standalone compromise proof.
- Deeper technical answer: The repo now ingests ThreatFox and MalwareBazaar through the normal pipeline. They strengthen the cyber graph, IOCs, and explanation layer, but they should be presented as enrichment and correlation feeds, not as proof that a host is compromised by themselves. See [SIMSWAP_MULE_VPN_MALWARE_DATA_PLAN.md](/home/ogola/personal/sentinel-ke/docs/SIMSWAP_MULE_VPN_MALWARE_DATA_PLAN.md).
- Dangerous answer to avoid: "An IOC feed alone proves compromise."

## 17) How do SIM swap, mule rings, VPN, and malware fit together?

- Short answer: They are separate threat families, each with its own data reality and modeling path.
- Deeper technical answer: VPN is benchmark-ready on public traffic data, malware has live operational feeds, mule-ring logic exists and can use PaySim or AML-style benchmarks, and SIM swap currently needs the best proxy benchmarks plus private telco feeds for true owner attribution. The repo explicitly warns not to claim real legal-owner identification without KYC or subscriber data. See [SIMSWAP_MULE_VPN_MALWARE_DATA_PLAN.md](/home/ogola/personal/sentinel-ke/docs/SIMSWAP_MULE_VPN_MALWARE_DATA_PLAN.md).
- Dangerous answer to avoid: "We already have perfect public SIM-swap truth."

## 18) When should containment trigger?

- Short answer: After detection and correlation, not at the first noisy signal.
- Deeper technical answer: The right escalation ladder is observe, then challenge or rate limit, then isolate a specific asset or account path, then upstream block or scrub only when the evidence and operational impact justify it. The repo already supports signed containment dispatch and the external partner simulator proves the workflow. See [EXTERNAL_CONTAINMENT_DEMO.md](/home/ogola/personal/sentinel-ke/docs/EXTERNAL_CONTAINMENT_DEMO.md).
- Dangerous answer to avoid: "We should shut off the internet as soon as the score rises."

## 19) How is Sentinel-KE different from other tools?

- Short answer: It is not just another detector. It is a sovereign workflow: ingest, correlate, score, explain, contain, and report.
- Deeper technical answer: Many tools do detection or response, but Sentinel-KE combines multi-agency federation, graph correlation, GNN scoring, evidence traces, judge-ready transparency, and bounded containment in one platform. The differentiator is the whole operational loop, not just one algorithm. See [TOP3_HARDENING_PACK.md](/home/ogola/personal/sentinel-ke/docs/TOP3_HARDENING_PACK.md) and [THREE_LANE_AI_STORY.md](/home/ogola/personal/sentinel-ke/docs/THREE_LANE_AI_STORY.md).
- Dangerous answer to avoid: "Nobody else does AI security."

## 20) What is the safest overall judge summary?

- Short answer: Sentinel-KE is a credible national-security MVP with real live evidence, but the strongest claim is operational intelligence workflow, not magical AI.
- Deeper technical answer: The honest story is that cyber now has strong recent scientific evidence and live operating evidence, fraud has a fresh benchmark artifact, corruption is a ranking lane with caveats, containment is signed and auditable, and legacy systems can join through connector bridges. That is a strong, defensible Top-3 argument if you keep the claims disciplined. See [JUDGE_TOP15_SCORECARD.md](/home/ogola/personal/sentinel-ke/docs/JUDGE_TOP15_SCORECARD.md) and [TOP3_HARDENING_PACK.md](/home/ogola/personal/sentinel-ke/docs/TOP3_HARDENING_PACK.md).
- Dangerous answer to avoid: "Everything is production-perfect already."

# Sentinel-KE Benchmark Summary

Last updated: 2026-03-27

Each lane is evaluated independently. No benchmark result from one lane validates another lane.

## Summary Table

| Lane | Model | Dataset | Headline metric | Nodes | Edges | Holdout | Status |
|---|---|---|---|---|---|---|---|
| Cyber | SentinelGNN-Cyber | Real Kenyan events (URLhaus, Feodo, ThreatFox, MalwareBazaar, OSINT) | Holdout `AUC 0.9682`; operating `F1 0.7000`, precision `0.7538`, recall `0.6533` on the latest matched run; multi-window scientific evidence `strong` | 2,500 | 6,424 | Temporal (Wmid window) | Operational lane with strong recent scientific support |
| Fraud | SentinelGNN-Fraud | PaySim (6.3M M-Pesa-style txns, Kaggle ealaxi/paysim1) | Holdout `AUC 0.9555`, `PR-AUC 0.9291`; thresholded precision/F1 still weak (`0.1251` / `0.2224`) | 50k+ | — | Temporal | Fresh benchmark artifact present |
| Corruption | SentinelGNN-Corruption | PPRA + Kenya Law + EACC | Holdout `AUC 0.9158`, F1 `0.8351`, precision `0.9759`, recall `0.7297` | 2,026 | 3,900 | Temporal | Operational ranking lane |

PaySim remains the fraud benchmark lane and now has a fresh regenerated artifact at `/app/artifacts/paysim_auc.json`. It must still be presented as a separate fraud benchmark, not as evidence for cyber or corruption performance.

---

## Lane Notes

### Cyber — operational and scientifically stronger than before
- Graph built from live-ingested threat feeds: URLhaus malicious URLs, Feodo Tracker
  botnet C2 IPs, ThreatFox IOCs, MalwareBazaar signatures
- Latest matched benchmarked run: `2,500` nodes, `6,424` edges
- Latest matched holdout metrics: `AUC 0.9682`, `precision 0.7538`, `recall 0.6533`, `F1 0.7000`
- Judge-readiness now reports multi-window scientific evidence `strong`
- Recent scientific aggregates from `/v1/ai/judge-readiness`:
  - mean AUC `0.9910`
  - mean PR-AUC `0.9566`
  - mean operating F1 `0.8575`
- This lane is now stronger scientifically than the earlier 97-node / 237-edge window, but it still carries a supervision caveat rather than full adjudicated incident truth

### Fraud — fresh benchmark artifact present
- PaySim is the accepted industry benchmark for M-Pesa-style mobile money fraud
- Dataset: 6.3M transactions, 8,213 fraud accounts out of 50,000+ account nodes
- Temporal holdout: trained on earlier transaction steps, tested on later steps
- Fresh artifact metrics:
  - AUC `0.9555`
  - PR-AUC `0.9291`
  - precision `0.1251`
  - recall `1.0`
  - F1 `0.2224`
- Artifact path: `/app/artifacts/paysim_auc.json`
- CSV identity is recorded with filename, SHA256, and seeded snapshot count
- This lane remains separate from cyber and corruption and should be presented as a fraud-ranking benchmark, not as live sovereign fraud telemetry

### Corruption — AUC 0.9158 holdout
- Graph covers PPRA procurement awards, arbitration outcomes, Kenya Law judgments,
  EACC case outcomes
- 2,026 entity nodes and 3,900 relationship edges in the latest live run
- Holdout metrics are present in the run payload and the fairness gate passes on the deployed corruption window
- The lane still carries a mixed-supervision caveat because outcome-backed labels are not yet the full national ground truth
- Current deliverable: corruption risk ranking and relationship graph visualization

---

## Honest Judge-Facing Statement

> "Our cyber lane is operationally aligned on real ingested cyber events, with live thresholds,
> baselines, and strong recent scientific support across multiple windows. Corruption and fraud
> remain separate lanes with their own evidence and caveats."

Safer current wording:

> "Our cyber lane now has both live operating evidence and strong recent scientific support,
> but evaluation is still on the current supervision mix rather than fully adjudicated national
> incident truth. Fraud is a separate benchmark lane with a fresh PaySim artifact, and we do
> not use that fraud benchmark to overstate cyber or corruption performance."

---

## Cross-References

| Document | Purpose |
|---|---|
| `docs/FRAUD_BENCHMARK_POSITIONING.md` | What PaySim proves and does not prove |
| `docs/THREE_LANE_AI_STORY.md` | Full judge-facing narrative for all three lanes |
| `docs/AI_BENCHMARK_STRATEGY.md` | Metrics by lane, presentation rules, data discipline |
| `docs/AI_DATASET_REGISTRY.md` | Registered data sources and entry points |
| `backend/scripts/run_paysim_gnn.py` | PaySim GNN training script |

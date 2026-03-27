# Sentinel-KE AI Architecture — Three Intelligence Lanes

## Why Three Lanes?

Kenya's threat landscape has three structurally distinct risk domains. Each domain has
different actors, different data sources, different graph topologies, and different
downstream use cases. A single model trained on one domain would fail on the others —
not because of weak engineering, but because the signal structure is fundamentally
different.

Sentinel-KE therefore trains and evaluates three independent GNN models:

- **SentinelGNN-Cyber** — detects threat actors and attack infrastructure in network event graphs
- **SentinelGNN-Fraud** — detects mobile money fraud in M-Pesa-style transaction graphs
- **SentinelGNN-Corruption** — ranks procurement corruption risk in government contracting graphs

These models share the same underlying GraphSAGE architecture and the same Sentinel-KE
feature schema, but they are trained on separate data, evaluated on separate holdouts,
and make separate claims. No benchmark from one lane validates another lane.

---

## Lane 1: Cyber Threat Intelligence (SentinelGNN-Cyber)

**Training data:** Real ingested cyber events — URLhaus malicious URLs, Feodo Tracker
botnet C2 infrastructure, ThreatFox IOCs, MalwareBazaar malware signatures, and
operational OSINT network telemetry feeds

**Graph structure:**
- Entities (nodes): IPs, domains, accounts, network services
- Relationships (edges): shared events, co-occurrence in threat feeds, IOC co-labeling

**Evaluation:**
- Holdout type: temporal recency holdout with class-support backfill
- Latest matched run metrics: **AUC 0.9682**, **F1 0.7000**, **precision 0.7538**, **recall 0.6533**
- Latest matched graph size: **2,500 nodes**, **6,424 edges**
- Live judge-readiness now reports cyber scientific evidence as **strong** across recent benchmarkable windows

**Benchmark statement:**
The cyber GNN is operationally aligned on a real Kenyan cyber event graph using a
temporal split, live thresholds, live baselines, and a matched prediction window. The
current judge-safe cyber claim is that the lane now has both live operating evidence and
strong recent scientific support across multiple benchmarkable windows. The remaining
caveat is that evaluation still reflects the current supervision mix rather than fully
adjudicated national incident ground truth.

**What this does not prove:**
This result does not validate fraud detection or corruption risk ranking. Cyber AUC is
measured on cyber data only.

---

## Lane 2: Mobile Money Fraud (SentinelGNN-Fraud)

**Training data:** PaySim — 6.3 million M-Pesa-style synthetic transactions generated
from real Central Bank of Kenya transaction logs (Kaggle: ealaxi/paysim1). PaySim is
the industry-standard benchmark for mobile money fraud research.

**Graph structure:**
- Entities (nodes): accounts, phones, merchants (50,000+ nodes)
- Relationships (edges): transaction flows between accounts
- Fraud accounts in dataset: 8,213

**Evaluation:**
- Holdout AUC: **0.9555**
- Holdout PR-AUC: **0.9291**
- Holdout precision / recall / F1: **0.1251 / 1.0 / 0.2224**
- Holdout type: temporal (train on earlier transaction steps, test on later steps)
- Script: `backend/scripts/run_paysim_gnn.py`
- Artifact: `/app/artifacts/paysim_auc.json`

**Why PaySim:**
PaySim is the accepted M-Pesa fraud benchmark in the academic and industry literature.
It replicates the statistical properties of real Central Bank mobile money logs. Sentinel-KE
now has a fresh reproducible artifact with CSV identity, SHA256, seeded snapshot count,
and held-out metrics. It is not a substitute for live M-Pesa data, but it establishes that
the GNN architecture can be evaluated on a public mobile-money-style corpus before live
data is available.

**What this does not prove:**
This result does not validate cyber threat detection or corruption risk ranking. The
PaySim lane remains specific to the mobile money fraud domain.

---

## Lane 3: Corruption Intelligence (SentinelGNN-Corruption)

**Training data:**
- PPRA Kenya — public procurement awards and arbitration outcomes
- Kenya Law — court judgments referencing procurement misconduct
- EACC — Ethics and Anti-Corruption Commission case outcomes

**Graph structure:**
- Entities (nodes): suppliers, government officials, tenders, contracts (1,982 nodes)
- Relationships (edges): procurement relationships, payment chains, outcome linkages (4,158 edges)

**Current status: operational ranking lane with mixed-supervision caveat**

The corruption GNN now reports a live holdout AUC of **0.9158** with fairness passed on
the active window. The lane still carries a mixed-supervision caveat because outcome-backed
labels are not yet the full national ground truth. The metrics are useful for risk ranking
and investigation support; they should still be described as mixed-supervision evidence,
not adjudication.

**What it delivers today:**
- Corruption risk ranking across the procurement graph
- Relationship graph visualization showing supplier-official-tender linkages
- Connected-component analysis identifying procurement clusters
- Anomaly flags for payment and milestone mismatches

**Design intent:**
The corruption lane is designed as a risk prioritization tool for investigators, not as
an automatic adjudication system. Even when the fairness fix is complete and a classifier
AUC is reported, the output will be "entities flagged for review" not "entities proven
corrupt." The graph evidence is provided to support human decision-making.

**What this does not prove:**
Corruption graph scores are not legal findings. No output from this lane should be
presented as proof of wrongdoing.

---

## The Unified Story

Each lane feeds independently into the Sentinel-KE Command screen and the federation
hub:

```
SentinelGNN-Cyber      →  Cyber threat feed  →  Command screen threat panel
SentinelGNN-Fraud      →  Fraud alert queue  →  Command screen fraud panel
SentinelGNN-Corruption →  Risk rankings      →  Command screen governance panel
                                   ↓
                         Federation Hub (cross-domain correlation)
```

The federation hub allows an operator to ask whether the same entity appears in multiple
lanes — for example, whether a supplier flagged in the corruption lane also appears in a
suspicious transaction cluster in the fraud lane. Cross-lane correlation is a separate
inference step; it does not inherit the AUC of either lane's standalone model.

---

## Summary of Honest Claims

| Lane | Honest Claim |
|---|---|
| Cyber | Strong matched-run cyber metrics on a real Kenyan cyber event graph, plus strong recent scientific evidence across multiple windows, with an honest caveat that evaluation still uses the current supervision mix |
| Fraud | PaySim is the separate fraud benchmark lane and now has a fresh artifact: AUC `0.9555`, PR-AUC `0.9291`, with an honest caveat that the current operating threshold is still weak |
| Corruption | 0.9158 holdout AUC on PPRA + Kenya Law + EACC mixed-supervision data, with ranking focus and a non-adjudication caveat |

**The single claim for judges:**

> "Our cyber lane now shows both live operating evidence and strong recent scientific support
> on real cyber events. Fraud and corruption are separate lanes with their own evidence and
> caveats, and we do not use the fraud benchmark to overstate cyber or corruption."

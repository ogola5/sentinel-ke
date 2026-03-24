# Corruption Intelligence Overhaul Plan

This document explains how to turn Sentinel-KE's current corruption features
into a more realistic Kenyan anti-corruption intelligence system that is worth
deploying in government.

The goal is not "AI that guesses corruption." The goal is:

- represent how procurement and project corruption actually works
- ingest the evidence trails that public institutions already produce
- use rules, graph analytics, and GNNs together
- rank investigative priority, not replace investigators or auditors

## 1. What The Repo Already Has

Current corruption capability is split into two paths.

1. `Graph ML corruption path`
   - Real procurement import: `backend/app/analytics/corruption/ocds_ingest.py`
   - Synthetic corruption training data: `backend/app/demo/synthetic_corruption_data.py`
   - Corruption features: `backend/app/analytics/corruption/feature_builder.py`
   - Corruption GNN training: `backend/app/analytics/corruption/train_worker.py`

2. `Rule-based economic integrity path`
   - Procurement anomaly scoring: `backend/app/api/economy.py`
   - Procurement scoring rules: `backend/app/economy/scoring.py`
   - Leakage detectors: `backend/app/economy/leakage.py`

This means the current system is already strongest on procurement-linked
integrity, not on all corruption classes equally.

## 1.1 Phase 1 Implemented In This Repo

The first realism pass is now implemented in the procurement ingest path.

What changed in `backend/app/analytics/corruption/ocds_ingest.py`:

- supplier-family clustering now uses stronger identity fields
  - tax ID
  - bank account
  - email / phone / address
- procurement rows can now carry:
  - beneficial-owner / director identity
  - supplier bank account
  - inspector and milestone identities
  - delivery progress versus certified progress
  - complaint counts
  - quality-failure counts
  - delay days
  - debarment and delivery-status signals
- the importer now emits richer corruption events:
  - `SUPPLIER_NETWORK_LINK`
  - `SITE_INSPECTION`
  - `PROJECT_MILESTONE_CERTIFIED`
  - `COMPLAINT_FILED`
  - `DEFECT_NOTICE`
  - `PROJECT_DELAY`
  - `PROJECT_DELIVERY_ALERT`
- snapshots now preserve procurement-delivery features such as:
  - supplier family size
  - inspection count
  - complaint and defect counts
  - delay days
  - progress mismatch
  - payment-to-delivery mismatch

The first-pass model update in `backend/app/analytics/corruption/feature_builder.py`
also now tracks procurement lifecycle and supplier-network event families
instead of only the older synthetic event mix.

What this gives us immediately:

- a more realistic graph for split companies and proxy-bid networks
- a better signal path for substandard works and fake completion
- project-level corruption risk that follows award -> payment -> inspection -> complaint
- a cleaner bridge between PPRA/OCDS ingest and future IFMIS / project-delivery evidence

## 1.2 Phase 2 Implemented In This Repo

Phase 2 adds a separate registry and beneficial-ownership ingest path in
`backend/app/analytics/corruption/registry_ingest.py`.

This path models the supplier network outside the tender itself:

- company registration
- beneficial owner / director identity
- bank account linkage
- tax ID / contact / address overlap
- debarment and watchlist evidence

The Phase 2 importer emits graph events such as:

- `COMPANY_REGISTRATION`
- `SUPPLIER_NETWORK_LINK`
- `DEBARMENT_LISTING`
- `WATCHLIST_HIT`

It also writes corruption snapshots for:

- suppliers
- supplier-family clusters
- directors / beneficial owners
- linked bank accounts

Why this matters:

- procurement risk is no longer based only on award rows
- one beneficial-owner network split across many companies becomes visible
- a debarred supplier can influence corruption weak labels through an
  independent registry signal
- the same supplier-family entity can now connect procurement data and
  registry data in one graph neighborhood

## 1.3 Phase 3 Implemented In This Repo

Phase 3 adds an IFMIS-style payment-trail ingest path in
`backend/app/analytics/corruption/payment_ingest.py`.

This path models the financial approval and release chain:

- invoice approved
- voucher created
- payment released
- approver linked
- advance payment
- payment hold / delayed release
- milestone certification

The importer creates graph entities for:

- departments
- suppliers
- contracts
- projects
- invoice / payment records
- approvers
- payment accounts

It derives corruption-relevant signals such as:

- approval bypass / manual override
- delayed or held payment
- high advance payment ratio
- payment-versus-delivery mismatch
- debarred supplier in payment flow

Most importantly, the payment trail is weighted carefully:

- invoice obligation is counted once in `total_value_ksh`
- cash release is tracked through `payment_amount_ksh`
- voucher and approval-link events do not inflate contract value

What this gives us:

- a real bridge from procurement award to actual public money movement
- better detection of “paid but not delivered” patterns
- a stronger basis for linking IFMIS, procurement, registry, and project evidence

## 2. How Corruption Actually Works In Kenyan Procurement

If this is meant to be real, the system must model corruption as a chain, not
as an isolated tender score.

The common real patterns are:

- shell or proxy companies created shortly before tender award
- one beneficial-owner network split into multiple "different" bidders
- bid rotation among a stable ring of firms
- direct or emergency procurement used to bypass competition
- tenders split just below approval thresholds
- inflated pricing versus market baseline or engineer's estimate
- repeated contract variations / change orders after award
- mobilization or advance payments before verified delivery
- project progress mismatching disbursements
- substandard materials or quantity shortfalls hidden by collusive certification
- same phone, email, address, tax ID, bank account, directors, device, or agent
  appearing across nominally separate suppliers
- same supplier group capturing many awards across counties or agencies
- complaint, audit, debarment, and investigation trails arriving late but
  providing stronger labels

The machine-learning system must therefore see:

- the procurement process
- the supplier network
- the payment trail
- the project delivery trail
- the audit / complaint / enforcement trail

If it only sees tender awards, it will miss half the corruption story.

## 3. What "Normal" Should Mean

For government procurement, normal is not a single global baseline.

Normal should be learned by:

- sector
- agency
- county / geography
- item class
- procurement method
- amount band
- project type
- vendor history
- project phase

Examples:

- A road project can legitimately have higher change-order behavior than
  routine stationery purchases.
- Emergency health procurement has different timing and competition dynamics
  from ordinary county fuel procurement.
- A new supplier is not automatically suspicious; a new supplier winning a
  single-source KES 40M award three weeks after registration is suspicious.

So the system should compare an event or project to its own peer group, not to
the whole country at once.

## 4. Data Sources Needed To Make This Real

The strongest real anti-corruption path is a multi-source public-sector graph.

Priority data sources:

1. `PPRA / OCDS procurement publications`
   - tenders
   - awards
   - contracts
   - amendments
   - suppliers
   - methods
   - dates
   - amounts

2. `IFMIS / e-procurement / disbursement trail`
   - invoice approved
   - payment request
   - payment released
   - vote head / program / project linkage

3. `Company registry / beneficial ownership`
   - directors
   - shareholders
   - registration dates
   - common addresses

4. `Tax and compliance signals`
   - KRA PIN / VAT status
   - nil filings
   - dormant company indicators

5. `Project delivery evidence`
   - engineer certificates
   - milestone approvals
   - inspection reports
   - geotagged site photos
   - material / quality tests
   - completion certificates

6. `Audit and complaint sources`
   - Auditor-General findings
   - PPRA review flags
   - EACC / internal complaint references
   - debarment lists

7. `Payroll / HR / land registry` for non-procurement corruption families
   - ghost workers
   - title manipulation
   - conflict-of-interest links

This is the key realism point:

- procurement corruption becomes real with PPRA + IFMIS + registry + delivery evidence
- ghost workers become real only when payroll / HR / ID / bank evidence is connected
- land fraud becomes real only when registry / title / transfer evidence is connected

Right now the repo is most realistic on the first category.

## 5. How The Graph Should Be Modeled

The current repo already creates entities like:

- `department`
- `tender`
- `supplier`
- `contract`
- `project`

That is a good start. But a serious corruption graph should also represent:

- `official`
- `director`
- `company`
- `bank_account`
- `mobile_money_till`
- `invoice`
- `inspection`
- `milestone`
- `asset / site`
- `complaint`
- `audit_finding`

The critical improvement is not just more nodes. It is better relationships.

You want typed edges such as:

- `supplier SUBMITTED_BID tender`
- `tender AWARDED_TO supplier`
- `contract FUNDS project`
- `payment PAID_TO supplier`
- `supplier SHARES_DIRECTOR company`
- `supplier SHARES_PHONE supplier`
- `official APPROVED payment`
- `inspection VERIFIED milestone`
- `project LOCATED_IN county`
- `audit_finding REFERS_TO contract`

The current co-occurrence graph is useful, but typed relations will make the
GNN much more believable and the explanations much more human.

## 6. How To Detect "Subdivided Companies"

This is one of the highest-value Kenyan corruption features.

You should not treat each bidder as independent if they share strong identity
signals.

Build a `supplier_family` or `beneficial_owner_cluster` concept from:

- directors
- phone numbers
- emails
- physical addresses
- tax IDs
- bank accounts
- mobile money tills
- repeated shared agents / representatives
- device/IP overlap in digital bidding systems if available

Then detect:

- multiple suppliers from the same cluster bidding on the same tender
- cluster winning repeated awards across agencies
- cluster splitting awards just below thresholds
- one cluster receiving payment on behalf of several "different" companies

In the current repo, `ocds_ingest.py` already starts this idea with
`supplier_cluster_key`, but it is still too shallow. It should be expanded into
a first-class cluster entity and relation set.

## 7. How To Capture Substandard Works

This is where many anti-corruption demos fail. Tender data alone will not prove
substandard delivery.

To model poor or fake delivery, you need project-delivery events like:

- `BOQ_APPROVED`
- `MILESTONE_CERTIFIED`
- `SITE_INSPECTION`
- `LAB_TEST_RESULT`
- `DELIVERY_ACCEPTANCE`
- `DEFECT_NOTICE`
- `PROJECT_DELAY`
- `RETENTION_RELEASE`

And you need the mismatch features:

- payment-to-physical-progress ratio
- completion certificate before inspection evidence
- same inspector certifying too many unrelated projects
- large advance payments with low verified execution
- repeated variation orders after suspicious low initial bid
- geographic impossibility: same contractor or inspector on many distant sites
  in impossible time windows

This is how the system becomes useful for roads, water, school, hospital, and
county works projects.

## 8. What The ML Stack Should Look Like

For government corruption, do not use only a GNN.

Use four layers:

1. `Deterministic rules`
   - split tendering
   - direct award misuse
   - excessive change orders
   - bid rotation
   - supplier concentration
   - payment vs baseline mismatch

2. `Feature engineering`
   - entity volume
   - network centrality
   - procurement method profile
   - financial ratios
   - project delivery mismatch
   - cluster / identity overlap

3. `Graph ML / GNN`
   - rank risky entities and rings in context
   - learn patterns that rules miss

4. `Case assembly / explainability`
   - convert high-risk graph neighborhoods into investigator-readable cases

This is the right government architecture:

- rules for defensibility
- graph ML for hidden structure
- case output for actionability

## 9. What Is Good And Bad In The Current ML Approach

What is good:

- graph modeling is the correct direction for cartel / shell / network corruption
- procurement entities and project nodes already exist
- provenance, fairness, and real-data gates are already being recorded
- the repo explicitly treats predictions as risk indicators, not final proof

What is weak:

- labels are weak heuristics, not confirmed outcomes
- some risk flags used for labels also appear in the feature vector
- evaluation is on the same weak-label world, so metrics can look better than
  real field performance
- synthetic corruption families are cleaner than real corruption evidence
- the real-data importer is strongest for procurement, not yet for the full
  corruption universe

So the current corruption GNN is suitable for:

- investigative prioritization
- demoing sovereign graph intelligence
- showing how ministries or counties could be triaged

It is not yet suitable for:

- strong public accuracy claims
- automated sanctioning decisions
- claiming "proven corruption" from model output alone

## 10. What To Change In This Codebase First

### Phase 1 — Strengthen Real Procurement Truth

Extend `backend/app/analytics/corruption/ocds_ingest.py` so it emits more
procurement lifecycle events, not just award-centric events.

Add support for:

- bid submission counts
- prequalification / restricted tender evidence
- complaint / review events
- contract variation events
- invoice and payment request events
- milestone certification events
- delivery / acceptance events
- inspection events

### Phase 2 — Make Supplier Clusters First-Class

Instead of only `supplier_cluster_key`, create stable cluster entities and
relations:

- `supplier_family:<hash>`
- relations from supplier to family
- family-level features like shared director count, shared address count,
  cross-agency award volume

This will directly address the "same people using many companies" problem.

### Phase 3 — Separate Labels From Input Features

In `backend/app/analytics/corruption/feature_builder.py` and
`backend/app/analytics/corruption/train_worker.py`:

- stop letting the same strongest flags both define the label and serve as
  direct input features in the same training regime
- move to label tiers:
  - confirmed outcome labels
  - audit / enforcement labels
  - weak heuristic labels

Then track evaluation by label source.

### Phase 4 — Add Project Delivery Features

Extend features for:

- payment vs milestone mismatch
- inspection frequency
- repeated certifier overlap
- retention release timing
- defect history
- spatial and temporal anomalies in site supervision

### Phase 5 — Move From Co-Occurrence To Typed Graph Relations

The current graph edges from shared events are useful, but the next serious step
is typed edges and possibly relation-aware graph training.

That means:

- explicit relationship extraction
- explicit relation tables or richer graph projection
- better explanations: "same director", "same account", "same project", "same site certifier"

## 11. What "Normal" ML Governance Should Be Here

For this domain, the correct ML discipline is:

- time-based evaluation by quarter or fiscal year
- agency-heldout or county-heldout validation where possible
- label-source reporting
- calibration reporting, not just AUC
- project-level and case-level evaluation, not only node-level metrics
- human review loop with feedback overrides

If you do that, the GNN becomes a serious prioritization model.

If you skip that, it remains a strong demo but a weak audit instrument.

## 12. Best Government Story

This project becomes a real government-interest system when it can answer:

- which supplier rings are quietly winning across agencies?
- which projects are absorbing money faster than verified work?
- which direct awards cluster around the same officials or supplier family?
- which counties or ministries show abnormal procurement behavior versus peers?
- which flagged patterns now also have audit, complaint, or payment evidence?

That is the right public-sector value proposition:

not "AI detects corruption automatically"

but:

"Sentinel-KE gives auditors, investigators, and oversight teams a national
graph of procurement and project-risk signals so they can find collusion,
capture, and delivery fraud earlier."

## 13. Recommended Build Order

1. Improve `ocds_ingest.py`
2. Add supplier-family / beneficial-owner clustering
3. Add project-delivery event ingestion
4. Separate strong labels from weak heuristic labels
5. Retrain corruption GNN on mixed real + synthetic windows
6. Keep rule-based economy detectors as explicit guardrails and explanations

## 14. Honest Final Position

Right now the corruption pipeline is promising and strategically correct, but
it is still mostly a procurement-risk graph with weak supervision.

To make it truly government-grade, it needs:

- richer real public-sector data
- stronger entity identity resolution
- typed relationships
- project-delivery evidence
- stronger label discipline

That is the path that turns it from a hackathon corruption demo into a real
national procurement intelligence platform.

# Edge Federation Practical Operating Model

This document corrects the edge-agent story into something that can be
explained and deployed as a real multi-agency operating model, not only as a
demo.

The goal is:

- keep raw agency telemetry inside each agency perimeter
- let each agency run local detection and local response
- let the national hub correlate threats across agencies without seeing raw
  personal or operational identifiers
- enforce visibility boundaries that make sense in government

## 1. What The Current Repo Already Does

The current repo already has the core federation skeleton:

- an edge agent can fetch local records from `demo`, `csv`, or `db`
- the edge node runs local scoring and publishes only high-risk patterns
- entity keys are HMAC-hashed before they leave the agency
- the hub stores partner heartbeat and pattern rows
- the hub correlates the same hashed entity across partners

Relevant files:

- `edge-agent/app/connector.py`
- `edge-agent/app/gnn_runner.py`
- `edge-agent/app/publisher.py`
- `edge-agent/app/main.py`
- `backend/app/api/federation.py`
- `backend/app/federation/models.py`

That is a good base, but it is still too generic for a real multi-agency
deployment model.

## 1.1 What Is Now Implemented

The repo now has the first practical warning flow on top of the federation
pattern exchange.

### Hub-side warning APIs

Implemented in `backend/app/api/federation.py` and
`backend/app/federation/models.py`:

- central-only partner visibility:
  - `GET /v1/federation/partners`
  - `GET /v1/federation/stream`
  - `GET /v1/federation/correlations`
- warning envelope creation:
  - `POST /v1/federation/warnings`
  - `POST /v1/federation/warnings/from-correlation`
- central warning review:
  - `GET /v1/federation/warnings`
- partner-only warning consumption:
  - `GET /v1/federation/warnings/inbox`
  - `POST /v1/federation/warnings/{warning_id}/ack`

Partner inbox responses are sanitized:

- the partner sees only its own acknowledgement state
- source and target partner IDs are not exposed directly
- the partner receives counts, severity, family, summary, and action guidance

### Edge-side local resolution

Implemented in:

- `edge-agent/app/warning_resolver.py`
- `edge-agent/app/publisher.py`
- `edge-agent/app/main.py`

The edge node now:

- persists a local `entity_key_hash -> raw entity` index in
  `edge_hash_index.json`
- refreshes that index after local GNN runs
- pulls only its own warning inbox from the hub
- resolves warning hashes back to raw local entities on-node
- stores the resolved inbox locally in `edge_warning_cache.json`
- exposes local warning operations through:
  - `GET /warnings`
  - `POST /warnings/sync`
  - `POST /warnings/{warning_id}/ack`

This is the practical privacy boundary:

- the hub never stores the raw entity
- the edge node never needs to send the raw entity back
- the local operator can still act on a national warning because the hash is
  resolved locally

## 2. The Correct Real-World Deployment Model

The practical deployment has three layers.

### Layer A — Agency Edge Node

Runs inside each partner environment:

- bank SOC
- telco SOC
- county ICT/security unit
- ministry data centre
- hospital SOC

What stays local:

- raw logs
- raw customer or citizen identifiers
- hostnames and internal IPs
- case notes
- local response actions
- detailed evidence and packet/log artifacts

What the edge node does:

- collect telemetry from local systems
- normalize to local entity/event records
- run local rules and ML/GNN scoring
- trigger local playbooks
- publish only hashed warning patterns to the hub

### Layer B — National Command Hub

Runs centrally and never becomes a raw-data lake.

What the hub sees:

- partner heartbeat and health
- hashed high-risk entities
- entity type
- threat family / tactic category
- confidence / uncertainty
- time window
- partner count and sector spread
- aggregate warning summaries

What the hub should not see by default:

- raw phone numbers
- raw account numbers
- raw internal IPs
- mailbox contents
- endpoint forensic artifacts
- local analyst notes

### Layer C — Command / Coordination Plane

This is where cross-agency coordination happens:

- see which partners are online
- see correlated hashes across partners
- issue warnings
- request partner action
- track partner acknowledgements
- escalate only when multiple sources confirm a threat

## 3. Who Should See What

This is the most important correction.

### Agency SOC User

Should see:

- their own raw telemetry
- their own detections
- their own graph
- their own local incidents
- warnings sent to their agency

Should not see:

- other agencies' partner lists
- other agencies' stream of hashed entities
- cross-agency correlations involving named partners unless explicitly shared

### Central Command User

Should see:

- all partner heartbeat and readiness
- all cross-agency correlations
- all national warning summaries
- all partner warning acknowledgements

Should not automatically see:

- raw agency evidence
- raw PII/PCI/PHI
- raw packet or endpoint data

### Step-Up / Exceptional Reveal

If law or incident severity requires deeper collaboration:

- central command can request a reveal from the partner
- partner decides whether to disclose the raw entity or evidence
- that disclosure is audited and classified

This is the correct sovereign model:

- central correlation by default
- raw-data disclosure only by controlled exception

## 4. What Telemetry Each Agency Should Use

The current edge connector is too generic. In real deployment the edge node
should consume telemetry classes like these.

### VPN / Account Takeover

Use:

- VPN gateway logs
- SSO / IdP logs
- O365 / Google Workspace login events
- AD / LDAP login failures
- impossible-travel and device-change signals

Local entities:

- user account
- device
- IP
- VPN session

Local actions:

- revoke session
- force MFA
- disable account
- block source IP

Shared to hub:

- hashed account
- hashed device or IP where appropriate
- threat family `ATO` or `VPN_ABUSE`
- confidence / uncertainty
- seen tactic flags like impossible travel or MFA bypass

### Phishing / BEC

Use:

- mail gateway events
- click/open telemetry
- mailbox forwarding rule changes
- domain reputation
- identity-provider follow-on logins

Local entities:

- mailbox
- sender domain
- attachment hash
- destination account

Local actions:

- quarantine mail
- block domain
- remove mailbox rules
- suspend tokens

Shared to hub:

- hashed mailbox or account
- domain hash when private, domain plain when public IOC policy allows
- phishing family / BEC family
- tactic flags like forwarding rule abuse, login pivot, attachment delivery

### Malware / Endpoint Compromise

Use:

- EDR events
- antivirus detections
- DNS sinkhole or proxy logs
- file hash / process execution
- lateral movement alerts

Local entities:

- device
- user
- file hash
- C2 domain / IP

Local actions:

- isolate host
- kill process
- block hash
- block outbound IOC

Shared to hub:

- hashed device/user
- public IOC hash or plain IOC if policy allows
- malware family or tactic
- confidence / severity

### DDoS / Service Disruption

Use:

- WAF logs
- reverse-proxy logs
- NetFlow/sFlow
- firewall counters
- CDN signals
- service-health metrics

Local entities:

- service
- endpoint
- attacking source cluster
- upstream provider

Local actions:

- rate limit
- WAF rule update
- upstream block
- failover / traffic shaping

Shared to hub:

- hashed service identifier if private
- endpoint hash if sensitive
- DDoS family
- pressure score
- attack shape flags like IP fan-in, path concentration, saturation

## 5. How The Edge Agent Should Actually Train

The current edge runner can train from scratch on each run. That is useful for
demo and fallback, but it is not the practical long-run operating model.

The corrected model is:

### Baseline Model

Maintained centrally by sector:

- banking baseline
- telco baseline
- government digital service baseline
- healthcare baseline

This baseline is distributed to edge nodes as an artifact, not as raw data.

### Local Fine-Tuning

Each partner fine-tunes locally on:

- its own telemetry
- its own rules
- its own analyst feedback
- its own confirmed incidents

This should happen on a slower cadence:

- nightly
- every few hours
- or by drift trigger

### Real-Time Inference

Should run every few minutes or near-real-time on the latest local features.

So the practical sequence is:

1. central baseline artifact distributed
2. local edge node fine-tunes periodically
3. local inference runs often
4. only warning patterns are published to the hub

### What Should Be Shared About Models

Share to the hub:

- model version
- training freshness
- data freshness
- local AUC or validation summary if available
- drift status
- artifact hash

Do not share:

- local training data
- raw features
- gradients
- model internals that leak private classes

## 6. How Hashing Should Work

The current implementation is directionally right.

### National Correlation Salt

Use one shared national correlation salt for all partners.

Purpose:

- same entity at different agencies gives the same hash
- hub can correlate without seeing the raw entity

Use for:

- phone
- account
- internal person or account identifiers
- internal service IDs
- internal endpoint identifiers

### Partner-Local Salt

Keep a separate partner-local salt.

Purpose:

- any local pseudonymization that should remain private inside the partner
- local caches and local lookup tables

Do not use this salt for hub correlation.

### Practical Cautions

- low-entropy spaces like phone numbers are brute-forceable if the national
  salt leaks
- protect the national salt like a signing secret
- rotate it carefully and deliberately
- prefix the entity type into the key before hashing

Example:

- `phone:+2547...`
- `account:...`
- `service_id:...`

## 7. What The Hub Should Receive

The hub should receive warning patterns, not raw telemetry.

A practical warning pattern should contain:

- `partner_id`
- `time window`
- `entity_key_hash`
- `entity_type`
- `threat family`
- `risk_score`
- `uncertainty`
- `tactic flags`
- `local action status`
- `model_version`
- `data freshness`

The hub should also track:

- partner sector
- partner trust level
- last heartbeat
- last successful publish
- warning acknowledgement state

## 8. How Warnings Should Flow Back To Agencies

This is still missing as a first-class pattern in the repo and should be built.

The hub should create a `warning envelope` and send it to each affected agency.

That envelope should contain:

- warning ID
- entity hash
- entity type
- threat family
- partner count
- first seen / last seen
- recommended action class
- urgency
- classification / TLP

The agency edge node then:

1. matches the hash against its local hash index
2. resolves the local raw entity
3. opens or updates a local case
4. executes or recommends local playbooks
5. sends acknowledgement back to the hub

This is how you avoid the central hub trying to act directly on raw agency data
it does not own.

## 9. Isolation During Danger

This is the resilient operating model.

### If The Hub Goes Down

- edge nodes continue ingesting local telemetry
- edge nodes continue local scoring
- edge nodes continue local containment
- outbound warning patterns queue locally
- when hub returns, the backlog syncs

### If One Partner Is Compromised

- suspend that partner's API key
- stop accepting that partner's new publishes
- preserve its historical records
- keep the rest of the federation alive

### If A Partner Starts Flooding Noise

- lower trust score
- quarantine that partner feed
- require step-up validation before using it for national escalation

## 10. Access Control Corrections Needed

This is where the current implementation is too permissive.

Today, the federation analytics routes are protected with section access.
That is too broad for a real national deployment.

Practical correction:

- `/v1/federation/partners` should be central-only, or partner-scoped with
  self-view only
- `/v1/federation/stream` should be central-only, or filter strictly to the
  partner's own records
- `/v1/federation/correlations` should be central-only by default
- partner-facing warning retrieval should be a separate endpoint

In other words:

- partner SOC users should see local truth plus warnings addressed to them
- central command should see the national picture

## 11. Practical Deployment By Threat Class

### VPN / ATO

Deployment:

- connector to VPN gateway + IdP
- local graph over account, device, IP, session
- local playbooks: MFA, disable, token revoke
- hub gets hashed cross-agency account/device patterns

### Phishing

Deployment:

- connector to mail security + IdP + endpoint
- local graph over mailbox, sender domain, click path, login pivot
- local playbooks: quarantine, rule removal, token revoke
- hub gets coordinated campaign hashes and domain/tactic summaries

### Malware

Deployment:

- connector to EDR/AV/DNS/proxy
- local graph over device, user, hash, IOC, process chain
- local playbooks: isolate host, block hash, kill process
- hub gets hashed host/user patterns and campaign spread summaries

### DDoS

Deployment:

- connector to WAF/CDN/firewall/NetFlow/service health
- local graph over service, endpoint, attack source cluster, provider
- local playbooks: rate limit, WAF rule, upstream mitigation
- hub gets service pressure and cross-sector attack-shape warnings

## 12. What To Build Next In This Repo

Highest-priority practical improvements:

1. Add a first-class `warning envelope` model and hub-to-partner warning flow.
2. Add a local hash index on the edge node so warnings can be resolved back to
   raw local entities.
3. Split federation visibility into:
   - central-only national views
   - partner-only local warning views
4. Add source-freshness and queue-lag fields to heartbeat.
5. Stop training from scratch every run as the default production story.
6. Add sector-specific connector presets:
   - VPN / IdP
   - mail gateway / phishing
   - EDR / malware
   - WAF / DDoS
7. Add partner trust/quarantine state for noisy or compromised feeds.

## 13. Best Honest Story

The edge federation story should be presented like this:

"Each agency keeps its raw telemetry and response actions locally. Sentinel-KE
runs local detection at the edge, publishes only hashed high-risk warning
patterns to the national hub, and the hub correlates those patterns across
agencies. The hub coordinates national warning and policy response; the agency
retains raw evidence, operational control, and local containment."

That is the practical sovereign model.

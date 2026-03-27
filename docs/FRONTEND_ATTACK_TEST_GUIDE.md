# Sentinel-KE Frontend Attack Test Guide

**System state**: Stack fully running (`docker compose up -d` already active)
**Backend**: http://localhost:8000
**Frontend**: http://localhost:3000
**Tested**: 2026-03-27

---

## Credentials

```bash
# Admin login
USERNAME=admin
PASSWORD=Sentinel@Admin2025!

# Source API keys (seeded defaults)
SAFARICOM_KEY=safaricom-secret-key   # telecom events
KCB_KEY=kcb-secret-key               # bank/transaction events
KPA_KEY=kpa-secret-key               # gov/infra events

# Get Bearer token (valid for 1 hour)
TOKEN=$(curl -s http://localhost:8000/v1/auth/login \
  -X POST -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"Sentinel@Admin2025!"}' \
  | python3 -c "import json,sys; print(json.load(sys.stdin).get('access_token',''))")
```

---

## Valid Anchor Keys (critical — wrong keys = 422 error)

Anchors must use ONLY these keys:
- `phone_h` — pseudonymized phone (NOT `phone`)
- `account_h` — pseudonymized account (NOT `account_from`/`account_to`)
- `ip` — raw IP address ✓
- `device_id` — device identifier ✓
- `service_id` — service name ✓
- `domain` — domain name ✓
- `person_h` — pseudonymized person ID

---

## Attack Scenario 1: SIM Swap → VPN Login → Mule Ring

**Frontend screens to watch**: LiveFeed, Campaigns, InfraCorrelation, EntityInvestigation

### Inject events

```bash
SAFARICOM_KEY=safaricom-secret-key
KCB_KEY=kcb-secret-key
MINUS15=$(date -u -d '-15 minutes' +'%Y-%m-%dT%H:%M:%SZ')
MINUS5=$(date -u -d '-5 minutes' +'%Y-%m-%dT%H:%M:%SZ')
NOW=$(date -u +'%Y-%m-%dT%H:%M:%SZ')

# Step 1: SIM swap (attacker takes over victim's number)
curl -s -X POST http://localhost:8000/v1/ingest/event \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $SAFARICOM_KEY" \
  -d "{
    \"event_type\": \"SIM_SWAP_EVENT\",
    \"occurred_at\": \"$MINUS15\",
    \"source_api_key\": \"$SAFARICOM_KEY\",
    \"classification\": \"RESTRICTED\",
    \"section_code\": \"telecom\",
    \"schema_version\": \"1.0\",
    \"anchors\": {\"phone_h\": \"phone_victim_01_h\"},
    \"payload\": {
      \"phone\": \"254712111222\",
      \"prev_sim_id\": \"89254099999111000\",
      \"new_sim_id\": \"89254099999111999\",
      \"reason\": \"device_lost\"
    }
  }"

# Step 2: Attacker logs in from Tor VPN exit node
curl -s -X POST http://localhost:8000/v1/ingest/event \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $SAFARICOM_KEY" \
  -d "{
    \"event_type\": \"LOGIN_EVENT\",
    \"occurred_at\": \"$MINUS5\",
    \"source_api_key\": \"$SAFARICOM_KEY\",
    \"classification\": \"RESTRICTED\",
    \"section_code\": \"telecom\",
    \"schema_version\": \"1.0\",
    \"anchors\": {\"ip\": \"185.220.101.5\", \"device_id\": \"dev-tor-01\"},
    \"payload\": {
      \"username\": \"victim_01\",
      \"ip\": \"185.220.101.5\",
      \"asn\": 60729,
      \"provider\": \"tor-exit-relay\",
      \"device_id\": \"dev-tor-01\",
      \"outcome\": \"success\"
    }
  }"

# Step 3: Transfer to mule account (device_id links to VPN login)
curl -s -X POST http://localhost:8000/v1/ingest/event \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $KCB_KEY" \
  -d "{
    \"event_type\": \"TRANSACTION_EVENT\",
    \"occurred_at\": \"$NOW\",
    \"source_api_key\": \"$KCB_KEY\",
    \"classification\": \"RESTRICTED\",
    \"section_code\": \"bank\",
    \"schema_version\": \"1.0\",
    \"anchors\": {\"account_h\": \"acct_victim_01_h\", \"device_id\": \"dev-tor-01\"},
    \"payload\": {
      \"account_from\": \"254712111222\",
      \"account_to\": \"254733444001\",
      \"amount\": 95000,
      \"currency\": \"KES\",
      \"channel\": \"mobile_money\",
      \"device_id\": \"dev-tor-01\",
      \"agent_id\": \"AGENT_MULE_A\"
    }
  }"

# Step 4: Second mule transfer (same device → mule ring pattern)
curl -s -X POST http://localhost:8000/v1/ingest/event \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $KCB_KEY" \
  -d "{
    \"event_type\": \"TRANSACTION_EVENT\",
    \"occurred_at\": \"$NOW\",
    \"source_api_key\": \"$KCB_KEY\",
    \"classification\": \"RESTRICTED\",
    \"section_code\": \"bank\",
    \"schema_version\": \"1.0\",
    \"anchors\": {\"account_h\": \"acct_victim_01_h\", \"device_id\": \"dev-tor-01\"},
    \"payload\": {
      \"account_from\": \"254712111222\",
      \"account_to\": \"254733444002\",
      \"amount\": 72500,
      \"currency\": \"KES\",
      \"channel\": \"mobile_money\",
      \"device_id\": \"dev-tor-01\",
      \"agent_id\": \"AGENT_MULE_B\"
    }
  }"
```

### What to check in the frontend

| Screen | URL | What to see |
|--------|-----|-------------|
| **LiveFeed** | http://localhost:3000 (default) | SIM_SWAP_EVENT, LOGIN_EVENT, TRANSACTION_EVENT all appearing in real-time feed |
| **Campaigns** | Campaigns tab | VPN_IP_REUSE campaigns; MULE_RING campaigns (after worker runs) |
| **InfraCorrelation** | Infra tab | `185.220.101.5` in a vpn_exit cluster |
| **EntityInvestigation** | Search `ip:185.220.101.5` | Graph showing: IP → device → accounts chain |
| **GraphExplorer** | Graph tab | Entity relationship: sim_swap → login → transactions |

---

## Attack Scenario 2: DDoS Escalation

**Frontend screen**: OperationsCenter

### Inject 5 escalating DDoS bursts

```bash
KPA_KEY=kpa-secret-key
NOW=$(date -u +'%Y-%m-%dT%H:%M:%SZ')

for REQ_RATE in 300 350 400 450 500; do
  curl -s -X POST http://localhost:8000/v1/ingest/event \
    -H "Content-Type: application/json" \
    -H "X-API-Key: $KPA_KEY" \
    -d "{
      \"event_type\": \"DDOS_SIGNAL_EVENT\",
      \"occurred_at\": \"$NOW\",
      \"source_api_key\": \"$KPA_KEY\",
      \"classification\": \"RESTRICTED\",
      \"section_code\": \"gov\",
      \"schema_version\": \"1.0\",
      \"anchors\": {\"service_id\": \"mpesa-api\"},
      \"payload\": {
        \"service_id\": \"mpesa-api\",
        \"endpoint\": \"/v1/pay\",
        \"req_rate\": $REQ_RATE,
        \"unique_ips_count\": 60,
        \"error_rate\": 0.04,
        \"avg_latency_ms\": 150,
        \"endpoint_convergence\": 0.75,
        \"asn_concentration\": 0.65
      }
    }" | python3 -c "import json,sys; d=json.load(sys.stdin); print(f'  req_rate=$REQ_RATE: {d.get(\"status\",\"?\")}')"
done
```

### What to check in the frontend

| Screen | What to see |
|--------|-------------|
| **OperationsCenter** | `mpesa-api` alert appearing; stage escalating from `normal` → `elevated` → `attack`; reason_codes: ENDPOINT_CONVERGENCE, ERROR_RATE_UP |
| **LiveFeed** | DDOS_SIGNAL_EVENT burst sequence |
| **EntityInvestigation** | `service:mpesa-api` entity with elevated GNN risk score |

### Verify via API

```bash
curl -s "http://localhost:8000/v1/ddos/alerts?limit=10" \
  -H "Authorization: Bearer $TOKEN" | python3 -c "
import json,sys
d=json.load(sys.stdin)
for a in d.get('items',[]):
    if a.get('service_id')=='mpesa-api':
        print(f'stage={a[\"stage\"]} risk={a[\"risk\"]:.1f} codes={a[\"reason_codes\"]}')
"
```

---

## Attack Scenario 3: VPN Infrastructure Reuse (Multi-target)

**Frontend screen**: InfraCorrelation

### Inject 5 logins from same VPN provider (different IPs, same ASN)

```bash
SAFARICOM_KEY=safaricom-secret-key
NOW=$(date -u +'%Y-%m-%dT%H:%M:%SZ')

for LAST_OCTET in 1 2 3 4 5; do
  curl -s -X POST http://localhost:8000/v1/ingest/event \
    -H "Content-Type: application/json" \
    -H "X-API-Key: $SAFARICOM_KEY" \
    -d "{
      \"event_type\": \"LOGIN_EVENT\",
      \"occurred_at\": \"$NOW\",
      \"source_api_key\": \"$SAFARICOM_KEY\",
      \"classification\": \"RESTRICTED\",
      \"section_code\": \"telecom\",
      \"schema_version\": \"1.0\",
      \"anchors\": {\"ip\": \"185.220.200.$LAST_OCTET\", \"device_id\": \"vpn-cluster-dev-$LAST_OCTET\"},
      \"payload\": {
        \"username\": \"target_user_$LAST_OCTET\",
        \"ip\": \"185.220.200.$LAST_OCTET\",
        \"asn\": 60729,
        \"provider\": \"mullvad-vpn\",
        \"device_id\": \"vpn-cluster-dev-$LAST_OCTET\",
        \"outcome\": \"success\"
      }
    }" | python3 -c "import json,sys; d=json.load(sys.stdin); print(f'  IP=185.220.200.$LAST_OCTET: {d.get(\"status\",\"?\")}')"
done
```

### What to check in the frontend

| Screen | What to see |
|--------|-------------|
| **InfraCorrelation** | New `mullvad-vpn` cluster with 5 member IPs; `endpoint_overlap` reason; confidence score |
| **EntityInvestigation** | Click any IP → see cluster membership, shared provider attribution |

---

## Attack Scenario 4: Malware C2 Beacon (DFIR Finding)

**Frontend screen**: LiveFeed (DFIR events), GNNIntelligence (risk prediction on host IP)

### Inject malware C2 beacon finding

```bash
KPA_KEY=kpa-secret-key
NOW=$(date -u +'%Y-%m-%dT%H:%M:%SZ')

curl -s -X POST http://localhost:8000/v1/ingest/event \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $KPA_KEY" \
  -d "{
    \"event_type\": \"DFIR_FINDING_EVENT\",
    \"occurred_at\": \"$NOW\",
    \"source_api_key\": \"$KPA_KEY\",
    \"classification\": \"RESTRICTED\",
    \"section_code\": \"gov\",
    \"schema_version\": \"1.0\",
    \"anchors\": {\"ip\": \"185.220.101.5\", \"device_id\": \"safaricom-ws-007\"},
    \"payload\": {
      \"source\": \"velociraptor\",
      \"host\": \"safaricom-workstation-007\",
      \"artifact_name\": \"Windows.Network.NetstatEnriched\",
      \"finding_type\": \"c2_beacon\",
      \"severity\": \"critical\",
      \"sha256\": \"a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4\",
      \"command_line\": \"powershell -enc SQBFAFgAIAAoAE4AZQ\",
      \"c2_ip\": \"185.220.101.5\",
      \"c2_port\": 4444
    }
  }"

# Inject web attack from same IP (corroborating evidence)
curl -s -X POST http://localhost:8000/v1/ingest/event \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $KPA_KEY" \
  -d "{
    \"event_type\": \"WEB_ATTACK_EVENT\",
    \"occurred_at\": \"$NOW\",
    \"source_api_key\": \"$KPA_KEY\",
    \"classification\": \"RESTRICTED\",
    \"section_code\": \"gov\",
    \"schema_version\": \"1.0\",
    \"anchors\": {\"ip\": \"185.220.101.5\", \"domain\": \"safaricom.co.ke\"},
    \"payload\": {
      \"attack_type\": \"sql_injection\",
      \"ip\": \"185.220.101.5\",
      \"target_url\": \"https://safaricom.co.ke/api/accounts\",
      \"method\": \"POST\",
      \"status_code\": 500,
      \"waf_action\": \"blocked\",
      \"severity\": \"high\"
    }
  }"
```

### What to check in the frontend

| Screen | What to see |
|--------|-------------|
| **LiveFeed** | DFIR_FINDING_EVENT + WEB_ATTACK_EVENT from `kpa` source |
| **GNNIntelligence** | `ip:185.220.101.5` risk prediction elevated (same IP as DDoS + DFIR) |
| **EntityInvestigation** | Entity `ip:185.220.101.5` shows convergence: DDoS + DFIR + VPN login + Web attack |
| **Campaigns** | VPN_IP_REUSE campaign linking this IP to others |

---

## Full Combined Scenario (Quickest Demo)

Trigger the built-in `ddos_vpn_fraud` scenario — injects all event types automatically:

```bash
TOKEN=$(curl -s http://localhost:8000/v1/auth/login \
  -X POST -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"Sentinel@Admin2025!"}' \
  | python3 -c "import json,sys; print(json.load(sys.stdin).get('access_token',''))")

curl -s -X POST "http://localhost:8000/v1/demo/scenario/start/ddos_vpn_fraud" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json"
```

Available scenarios: `ddos`, `vpn`, `sim_swap`, `fraud`, `ddos_vpn`, `ddos_vpn_fraud`

---

## Frontend Navigation — Screen by Screen

Open http://localhost:3000 and navigate:

```
Dashboard (home)
├── LiveFeed          → Real-time event stream (all event types appear here first)
├── OperationsCenter  → DDoS alerts table; stage + risk + reason_codes + mitigations
├── Campaigns         → Detected attack campaigns (VPN_IP_REUSE, MULE_RING, DDOS_ENDPOINT_FANIN)
├── InfraCorrelation  → VPN clusters (vpn_exit kind, confidence, member IPs, provider)
├── EntityInvestigation → Search any entity key:
│     ip:185.220.101.5         ← the Tor/attacker IP used above
│     device:dev-tor-01        ← bridging device
│     account_h:acct_victim... ← victim account
├── GNNIntelligence   → AI risk predictions; top 5 high-risk entities
├── GraphExplorer     → Visual graph of entity relationships
└── CasePackets       → Create legal bundle from a detected campaign
```

---

## Verifying Detection via API (without opening browser)

```bash
# Events ingested
curl -s "http://localhost:8000/v1/events/search?size=5" -H "Authorization: Bearer $TOKEN" \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print(f'Total events: {d.get(\"total\",\"?\")}')"

# DDoS alerts
curl -s "http://localhost:8000/v1/ddos/alerts?limit=10" -H "Authorization: Bearer $TOKEN" \
  | python3 -c "import json,sys; [print(f'{i[\"service_id\"]} stage={i[\"stage\"]} risk={i[\"risk\"]:.0f}') for i in json.load(sys.stdin).get('items',[])]"

# Campaigns
curl -s "http://localhost:8000/v1/campaigns?limit=20" -H "Authorization: Bearer $TOKEN" \
  | python3 -c "import json,sys; d=json.load(sys.stdin); [print(f'{i[\"type\"]} score={i[\"score\"]:.2f}') for i in d.get('items',[])]"

# VPN/Infra clusters
curl -s "http://localhost:8000/v1/infra/clusters?limit=10" -H "Authorization: Bearer $TOKEN" \
  | python3 -c "import json,sys; [print(f'{c[\"kind\"]} conf={c[\"confidence\"]} members={c[\"member_count\"]}') for c in json.load(sys.stdin).get('items',[])]"

# GNN predictions
curl -s "http://localhost:8000/v1/ai/predictions?limit=10" -H "Authorization: Bearer $TOKEN" \
  | python3 -c "import json,sys; [print(f'{p[\"entity_key\"][:40]} score={p[\"risk_score\"]:.1f}') for p in json.load(sys.stdin).get('items',[])]"
```

---

## Known Constraints

| Constraint | Detail |
|-----------|--------|
| Token expiry | Bearer token valid for ~1 hour. Re-login if 401 |
| Rate limits | Ingest: 300 req/min single, 60 req/min batch |
| Mule ring detection | Requires `mule_campaign_worker` to run (runs on schedule); trigger manually: `docker compose exec backend python -m app.analytics.layer3.mule_campaign_worker --minutes 60 --min-senders 2 --min-tx 2` |
| GNN re-scoring | New entities scored on next inference cycle (runs every few minutes) |
| DDoS stage escalation | Needs multiple windows with sustained spike_z > threshold to move stage |

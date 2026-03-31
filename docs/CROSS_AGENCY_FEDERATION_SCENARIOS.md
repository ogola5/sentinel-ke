# Cross-Agency Federation Scenarios

Last updated: 2026-03-31

These are the three cross-agency scenarios now supported by the demo stack.

Use them from:

- `Command -> Scenario launcher -> Launch now`

Or from the API:

- `POST /v1/demo/scenario/start/federated_vpn`
- `POST /v1/demo/scenario/start/federated_sim_swap`
- `POST /v1/demo/scenario/start/federated_malware`

## 1. Shared VPN Exit Across Partners

- Scenario ID: `federated_vpn`
- Start screen: `Federation`
- Follow-up screen: `Threat Graph`
- Primary proof:
  - same IP hash shared by `KCB Bank Kenya`, `Equity Bank Kenya`, and `Safaricom PLC`
  - fraud family: `VPN_REUSE`
  - key flags: `shared_access_infrastructure`, `vpn_exit_node`, `cross_agency_correlation`
- Best line:
  - `This is the same masked access infrastructure touching multiple institutions. One agency alone would only see a local login pattern. The hub sees the shared national signal.`

## 2. Shared SIM-Swap Actor

- Scenario ID: `federated_sim_swap`
- Start screen: `Federation`
- Follow-up screen: `Investigate`
- Primary proof:
  - same phone hash shared by `Safaricom PLC`, `Equity Bank Kenya`, and `KCB Bank Kenya`
  - fraud family: `SIM_SWAP`
  - key flags: `sim_swap_velocity`, `account_takeover_risk`, `shared_actor_hash`, `wallet_cashout_overlap`
- Best line:
  - `This is a cross-agency fraud chain: telco takeover, bank access, and wallet movement. Sentinel-KE lets the country see one actor chain instead of three partial warnings.`

## 3. Shared Malware IOC

- Scenario ID: `federated_malware`
- Start screen: `Federation`
- Follow-up screen: `Live Feed`
- Primary proof:
  - same IOC hash shared by `KCB Bank Kenya`, `Equity Bank Kenya`, and `Kenya Computer Incident Response Team`
  - fraud family: `MALWARE_C2`
  - key flags: `shared_malware_ioc`, `banking_exposure`, `national_monitoring`
- Best line:
  - `This is the same malware infrastructure appearing across banks and the national cyber response layer. The hub can raise one shared warning without centralizing raw endpoint data.`

## Expected Correlation Output

After replay, `Federation` should show three high-confidence matches:

1. `SIM_SWAP` across `Safaricom`, `Equity`, `KCB`
2. `MALWARE_C2` across `KCB`, `Equity`, `KE-CIRT`
3. `VPN_REUSE` across `KCB`, `Equity`, `Safaricom`

## Best Demo Flow

1. Launch one cross-agency scenario from `Command`
2. Open `Federation`
3. Say what the shared story is in one sentence
4. Open the follow-up screen to show the operational detail

## Best Positioning

- `Federation` proves privacy-preserving cross-agency correlation
- `Threat Graph` proves shared infrastructure
- `Investigate` proves explainable prioritization
- `Live Feed` proves the signals are entering through the real ingest path


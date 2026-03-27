# External Containment Demo

This runbook turns Sentinel-KE's existing containment webhook support into a judge-safe demo of a real partner control plane.

Use this when you need to answer:

- `Can Sentinel-KE call a real external control plane?`
- `When do you contain, and when do you hold back?`
- `Does containment mean shutting down the internet?`

The honest answer is:

- Sentinel-KE dispatches bounded containment actions through signed webhooks.
- The first production step is almost never "shut everything down".
- The escalation ladder should be `observe -> challenge -> rate limit -> isolate specific assets -> upstream scrubbing/blocking`.

## 1) What Sentinel-KE Already Supports

The hub already has real webhook registration and delivery endpoints:

- `POST /v1/defense/webhooks`
- `GET /v1/defense/webhooks`
- `GET /v1/defense/webhooks/deliveries`

The dispatcher signs each outbound payload with:

- `X-Sentinel-Signature: sha256=<hmac>`

The current remote action families are:

- `block_ip`
- `unblock_ip`
- `isolate_host`
- `rate_limit_service`
- `enable_waf_challenge`
- `reroute_to_scrubber`
- `quarantine_email`
- `freeze_account`
- `hold_cashout`
- `suspend_sim_change`

See:

- [executor.py](/home/ogola/personal/sentinel-ke/backend/app/defense/executor.py)
- [defense.py](/home/ogola/personal/sentinel-ke/backend/app/api/defense.py)

## 2) Demo Boundary

There are three claim levels:

1. `Internal proof`
Sentinel-KE dispatches to its built-in self-test receiver. Good for engineering proof, weaker for judges.

2. `External partner simulator`
Sentinel-KE dispatches to a separate process that verifies HMAC, accepts only chosen action types, and stores receipts. This is the recommended demo level.

3. `Real production partner`
Sentinel-KE dispatches to an actual WAF, CDN, EDR, telco, or banking control plane. This is the strongest level, but only claim it if the partner is truly connected.

## 3) Start the External Partner Simulator

### Option A — Separate container on the same Docker network

This is the most reliable local demo path on Linux because the backend container can reach the partner by container name.

Verified route:

- partner host: `http://sentinel-ke-notebook-1:18102/apply`
- action delivered: `enable_waf_challenge`
- Sentinel delivery status: `delivered`
- partner receipt: `signature_verified: true`, `status: accepted`

### Option B — Host process

Run the simulator on the host:

```bash
python3 backend/scripts/run_partner_control_plane.py \
  --host 0.0.0.0 \
  --port 18100 \
  --shared-secret sentinel-demo-shared-secret \
  --accept-action enable_waf_challenge \
  --accept-action rate_limit_service \
  --receipts-file /tmp/sentinel_partner_receipts.json
```

Health check:

```bash
curl -sS http://localhost:18100/health
curl -sS http://localhost:18100/receipts
```

What this proves:

- the endpoint is external to the hub process
- the endpoint verifies Sentinel signatures
- the endpoint keeps an independent receipt log

## 4) Register It with Sentinel-KE

Register the partner endpoint as a containment webhook:

```bash
curl -sS -X POST "http://localhost:8000/v1/defense/webhooks" \
  -H "Authorization: Bearer <central_access_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "section_code": "ecitizen",
    "action_type": "enable_waf_challenge",
    "webhook_url": "http://host.docker.internal:18100/apply",
    "secret": "sentinel-demo-shared-secret"
  }'
```

If `host.docker.internal` is not available on your runtime, either:

- use the Docker bridge gateway IP reachable from the backend container, or
- prefer Option A and run the partner simulator in a separate container on the same Docker network.

List registered hooks:

```bash
curl -sS "http://localhost:8000/v1/defense/webhooks" \
  -H "Authorization: Bearer <central_access_token>"
```

## 5) Trigger a Real Demo Action

Recommended path:

1. Run a cyber scenario such as the eCitizen DDoS proof.
2. Let detection, graph, and GNN evidence populate first.
3. Create or reuse an incident run.
4. Execute a bounded action such as `enable_waf_challenge`.

Example action call:

```bash
curl -sS -X POST "http://localhost:8000/v1/defense/incidents/runs/<run_id>/actions" \
  -H "Authorization: Bearer <section_or_central_access_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "actions": [
      {
        "action_type": "enable_waf_challenge",
        "target": "service_id:ecitizen",
        "details": {
          "reason": "active ddos pressure on login flow"
        }
      }
    ]
  }'
```

Then show:

- Sentinel receipt log:
  - `GET /v1/defense/webhooks/deliveries`
- Partner receipt log:
  - `GET http://localhost:18100/receipts`

Verified local container demo result:

- webhook registration updated for `section_code=ecitizen`, `action_type=enable_waf_challenge`
- incident run created successfully
- action execution summary: `executed=1`, `failed=0`, `no_integration=0`
- Sentinel delivery receipt status: `delivered`, `http_status_code=200`
- partner receipt status: `accepted`, `signature_verified=true`

## 6) When Containment Should Trigger

This is the correct escalation ladder for the demo:

### Stage A — Observe

Use when:

- risk is low
- graph support is weak
- evidence hashes are thin
- confidence is still mixed

Typical action:

- no containment
- analyst review only

### Stage B — Friction, Not Disruption

Use when:

- DDoS or abuse pressure is real
- availability matters
- attribution is still developing

Typical actions:

- `enable_waf_challenge`
- `rate_limit_service`

This is usually the best judge demo.

### Stage C — Asset Isolation

Use when:

- a host, account, mailbox, or SIM change path is strongly implicated
- false-positive risk is lower

Typical actions:

- `isolate_host`
- `quarantine_email`
- `freeze_account`
- `hold_cashout`
- `suspend_sim_change`

### Stage D — Upstream Network Suppression

Use only when:

- evidence is strong
- operational impact is severe
- the partner control plane is appropriate

Typical actions:

- `block_ip`
- `reroute_to_scrubber`

Do not present containment as "shutting down the internet". Present it as `bounded response matched to evidence quality and service risk`.

## 7) Judge-Safe Wording

Say:

> "Sentinel-KE does not jump straight to broad blocking. It first detects pressure, relates entities in the graph, scores risk, and then escalates through bounded controls such as challenge, throttling, isolation, or partner scrubbing."

Do not say:

- `The GNN automatically shuts down hostile traffic.`
- `We shut off the whole service when a score crosses a threshold.`
- `This proves attribution.`

## 8) Strongest Demo Flow

The strongest live demo is:

1. show detection on `Live Feed` or `Dashboard`
2. show structural correlation on `Threat Graph` or `Investigate`
3. show GNN + path + fusion in `Investigate`
4. show `Defense`
5. execute `enable_waf_challenge`
6. show signed delivery receipts in both Sentinel and the partner simulator

That is enough to honestly say:

> "Containment works as a real signed cross-system workflow."

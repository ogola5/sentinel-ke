# Edge Agency MVP Demo

This is the cleanest way to show one agency edge station in the MVP demo.

The goal is to prove four things:

- the agency keeps raw telemetry locally
- the agency scores and acts locally
- only hashes go to the hub
- the hub can send a warning back that the agency resolves locally

## 1. What Is Ready In The Repo

The current edge-agency path is viable for a demo:

- `docker-compose.edge.yml` runs a full local agency station:
  - backend
  - frontend
  - graph features
  - inference
  - threat patterns
  - decision fusion
  - edge sync
  - postgres
  - redpanda
- `backend/app/sync/edge_agent.py` pushes hashed high-risk patterns to the hub
- `backend/app/api/federation.py` exposes `GET /v1/federation/edge-status`
- `frontend/src/screens/govern/FederationDashboard.tsx` already shows local edge sync state when `is_edge_node=true`
- the standalone `edge-agent/` service still exists if you want a second terminal-only proof, but the full MVP demo should use `docker-compose.edge.yml`

## 2. Startup

On the agency machine:

```bash
cd ~/personal/sentinel-ke
cp .env.edge.example .env.edge
```

Fill these values in `.env.edge`:

- `EDGE_PARTNER_ID`
- `EDGE_HUB_URL`
- `EDGE_HUB_API_KEY`
- `EDGE_NATIONAL_SALT`

Those come from the central hub onboarding call:

```bash
curl -sS -X POST http://localhost:8000/v1/federation/register \
  -H 'Authorization: Bearer <central-token>' \
  -H 'Content-Type: application/json' \
  -d '{
    "partner_name": "Safaricom SOC",
    "partner_id": "safaricom-ke",
    "sector": "telecommunications"
  }'
```

Then start the agency station:

```bash
docker compose --env-file .env.edge -f docker-compose.edge.yml up -d --build
```

## 3. Agency Login

The edge station example env enables a local analyst login:

- username: `edge_admin`
- password: `EdgeDemo2026!`

Open:

- local analyst UI: `http://localhost:13000`
- local API: `http://localhost:18000`

## 4. Seed A Local Agency Scenario

Use the local backend on the agency machine:

```bash
docker compose --env-file .env.edge -f docker-compose.edge.yml exec backend \
  python -m app.demo.run_demo --seed-sources --scenario ddos_vpn_fraud
```

Then let the local workers score it. If you want to force a fresh cycle:

```bash
docker compose --env-file .env.edge -f docker-compose.edge.yml exec backend \
  python -m app.analytics.layer3.graph_feature_worker --window-key Wmid
```

```bash
docker compose --env-file .env.edge -f docker-compose.edge.yml exec backend \
  python -m app.analytics.layer3.gnn_train_worker --window-key Wmid --prediction-type risk_gnn --epochs 5
```

```bash
docker compose --env-file .env.edge -f docker-compose.edge.yml exec backend \
  python -m app.analytics.layer3.ai_inference_worker --window-key Wmid --prediction-type risk_gnn --max-entities 1000
```

## 5. What To Show On The Agency Screen

Open the agency station frontend and show this order:

1. `Command`
2. `GNN Intelligence`
3. `Investigate`
4. `Federation`

What to say:

- `Command`: "This is the agency's local operating picture. Raw telemetry is still inside the agency."
- `GNN Intelligence`: "The local graph and model score the agency's own entities first."
- `Investigate`: "The agency analyst sees raw evidence locally and can decide what to do."
- `Federation`: "Only the hashed warning pattern leaves the agency."

## 6. What To Show In Terminal

Local edge sync state:

```bash
curl -sS http://localhost:18000/v1/federation/edge-status \
  -H 'Authorization: Bearer <agency-user-token>'
```

What you want:

- `is_edge_node: true`
- `status: healthy`
- `total_pushed > 0`
- `last_error: null`

If you want to show sync-worker logs:

```bash
docker compose --env-file .env.edge -f docker-compose.edge.yml logs edge-sync-agent --tail=40
```

What you want to point at:

- local push happened
- no raw identifiers are in the payload
- only hash-based patterns were pushed

## 7. What To Show On The Central Hub

On the central hub frontend:

1. `Command`
2. `Federation`

What to say:

- "The hub sees the agency as online."
- "The hub sees correlated hashes, not raw phone numbers or raw accounts."
- "The hub can issue a warning without taking the agency's raw data."

If you want one terminal proof on the hub:

```bash
curl -sS http://localhost:8000/v1/federation/partners?limit=10 \
  -H 'Authorization: Bearer <central-token>'
```

```bash
curl -sS http://localhost:8000/v1/federation/correlations?limit=10 \
  -H 'Authorization: Bearer <central-token>'
```

## 8. The Best 90-Second Story

Use one agency only.

Story:

1. Seed `ddos_vpn_fraud` locally at the agency
2. Show the local agency `Command` page
3. Open `Investigate` and show the local evidence
4. Open local `Federation` and show `Local edge sync state`
5. Switch to the central hub `Federation` screen
6. Show the partner online and the cross-agency correlation row

This proves:

- local detection
- local visibility
- privacy-preserving sharing
- central coordination

## 9. Most Important Caveat

For the MVP demo, do not try to show:

- multiple agencies booting from scratch live
- hub-down resilience live unless already rehearsed
- every connector type in one run

One strong agency edge story is enough:

- local detection
- hashed publish
- central correlation
- warning-ready coordination

## 10. Three-Minute Judge Script

Use this if you need a short, repeatable demo.

### Before judges arrive

Central hub:

```bash
curl -sS http://localhost:8000/health
curl -sS http://localhost:8000/ready
```

Agency station:

```bash
docker compose --env-file .env.edge -f docker-compose.edge.yml up -d --build
docker compose --env-file .env.edge -f docker-compose.edge.yml exec backend \
  python -m app.demo.run_demo --seed-sources --scenario ddos_vpn_fraud
```

Optional local refresh:

```bash
docker compose --env-file .env.edge -f docker-compose.edge.yml exec backend \
  python -m app.analytics.layer3.graph_feature_worker --window-key Wmid
docker compose --env-file .env.edge -f docker-compose.edge.yml exec backend \
  python -m app.analytics.layer3.ai_inference_worker --window-key Wmid --prediction-type risk_gnn --max-entities 1000
```

### Minute 0:00 to 0:30 — Open agency view

Open:

- agency frontend: `http://localhost:13000`

Log in:

- username: `edge_admin`
- password: `EdgeDemo2026!`

Screen:

- `Command`

Say:

- "This is one agency edge station."
- "Raw telemetry, local evidence, and local response stay inside the agency."

### Minute 0:30 to 1:10 — Show local detection

Open:

- `GNN Intelligence`
- then `Investigate`

Say:

- "The agency builds a local graph and scores its own entities first."
- "The analyst sees the raw local evidence here before anything is shared nationally."
- "This is the local decision point, not the hub."

### Minute 1:10 to 1:40 — Show privacy-preserving sync

Open:

- `Federation`

Expand:

- `Local edge sync state`

Say:

- "Only hashed high-risk patterns leave the agency."
- "The central hub does not receive raw phone numbers, raw accounts, or local evidence."
- "This panel shows the local sync health and push count from the agency itself."

Optional terminal proof:

```bash
curl -sS http://localhost:18000/v1/federation/edge-status \
  -H 'Authorization: Bearer <agency-token>'
```

Point at:

- `is_edge_node`
- `status`
- `total_pushed`

### Minute 1:40 to 2:30 — Switch to the central hub

Open the central frontend and log in as the central user.

Screens:

- `Command`
- `Federation`

Say:

- "The hub sees partner readiness and cross-agency matches."
- "It sees hashes, warning families, and confidence, not the agency's raw identifiers."
- "That lets national command coordinate without turning the hub into a raw-data lake."

Point at:

- partner online status
- cross-agency correlation row
- `Agency keeps` vs `Hub sees`

### Minute 2:30 to 3:00 — Close the story

Say:

- "The agency keeps local control."
- "The hub only gets the minimum needed for national coordination."
- "That is how Sentinel-KE scales across banks, telcos, and public agencies without forcing raw-data exposure."

## 11. Best Single Sentence

If you only need one line:

- "Each agency runs local detection and local response, then shares only hashed warning patterns to the hub for national correlation."

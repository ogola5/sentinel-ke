# Render + Vercel Deployment

This repo is now configured for the deployment split below:

- `Render`: runtime API only
- `Local Docker`: heavy ML / GNN workers
- `Vercel`: frontend

## What Was Corrected

- The backend Docker image now supports a real split build:
  - `INSTALL_ALL_REQUIREMENTS=0` installs `requirements-runtime.txt`
  - `INSTALL_ALL_REQUIREMENTS=1` additionally installs full `requirements.txt`
- Local `docker compose` still defaults to `INSTALL_ALL_REQUIREMENTS=1`, so your workstation keeps full ML capability.
- `render.yaml` now matches the intended architecture:
  - API on Render
  - Postgres on Render
  - no ML worker on Render
- Optional services degrade cleanly:
  - `/ready` reports `opensearch=disabled` and `neo4j=disabled`
  - event search / timeline fall back to Postgres when OpenSearch is unavailable
- Frontend production builds can use either `VITE_API_BASE_URL` or `VITE_API_URL`
- `frontend/vercel.json` handles SPA route rewrites without rewriting `/assets/*` or other static files

## Honest Constraints

This Render blueprint does **not** provide a full managed replacement for local infrastructure.

What works well on Render-only:

- auth
- API routes backed by Postgres
- AI prediction reads from Postgres
- reports
- corruption/cyber dashboards that read persisted metrics/predictions
- event search/timeline via Postgres fallback

What stays limited without extra managed services:

- OpenSearch-native analytics
- Neo4j-native graph exploration
- Kafka/Redpanda streaming
- local PyTorch training/inference

If you later want those in the cloud, add managed services separately.

## Recommended Architecture

1. Deploy the runtime API and Postgres with Render Blueprint.
2. Point the frontend on Vercel at the Render backend URL.
3. Run local ML/GNN workers against the **same Render Postgres** using the external database URL from Render.

That gives you:

- stable public API
- public frontend
- heavy ML stays on your laptop/workstation
- predictions and model runs still appear in the deployed backend because both environments write to the same database

## Render Deploy

### 1. Deploy the Blueprint

Render reads [render.yaml](/home/ogola/personal/sentinel-ke/render.yaml).

It creates:

- `sentinel-pg`
- `sentinel-backend`

### 2. Required Render Environment Values

Render can auto-generate most secrets already declared in the blueprint, but you must set these manually after the first blueprint sync:

- `AUTH_BOOTSTRAP_ADMIN_PASSWORD`
- `CORS_ALLOW_ORIGINS`
- `LEGAL_APPROVER_SECRETS`

Recommended secret generation:

```bash
openssl rand -hex 32
```

Use one value each for:

- `AUTH_TOKEN_SECRET`
- `AUTH_MFA_SECRET_KEY`
- `AUTH_PASSWORD_PEPPER`
- `WEBHOOK_SECRET_ENCRYPTION_KEY`

If you keep the blueprint-generated values, make sure they exist and stay stable.

### 3. Verify Backend

After deploy:

```bash
curl -sS https://YOUR-RENDER-BACKEND.onrender.com/health
curl -sS https://YOUR-RENDER-BACKEND.onrender.com/ready
curl -sS https://YOUR-RENDER-BACKEND.onrender.com/docs
```

Expected shape:

- `/health` => `status=ok`
- `/ready` => `status=ok`, `postgres=ok`, optional services `disabled`

## Vercel Deploy

### 1. Vercel Project Settings

- Root Directory: `frontend`
- Framework: `Vite`
- Build Command: `npm run build`
- Output Directory: `dist`

### 2. Vercel Environment Variables

Set:

- `VITE_API_BASE_URL=https://YOUR-RENDER-BACKEND.onrender.com`

Optional:

- `VITE_API_KEY=<FRONTEND_API_KEY from Render>` if you want service-key backed SSE usage

### 3. After Vercel Deploy

Set Render CORS to the exact Vercel URL:

```text
CORS_ALLOW_ORIGINS=https://YOUR-APP.vercel.app
```

Then redeploy Render.

### 4. Important Vercel Rewrite Rule

The frontend must rewrite only application routes to `index.html`.

It must **not** rewrite:

- `/assets/*`
- files with extensions such as `.js`, `.css`, `.svg`, `.woff`, `.json`

If those are rewritten to `index.html`, the browser will fail with errors like:

- `Expected a JavaScript module script but the server responded with text/html`
- dynamic import failures on chunk files such as `CentralCommand-*.js`

## Local ML / GNN Against Render Postgres

This is the key step that keeps AI heavy lifting off Render.

### 1. Get the External Database URL

From Render Postgres, copy the **external** connection string.

It should look like:

```text
postgresql://USER:PASSWORD@HOST:PORT/DB?sslmode=require
```

### 2. Run Local Workers Against That Database

Use [`.env.render-ml.example`](/home/ogola/personal/sentinel-ke/.env.render-ml.example) as the template for the values your local ML workers need.

Example `./.env.render-ml`:

```env
DATABASE_URL=postgresql+psycopg2://USER:PASSWORD@HOST:PORT/DB?sslmode=require
APP_ENV=production
KAFKA_ENABLED=false
OPENSEARCH_HOST=disabled
NEO4J_URI=disabled
GNN_EDGE_BACKEND=postgres
```

There is now a helper override file for this workflow:

- [docker-compose.render-ml.yml](/home/ogola/personal/sentinel-ke/docker-compose.render-ml.yml)

It layers `.env.render-ml` on top of your normal `.env` for the heavy local worker services only.

Example:

```bash
cp .env.render-ml.example .env.render-ml
docker compose -f docker-compose.yml -f docker-compose.render-ml.yml up -d \
  graph-feature-worker cyber-train-worker corruption-train-worker inference-consumer
```

Exact commands depend on which local services you want running, but the principle is:

- local workers
- remote Render Postgres
- same schema
- same AI tables

When the local workers write:

- `gnn_training_run`
- `ai_prediction`
- `ai_explanation`
- `graph_feature_snapshot`

the Render backend will read them immediately.

## Deployment Truths

- The backend uses bearer-token auth, not cookie-based auth. No cookie rewrite is needed for Vercel.
- `requirements.txt` is a normal text file in this repo.
- `render_startup.sh` bootstraps metadata and schema patches; it does not run Alembic migrations.
- Claude’s suggested `SKIP_OPTIONAL_SERVICES_IN_READY` env var does not exist in this repo. The code was patched instead.

## Minimum Working Order

1. Push the patched repo.
2. Deploy `render.yaml` on Render.
3. Verify `/health`, `/ready`, `/docs`.
4. Deploy frontend on Vercel with `Root Directory=frontend`.
5. Set `VITE_API_BASE_URL` in Vercel.
6. Set `CORS_ALLOW_ORIGINS` in Render to the Vercel URL.
7. Point local ML workers at Render external Postgres.
8. Run local feature build + training + inference.
9. Verify predictions show through the deployed API/UI.

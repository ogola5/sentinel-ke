# Render Backend-Only Deployment (No ML Runtime)

Use this mode when frontend needs API only and ML training runs locally.

## Goal

- Deploy FastAPI backend for frontend consumption.
- Exclude heavy ML runtime (`torch`) from deployed backend image.
- Keep GNN/ML training in local notebook or local worker.

## 1) Build Without ML

The backend Dockerfile now supports:

- `INSTALL_ML=0` (default): skip `requirements-ml.txt`
- `INSTALL_ML=1`: install ML runtime

Dependency set for this mode:

- `backend/requirements-render.txt` (runtime-only, excludes `torch`)

For Render, set Docker build arg:

- `INSTALL_ML=0`
- `INSTALL_DEV=0`

Note:
- Current Dockerfile defaults already use backend-only mode (`INSTALL_ML=0`, `INSTALL_DEV=0`), so this is optional unless you override defaults.

You can use the provided blueprint:

- `render.yaml` (repo root) deploys backend-only defaults.

## 2) Render Environment Variables

Set these in Render for backend-only mode:

- `APP_ENV=production`
- `DB_AUTO_CREATE=false`
- `GNN_ENABLED=false`
- `KAFKA_ENABLED=false` (unless you also deploy Kafka/consumers)
- `API_AUTH_DISABLED=false`
- `FRONTEND_API_KEY=<strong-secret>`
- `CORS_ALLOW_ORIGINS=https://your-frontend-domain.com`
- `DATABASE_URL=<managed-postgres-url>`

Optional:

- `AI_API_ENABLED=false` if you want to hide `/v1/ai` endpoints completely.
- Keep `AI_API_ENABLED=true` if frontend still reads AI prediction records from DB.

Keep any other service credentials only if those integrations are actually deployed.

Ready-to-paste environment template:

- `.env.render.backend-only` (repo root)

Notes:

- Keep `DB_AUTO_CREATE=false` in production.
- `backend/scripts/render_startup.sh` bootstraps schema from ORM metadata before app start, so first boot on a fresh Render Postgres succeeds without enabling ML services.

## 3) Local ML Continues Separately

Run ML/GNN locally (not on Render backend):

- Notebook service with ML image:
  - `docker compose build notebook`
  - `docker compose up -d notebook`
- Local training scripts/workers keep writing predictions to your database.

## 4) Why This Is Fast

- Render backend avoids downloading/installing large ML wheels.
- API request path stays lightweight (SQL + business logic only).
- ML compute and retraining cannot slow frontend API latency.

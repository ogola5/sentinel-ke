#!/bin/sh
# =============================================================================
# render_gnn_worker.sh — Sentinel-KE GNN Training Worker (Render.com)
#
# Runs once on startup:
#   1. Wait for web service to finish DB init + schema patches
#   2. Seed synthetic data (idempotent — safe to run multiple times)
#   3. Train cyber GNN
#   4. Train corruption GNN
#
# Then loops every RETRAIN_INTERVAL_SEC (default 3600 = 1 hour)
# =============================================================================
set -e

RETRAIN_INTERVAL_SEC="${RETRAIN_INTERVAL_SEC:-3600}"
GNN_EPOCHS="${GNN_EPOCHS:-60}"
RETRAIN_EPOCHS="${RETRAIN_EPOCHS:-30}"

# ---------------------------------------------------------------------------
# 1. Fix Render DATABASE_URL prefix (same as startup script)
# ---------------------------------------------------------------------------
if echo "$DATABASE_URL" | grep -q "^postgresql://"; then
  export DATABASE_URL="postgresql+psycopg2://${DATABASE_URL#postgresql://}"
  echo "[gnn-worker] Patched DATABASE_URL driver prefix"
fi

# ---------------------------------------------------------------------------
# 2. Wait for PostgreSQL — the web service may still be doing DB_AUTO_CREATE
# ---------------------------------------------------------------------------
echo "[gnn-worker] Waiting for PostgreSQL + schema..."
python - <<'PYEOF'
import os, time, sys
from sqlalchemy import create_engine, text

engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)

for attempt in range(40):
    try:
        with engine.connect() as c:
            # Wait until the web service has created the core tables
            c.execute(text("SELECT 1 FROM graph_feature_snapshot LIMIT 1"))
        print(f"[gnn-worker] DB schema ready (attempt {attempt + 1})")
        sys.exit(0)
    except Exception as exc:
        print(f"[gnn-worker] Waiting for schema ({exc.__class__.__name__}), retry {attempt + 1}/40...")
        time.sleep(5)

print("[gnn-worker] ERROR: DB schema not ready after 200s")
sys.exit(1)
PYEOF

# ---------------------------------------------------------------------------
# 3. Seed synthetic data (idempotent)
# ---------------------------------------------------------------------------
echo "[gnn-worker] Seeding synthetic cyber data..."
python -m app.demo.synthetic_ke_gnn_data || echo "[gnn-worker] WARN: cyber seed failed (may already exist)"

echo "[gnn-worker] Seeding synthetic corruption data..."
python -m app.demo.synthetic_corruption_data || echo "[gnn-worker] WARN: corruption seed failed (may already exist)"

# ---------------------------------------------------------------------------
# 4. Build initial feature snapshots (required before training)
# ---------------------------------------------------------------------------
echo "[gnn-worker] Building cyber feature snapshots (Wmid)..."
python -m app.analytics.layer3.graph_feature_worker --window-key Wmid \
  && echo "[gnn-worker] Cyber snapshots OK" \
  || echo "[gnn-worker] WARN: cyber snapshot build failed"

# ---------------------------------------------------------------------------
# 5. Initial training run
# ---------------------------------------------------------------------------
echo "[gnn-worker] Training cyber GNN (epochs=${GNN_EPOCHS})..."
python -m app.analytics.layer3.gnn_train_worker --window-key Wmid --epochs "$GNN_EPOCHS" \
  && echo "[gnn-worker] Cyber GNN trained OK" \
  || echo "[gnn-worker] WARN: cyber GNN training failed"

echo "[gnn-worker] Training corruption GNN (epochs=${GNN_EPOCHS})..."
python -m app.analytics.corruption.train_worker --window-key Wcorruption --epochs "$GNN_EPOCHS" \
  && echo "[gnn-worker] Corruption GNN trained OK" \
  || echo "[gnn-worker] WARN: corruption GNN training failed"

# ---------------------------------------------------------------------------
# 6. Retrain loop — picks up any new data ingested via API
# ---------------------------------------------------------------------------
echo "[gnn-worker] Entering retrain loop (interval=${RETRAIN_INTERVAL_SEC}s)..."
while true; do
  sleep "$RETRAIN_INTERVAL_SEC"

  echo "[gnn-worker] Refreshing cyber feature snapshots..."
  python -m app.analytics.layer3.graph_feature_worker --window-key Wmid \
    || echo "[gnn-worker] WARN: cyber snapshot refresh failed"

  echo "[gnn-worker] Retraining cyber GNN..."
  python -m app.analytics.layer3.gnn_train_worker --window-key Wmid --epochs "$RETRAIN_EPOCHS" \
    || echo "[gnn-worker] WARN: cyber retrain failed"

  echo "[gnn-worker] Retraining corruption GNN..."
  python -m app.analytics.corruption.train_worker --window-key Wcorruption --epochs "$RETRAIN_EPOCHS" \
    || echo "[gnn-worker] WARN: corruption retrain failed"
done
